import base64
import io
import logging
from typing import Any, Dict, Generator, List, Optional, Union

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from PIL import Image

from ai_engine.personalization import build_system_prompt
from ai_engine.prompt_templates import load_prompt
from config import GEMINI_API_KEY, GEMINI_MODEL_NAME
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

_gemini_configured = False
_UNSUPPORTED_LOCATION_ERROR_FRAGMENT = "user location is not supported"
HISTORY_ATTACHMENT_MAX_COUNT = 8
HISTORY_ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024


def _ensure_gemini_configured() -> None:
    global _gemini_configured

    if _gemini_configured:
        return

    if not GEMINI_API_KEY or GEMINI_API_KEY == "ВАШ_API_КЛЮЧ":
        raise ValueError(
            "GEMINI_API_KEY не установлен или имеет значение по умолчанию. Проверьте config.py."
        )

    genai.configure(api_key=GEMINI_API_KEY)
    _gemini_configured = True
    logger.info("Модуль Gemini успешно настроен.")


def _load_system_prompt() -> Optional[str]:
    prompt_content = load_prompt("prompt.md")
    if prompt_content:
        return prompt_content

    logger.error("Файл системного промпта prompt.md не найден или пуст.")
    return None


def _prepare_history(
    history_from_main: List[Dict[str, Any]],
    *,
    allow_stored_attachments: bool = False,
) -> List[Dict[str, Any]]:
    restored_files: dict[str, dict] = {}
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
            restored = restore_stored_file_for_model(
                attachment,
                max_bytes=remaining_bytes,
            )
            if not restored:
                continue
            restored_files[url_path] = restored
            remaining_bytes -= int(restored.get("size") or 0)
            if len(restored_files) >= HISTORY_ATTACHMENT_MAX_COUNT:
                break

    prepared_history: List[Dict[str, Any]] = []
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


def _prepare_history_parts(
    parts: Any,
    restored_files: dict[str, dict] | None = None,
) -> List[Dict[str, Any]]:
    prepared_parts: List[Dict[str, Any]] = []
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


def _prepare_new_message(user_message_data: Dict[str, Any]) -> List[Union[str, Image.Image]]:
    content_parts: List[Union[str, Image.Image]] = []

    text = user_message_data.get("message", "")
    if text:
        content_parts.append(text)

    for file_info in user_message_data.get("files", []):
        try:
            model_part = file_info.get("model_part")
            if not model_part:
                logger.warning(
                    "Файл '%s' не содержит 'model_part'. Пропускаем.",
                    file_info.get("original_name"),
                )
                continue

            if "inline_data" in model_part:
                mime_type = model_part["inline_data"].get("mime_type")
                base64_data = model_part["inline_data"].get("data")
                if mime_type and mime_type.startswith("image/") and base64_data:
                    image_bytes = base64.b64decode(base64_data)
                    image = Image.open(io.BytesIO(image_bytes))
                    content_parts.append(image)
                    logger.info(
                        "Изображение '%s' добавлено в запрос.",
                        file_info.get("original_name"),
                    )
                else:
                    logger.warning(
                        "Некорректные данные изображения для файла '%s'.",
                        file_info.get("original_name"),
                    )
            elif "text" in model_part:
                content_parts.append(model_part["text"])
                logger.info(
                    "Текстовое содержимое файла '%s' добавлено в запрос.",
                    file_info.get("original_name"),
                )
        except Exception as exc:
            logger.error(
                "Критическая ошибка при обработке файла '%s': %s",
                file_info.get("original_name"),
                exc,
                exc_info=True,
            )
            content_parts.append(
                "\nОшибка обработки файла"
                f"Не удалось обработать файл '{file_info.get('original_name')}'."
            )

    return content_parts


def _google_api_error_message(exc: google_exceptions.GoogleAPICallError) -> str:
    return str(getattr(exc, "message", None) or exc)


def _is_unsupported_location_error(exc: google_exceptions.GoogleAPICallError) -> bool:
    error_message = _google_api_error_message(exc).lower()
    return (
        isinstance(exc, google_exceptions.FailedPrecondition)
        and _UNSUPPORTED_LOCATION_ERROR_FRAGMENT in error_message
    )


def _format_google_api_error(exc: google_exceptions.GoogleAPICallError) -> str:
    if _is_unsupported_location_error(exc):
        return (
            "Сервис недоступен"
            "Языковая модель сейчас недоступна из текущего региона. "
            "Обратитесь к администратору или попробуйте позже."
        )

    return (
        "Ошибка API"
        f"Произошла ошибка при обращении к API Google: {_google_api_error_message(exc)}"
    )


def _manual_web_search_requested(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _web_tool_enabled(user_message_data: Dict[str, Any]) -> bool:
    return _manual_web_search_requested(
        user_message_data.get("webSearch")
    ) or _manual_web_search_requested(user_message_data.get("autoWebSearch"))


def _tool_config(user_message_data: Dict[str, Any]) -> dict[str, Any] | None:
    if not _manual_web_search_requested(user_message_data.get("webSearch")):
        return None
    return {
        "function_calling_config": {
            "mode": "ANY",
            "allowed_function_names": ["web_search"],
        }
    }


def _function_calls_from_chunk(chunk: Any) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    for part in getattr(chunk, "parts", None) or []:
        function_call = getattr(part, "function_call", None)
        name = str(getattr(function_call, "name", "") or "").strip()
        if not name:
            continue
        raw_args = getattr(function_call, "args", None)
        try:
            arguments = dict(raw_args or {})
        except (TypeError, ValueError):
            arguments = {}
        calls.append((name, arguments))
    return calls


def _text_parts_from_chunk(chunk: Any) -> list[str]:
    return [
        str(text)
        for part in (getattr(chunk, "parts", None) or [])
        if (text := getattr(part, "text", None))
    ]


def gemini_stream(
    user_id: str, user_message_data: Dict[str, Any]
) -> Generator[Any, None, None]:
    try:
        _ensure_gemini_configured()

        try:
            system_prompt = build_system_prompt(user_id, user_message_data)
        except Exception as exc:
            logger.exception("Failed to build system prompt for user %s: %s", user_id, exc)
            system_prompt = _load_system_prompt()

        model_kwargs: dict[str, Any] = {"model_name": GEMINI_MODEL_NAME}
        if system_prompt:
            model_kwargs["system_instruction"] = system_prompt

        db_user_id: int | None
        try:
            db_user_id = int(user_id) if user_id is not None else None
        except (TypeError, ValueError):
            db_user_id = None
        tool_declarations = model_tool_declarations(
            db_user_id,
            enable_web=_web_tool_enabled(user_message_data),
        )
        if tool_declarations:
            model_kwargs["tools"] = [{"function_declarations": tool_declarations}]

        model = genai.GenerativeModel(**model_kwargs)
        history = _prepare_history(
            user_message_data.get("history", []),
            allow_stored_attachments=bool(user_message_data.get("history_is_canonical")),
        )
        chat_session = model.start_chat(history=history)
        logger.info(
            "Gemini: Сессия чата для '%s' создана с %s сообщениями в истории.",
            user_id,
            len(history),
        )

        new_message_parts = _prepare_new_message(user_message_data)
        if not new_message_parts:
            yield "Пожалуйста, введите сообщение или прикрепите файл для начала диалога."
            return

        response_stream = None
        any_text_generated = False

        try:
            next_message: Any = new_message_parts
            declared_tool_names = {
                str(declaration.get("name") or "") for declaration in tool_declarations
            }
            next_tool_config = (
                _tool_config(user_message_data)
                if "web_search" in declared_tool_names
                else None
            )
            completed_tool_calls: set[str] = set()
            total_tool_calls = 0

            for tool_round in range(MAX_TOOL_ROUNDS + 1):
                send_kwargs: dict[str, Any] = {"stream": True}
                if next_tool_config:
                    send_kwargs["tool_config"] = next_tool_config
                response_stream = chat_session.send_message(next_message, **send_kwargs)
                function_calls: list[tuple[str, dict[str, Any]]] = []

                for chunk in response_stream:
                    chunk_calls = _function_calls_from_chunk(chunk)
                    if chunk_calls:
                        function_calls.extend(chunk_calls)
                    for text in _text_parts_from_chunk(chunk):
                        yield text
                        any_text_generated = True

                if not function_calls:
                    break
                if tool_round >= MAX_TOOL_ROUNDS:
                    logger.warning("Gemini tool loop limit reached for user %s", user_id)
                    break

                unique_function_calls: list[tuple[str, dict[str, Any]]] = []
                round_call_keys: set[str] = set()
                for name, arguments in function_calls:
                    call_key = f"{name}:{serialize_tool_output(arguments)}"
                    if call_key in round_call_keys:
                        continue
                    round_call_keys.add(call_key)
                    unique_function_calls.append((name, arguments))
                function_calls = unique_function_calls

                remaining_calls = MAX_TOOL_CALLS_TOTAL - total_tool_calls
                function_calls = function_calls[: min(MAX_TOOL_CALLS_PER_ROUND, remaining_calls)]
                if not function_calls:
                    logger.warning("Gemini tool call limit reached for user %s", user_id)
                    break
                total_tool_calls += len(function_calls)

                response_parts = []
                for name, arguments in function_calls:
                    call_key = f"{name}:{serialize_tool_output(arguments)}"
                    if call_key in completed_tool_calls:
                        result_output = {
                            "ok": False,
                            "error": "duplicate_tool_call",
                        }
                    else:
                        completed_tool_calls.add(call_key)
                        try:
                            result = execute_model_tool(
                                name,
                                arguments,
                                user_id=db_user_id,
                            )
                        except Exception:
                            logger.exception("Model tool execution failed: %s", name)
                            result_output = {"ok": False, "error": "tool_execution_failed"}
                        else:
                            result_output = result.output
                            for event in result.events:
                                yield event
                            if result.sources:
                                yield {"sources": result.sources}

                    response_parts.append(
                        genai.protos.Part(
                            function_response=genai.protos.FunctionResponse(
                                name=name,
                                response={"result": serialize_tool_output(result_output)},
                            )
                        )
                    )

                next_message = genai.protos.Content(role="function", parts=response_parts)
                next_tool_config = None

        except google_exceptions.GoogleAPICallError as exc:
            logger.error("Ошибка вызова API для '%s': %s", user_id, exc, exc_info=True)
            yield _format_google_api_error(exc)
            return
        except Exception as exc:
            logger.error(
                "Неожиданная ошибка при отправке сообщения для '%s': %s",
                user_id,
                exc,
                exc_info=True,
            )
            yield (
                "Внутренняя ошибка"
                "Произошла внутренняя ошибка при отправке вашего сообщения модели."
            )
            return

        if not any_text_generated:
            logger.warning("Поток для '%s' завершился без генерации текста.", user_id)
            try:
                if response_stream and response_stream.prompt_feedback:
                    block_reason = response_stream.prompt_feedback.block_reason
                    logger.error(
                        "Ответ для '%s' был заблокирован. Причина: %s.",
                        user_id,
                        block_reason,
                    )
                    yield (
                        "Запрос заблокирован"
                        "Модель не сгенерировала ответ. Ваш запрос или контекст диалога мог быть "
                        "заблокирован по соображениям безопасности. Попробуйте переформулировать его."
                    )
                else:
                    logger.error("Ответ для '%s' пуст, причина блокировки не найдена.", user_id)
                    yield (
                        "Пустой ответ"
                        "Модель не сгенерировала ответ. Это могло произойти из-за внутренних правил "
                        "безопасности или временной ошибки. Пожалуйста, попробуйте еще раз."
                    )
            except Exception as feedback_error:
                logger.error(
                    "Ошибка при получении prompt_feedback для '%s': %s",
                    user_id,
                    feedback_error,
                    exc_info=True,
                )
                yield (
                    "Пустой ответлан "
                    "Модель вернула пустой ответ, и не удалось определить причину. "
                    "Попробуйте переформулировать запрос."
                )

    except Exception as exc:
        logger.critical(
            "КРИТИЧЕСКАЯ неперехваченная ошибка в gemini_stream для '%s': %s",
            user_id,
            exc,
            exc_info=True,
        )
        error_text = str(exc)
        if "API key not valid" in error_text:
            yield (
                "Недействительный API-ключ"
                "Произошла критическая ошибка: API-ключ недействителен. Обратитесь к администратору."
            )
        else:
            yield (
                "Критическая ошибка"
                "Произошла критическая системная ошибка при обращении к языковой модели. "
                "Пожалуйста, попробуйте позже."
            )
