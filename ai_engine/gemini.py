from __future__ import annotations

import base64
import html
import json
import logging
import re
import time
from typing import Any, Generator

from google import genai
from google.genai import errors, types

from ai_engine.personalization import build_system_prompt
from config import GEMINI_API_KEY
from services.files import restore_stored_file_for_model
from services.model_tools import (
    MAX_TOOL_CALLS_PER_ROUND,
    MAX_TOOL_CALLS_TOTAL,
    MAX_TOOL_ROUNDS,
    execute_model_tool,
    model_tool_declarations,
    serialize_tool_output,
)

logger = logging.getLogger(__name__)

GEMINI_31_FLASH_LITE_MODEL_ID = "gemini-3.1-flash-lite"
HISTORY_ATTACHMENT_MAX_COUNT = 8
HISTORY_ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024
INTERNAL_SEND_ERROR_RESPONSE = (
    "Внутренняя ошибка"
    "Произошла внутренняя ошибка при отправке вашего сообщения модели."
)
EMPTY_RESPONSE = (
    "Пустой ответ"
    "Модель не сгенерировала ответ. Это могло произойти из-за внутренних правил "
    "безопасности или временной ошибки. Пожалуйста, попробуйте еще раз."
)
DEFAULT_THINKING_LEVEL = "medium"
THINKING_LEVELS: dict[str, types.ThinkingLevel] = {
    "minimal": types.ThinkingLevel.MINIMAL,
    "low": types.ThinkingLevel.LOW,
    "medium": types.ThinkingLevel.MEDIUM,
    "high": types.ThinkingLevel.HIGH,
}
MAX_THOUGHT_SUMMARY_CHARS = 64_000
_THINK_BLOCK_RE = re.compile(r"<think(?:\s[^>]*)?>[\s\S]*?</think>", re.IGNORECASE)
MAX_SEARCH_ACTIVITY_SOURCES = 10


def _db_user_id(user_id: Any) -> int | None:
    try:
        return int(user_id) if user_id is not None else None
    except (TypeError, ValueError):
        return None


def _manual_web_search_requested(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _web_tool_enabled(user_message_data: dict[str, Any]) -> bool:
    return _manual_web_search_requested(
        user_message_data.get("webSearch")
    ) or _manual_web_search_requested(user_message_data.get("autoWebSearch"))


def _function_declarations(
    declarations: list[dict[str, Any]],
) -> list[types.FunctionDeclaration]:
    return [
        types.FunctionDeclaration(
            name=str(declaration.get("name") or ""),
            description=str(declaration.get("description") or ""),
            parameters_json_schema=declaration.get("parameters") or {
                "type": "object",
                "properties": {},
            },
        )
        for declaration in declarations
        if declaration.get("name")
    ]


def _generation_config(
    system_prompt: str,
    declarations: list[dict[str, Any]],
    *,
    force_web_search: bool,
    thinking_level: types.ThinkingLevel,
) -> types.GenerateContentConfig:
    function_declarations = _function_declarations(declarations)
    tool_config = None
    declared_names = {str(declaration.get("name") or "") for declaration in declarations}
    if force_web_search and "web_search" in declared_names:
        tool_config = types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode=types.FunctionCallingConfigMode.ANY,
                allowed_function_names=["web_search"],
            )
        )

    return types.GenerateContentConfig(
        system_instruction=system_prompt or None,
        thinking_config=types.ThinkingConfig(
            include_thoughts=True,
            thinking_level=thinking_level,
        ),
        tools=(
            [types.Tool(function_declarations=function_declarations)]
            if function_declarations
            else None
        ),
        tool_config=tool_config,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )


def _prepare_history_parts(
    parts: Any,
    restored_files: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    prepared_parts: list[dict[str, Any]] = []
    if not isinstance(parts, list):
        return prepared_parts
    for part in parts:
        if isinstance(part, dict) and part.get("text") is not None:
            text = str(part.get("text") or "").strip()
            if text:
                prepared_parts.append({"text": text})
            continue
        if not isinstance(part, dict) or not restored_files:
            continue
        attachment = part.get("image") or part.get("file")
        if not isinstance(attachment, dict):
            continue
        restored = restored_files.get(str(attachment.get("url_path") or ""))
        model_part = restored.get("model_part") if restored else None
        if isinstance(model_part, dict) and model_part:
            prepared_parts.append(model_part)
    return prepared_parts


def _prepare_history(
    history_from_main: list[dict[str, Any]],
    *,
    allow_stored_attachments: bool = False,
) -> list[dict[str, Any]]:
    restored_files: dict[str, dict[str, Any]] = {}
    remaining_bytes = HISTORY_ATTACHMENT_MAX_BYTES
    attachment_history = reversed(history_from_main or []) if allow_stored_attachments else ()
    for message in attachment_history:
        if len(restored_files) >= HISTORY_ATTACHMENT_MAX_COUNT:
            break
        parts = message.get("parts", []) if isinstance(message, dict) else []
        if not isinstance(parts, list):
            continue
        for part in reversed(parts):
            if not isinstance(part, dict):
                continue
            attachment = part.get("image") or part.get("file")
            if not isinstance(attachment, dict):
                continue
            url_path = str(attachment.get("url_path") or "")
            if not url_path or url_path in restored_files:
                continue
            restored = restore_stored_file_for_model(attachment, max_bytes=remaining_bytes)
            if not restored:
                continue
            restored_files[url_path] = restored
            remaining_bytes -= int(restored.get("size") or 0)
            if len(restored_files) >= HISTORY_ATTACHMENT_MAX_COUNT:
                break

    prepared_history: list[dict[str, Any]] = []
    for message in history_from_main or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        if role not in {"user", "model"}:
            continue
        prepared_parts = _prepare_history_parts(message.get("parts", []), restored_files)
        if not prepared_parts:
            continue
        if not prepared_history and role != "user":
            continue
        if prepared_history and prepared_history[-1]["role"] == role:
            prepared_history[-1]["parts"].extend(prepared_parts)
        else:
            prepared_history.append({"role": role, "parts": prepared_parts})
    return prepared_history


def _part_from_legacy(part: dict[str, Any]) -> types.Part | None:
    text = part.get("text")
    if text is not None:
        cleaned = _THINK_BLOCK_RE.sub("", str(text)).strip()
        return types.Part.from_text(text=cleaned) if cleaned else None

    inline_data = part.get("inline_data")
    if not isinstance(inline_data, dict):
        return None
    mime_type = str(inline_data.get("mime_type") or "")
    encoded_data = inline_data.get("data")
    if not mime_type or not isinstance(encoded_data, str):
        return None
    try:
        data = base64.b64decode(encoded_data, validate=True)
    except (ValueError, TypeError):
        return None
    return types.Part.from_bytes(data=data, mime_type=mime_type)


def _prepare_new_message(user_message_data: dict[str, Any]) -> list[types.Part]:
    content_parts: list[types.Part] = []
    text = str(user_message_data.get("message") or "")
    if text:
        content_parts.append(types.Part.from_text(text=text))

    for file_info in user_message_data.get("files", []):
        if not isinstance(file_info, dict):
            continue
        model_part = file_info.get("model_part")
        if not isinstance(model_part, dict):
            logger.warning("Attachment is missing a model payload: %s", file_info.get("original_name"))
            continue
        converted = _part_from_legacy(model_part)
        if converted is not None:
            content_parts.append(converted)
    return content_parts


def _history_for_client(user_message_data: dict[str, Any]) -> list[types.Content]:
    legacy_history = _prepare_history(
        user_message_data.get("history", []),
        allow_stored_attachments=bool(user_message_data.get("history_is_canonical")),
    )
    history: list[types.Content] = []
    for message in legacy_history:
        parts = [
            converted
            for part in message.get("parts", [])
            if isinstance(part, dict)
            and (converted := _part_from_legacy(part)) is not None
        ]
        if parts:
            history.append(types.Content(role=message.get("role"), parts=parts))
    return history


def _parts_from_chunk(chunk: Any) -> list[Any]:
    candidates = getattr(chunk, "candidates", None) or []
    if not candidates:
        return []
    content = getattr(candidates[0], "content", None)
    return list(getattr(content, "parts", None) or [])


def _thought_block(content: str, opened_at: int, closed_at: int) -> str:
    safe_content = html.escape(content[:MAX_THOUGHT_SUMMARY_CHARS], quote=False)
    return (
        f'<think data-open="{opened_at}" data-close="{closed_at}">'
        f"{safe_content}</think>"
    )


def _thinking_update(
    thought_id: str,
    *,
    status: str,
    open_time: int,
    content_delta: str = "",
    close_time: int | None = None,
) -> dict[str, Any]:
    update: dict[str, Any] = {
        "id": thought_id,
        "status": status,
        "openTime": open_time,
    }
    if content_delta:
        update["contentDelta"] = content_delta
    if close_time is not None:
        update["closeTime"] = close_time
    return {"thinking_update": update}


def _bounded_activity_text(value: Any, max_chars: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:max_chars]


def _search_activity_token(
    status: str,
    query: Any,
    sources: list[dict[str, Any]] | None = None,
) -> str:
    safe_sources = []
    for source in (sources or [])[:MAX_SEARCH_ACTIVITY_SOURCES]:
        if not isinstance(source, dict):
            continue
        safe_sources.append(
            {
                "rank": source.get("rank"),
                "title": _bounded_activity_text(source.get("title"), 240),
                "url": _bounded_activity_text(source.get("url"), 1_000),
                "display_url": _bounded_activity_text(source.get("display_url"), 240),
                "site_name": _bounded_activity_text(source.get("site_name"), 160),
                "snippet": _bounded_activity_text(source.get("snippet"), 600),
                "favicon_url": _bounded_activity_text(source.get("favicon_url"), 1_000),
            }
        )
    payload = {
        "type": "web_search",
        "status": status,
        "query": _bounded_activity_text(query, 500),
        "sources": safe_sources,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return f'<search_activity data-b64="{encoded}"></search_activity>'


def _thinking_level(user_message_data: dict[str, Any]) -> types.ThinkingLevel:
    requested = str(
        user_message_data.get("thinkingLevel")
        or user_message_data.get("thinking_level")
        or DEFAULT_THINKING_LEVEL
    ).strip().lower()
    return THINKING_LEVELS.get(requested, THINKING_LEVELS[DEFAULT_THINKING_LEVEL])


def gemini_stream(
    user_id: str, user_message_data: dict[str, Any]
) -> Generator[Any, None, None]:
    if not GEMINI_API_KEY or GEMINI_API_KEY == "ВАШ_API_КЛЮЧ":
        logger.error("Gemini 3.1 Flash-Lite is unavailable because GEMINI_API_KEY is not configured")
        yield INTERNAL_SEND_ERROR_RESPONSE
        return

    db_user_id = _db_user_id(user_id)
    client: genai.Client | None = None
    try:
        system_prompt = build_system_prompt(db_user_id, user_message_data)
        declarations = model_tool_declarations(
            db_user_id,
            enable_web=_web_tool_enabled(user_message_data),
        )
        client = genai.Client(api_key=GEMINI_API_KEY)
        chat = client.chats.create(
            model=GEMINI_31_FLASH_LITE_MODEL_ID,
            history=_history_for_client(user_message_data),
        )
        next_message: Any = _prepare_new_message(user_message_data)
        if not next_message:
            yield EMPTY_RESPONSE
            return

        completed_tool_calls: set[str] = set()
        total_tool_calls = 0
        any_answer_generated = False
        force_web_search = _manual_web_search_requested(user_message_data.get("webSearch"))
        thought_chunks: list[str] = []
        thought_chars = 0
        thought_opened_at: int | None = None
        thought_sequence = 0
        thought_id = ""
        thought_needs_separator = False

        def finalize_thought() -> list[dict[str, Any]]:
            nonlocal thought_chunks, thought_chars, thought_opened_at, thought_id
            nonlocal thought_needs_separator
            if not thought_chunks or thought_opened_at is None:
                return []
            closed_at = int(time.time() * 1000)
            content = "".join(thought_chunks)
            events = [
                _thinking_update(
                    thought_id,
                    status="complete",
                    open_time=thought_opened_at,
                    close_time=closed_at,
                ),
                {"internal_reply_part": _thought_block(content, thought_opened_at, closed_at)},
            ]
            thought_chunks = []
            thought_chars = 0
            thought_opened_at = None
            thought_id = ""
            thought_needs_separator = False
            return events

        def append_thought_content(content: str, *, separate: bool = False) -> dict[str, Any] | None:
            nonlocal thought_chars, thought_opened_at, thought_sequence, thought_id
            nonlocal thought_needs_separator
            if not content:
                return None
            if thought_opened_at is None:
                thought_opened_at = int(time.time() * 1000)
                thought_sequence += 1
                thought_id = f"{user_message_data.get('request_id') or 'thought'}-{thought_sequence}"
            remaining_chars = MAX_THOUGHT_SUMMARY_CHARS - thought_chars
            if remaining_chars <= 0:
                return None
            separator = "\n\n" if (separate or thought_needs_separator) and thought_chunks else ""
            thought_chunk = f"{separator}{content}"[:remaining_chars]
            if not thought_chunk:
                return None
            thought_chunks.append(thought_chunk)
            thought_chars += len(thought_chunk)
            thought_needs_separator = False
            return _thinking_update(
                thought_id,
                status="streaming",
                open_time=thought_opened_at,
                content_delta=thought_chunk,
            )

        for tool_round in range(MAX_TOOL_ROUNDS + 1):
            function_calls: list[tuple[str, dict[str, Any]]] = []

            response_stream = chat.send_message_stream(
                next_message,
                config=_generation_config(
                    system_prompt,
                    declarations,
                    force_web_search=force_web_search,
                    thinking_level=_thinking_level(user_message_data),
                ),
            )
            force_web_search = False

            for chunk in response_stream:
                for part in _parts_from_chunk(chunk):
                    text = getattr(part, "text", None)
                    if text and getattr(part, "thought", False):
                        thought_event = append_thought_content(str(text))
                        if thought_event:
                            yield thought_event
                        continue

                    if text:
                        yield str(text)
                        any_answer_generated = True
                        if thought_chunks:
                            thought_needs_separator = True

                    function_call = getattr(part, "function_call", None)
                    name = str(getattr(function_call, "name", "") or "").strip()
                    if name:
                        try:
                            arguments = dict(getattr(function_call, "args", None) or {})
                        except (TypeError, ValueError):
                            arguments = {}
                        function_calls.append((name, arguments))

            if not function_calls:
                yield from finalize_thought()
                break
            if tool_round >= MAX_TOOL_ROUNDS:
                logger.warning("Gemini 3.1 Flash-Lite tool loop limit reached for user %s", user_id)
                yield from finalize_thought()
                break

            unique_calls: list[tuple[str, dict[str, Any]]] = []
            round_keys: set[str] = set()
            for name, arguments in function_calls:
                call_key = f"{name}:{serialize_tool_output(arguments)}"
                if call_key in round_keys:
                    continue
                round_keys.add(call_key)
                unique_calls.append((name, arguments))

            remaining_calls = MAX_TOOL_CALLS_TOTAL - total_tool_calls
            unique_calls = unique_calls[: min(MAX_TOOL_CALLS_PER_ROUND, remaining_calls)]
            if not unique_calls:
                logger.warning("Gemini 3.1 Flash-Lite tool call limit reached for user %s", user_id)
                break
            total_tool_calls += len(unique_calls)

            response_parts: list[types.Part] = []
            for name, arguments in unique_calls:
                call_key = f"{name}:{serialize_tool_output(arguments)}"
                if call_key in completed_tool_calls:
                    result_output = {"ok": False, "error": "duplicate_tool_call"}
                else:
                    completed_tool_calls.add(call_key)
                    try:
                        result = execute_model_tool(name, arguments, user_id=db_user_id)
                    except Exception:
                        logger.exception("Gemini 3.1 Flash-Lite tool execution failed: %s", name)
                        result_output = {"ok": False, "error": "tool_execution_failed"}
                        if name == "web_search":
                            search_failed = append_thought_content(
                                _search_activity_token(
                                    "web_search_failed", arguments.get("query")
                                ),
                                separate=True,
                            )
                            if search_failed:
                                yield search_failed
                    else:
                        result_output = result.output
                        yield from result.events
                        if name == "web_search":
                            search_status = (
                                "web_search_done"
                                if result.sources
                                else "web_search_no_results"
                            )
                            if not result.output.get("ok"):
                                search_status = "web_search_failed"
                            search_finished = append_thought_content(
                                _search_activity_token(
                                    search_status,
                                    arguments.get("query"),
                                    result.sources,
                                ),
                                separate=True,
                            )
                            if search_finished:
                                yield search_finished
                        if result.sources:
                            yield {"sources": result.sources}

                response_parts.append(
                    types.Part.from_function_response(
                        name=name,
                        response={"result": serialize_tool_output(result_output)},
                    )
                )
            next_message = response_parts
            if thought_chunks:
                thought_needs_separator = True

        yield from finalize_thought()
        if not any_answer_generated:
            yield EMPTY_RESPONSE
    except errors.APIError as exc:
        logger.error("Gemini 3.1 Flash-Lite API request failed: %s", exc, exc_info=True)
        yield INTERNAL_SEND_ERROR_RESPONSE
    except Exception as exc:
        logger.exception("Gemini 3.1 Flash-Lite request failed: %s", exc)
        yield INTERNAL_SEND_ERROR_RESPONSE
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.warning("Failed to close Gemini 3.1 Flash-Lite client", exc_info=True)
