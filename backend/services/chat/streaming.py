from __future__ import annotations

import html
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, cast

from flask import (
    Flask,
    current_app,
)

from backend.ai_engine.errors import ProviderRequestError
from backend.responses import logger
from backend.services.chat.attachments import (
    build_model_message_for_history,
    cleanup_temporary_uploads,
)
from backend.services.chat.history import (
    generate_guest_session_token,
    persist_chat_operation,
)
from backend.services.chat.search import merge_web_sources
from backend.services.tools.canvas_tools import (
    find_canmore_marker,
    normalize_canvas_textdoc,
    process_canmore_calls,
)


@dataclass(frozen=True)
class ChatStream:
    events: Iterator[str]
    headers: dict[str, str]


CANMORE_STREAM_HOLDBACK_CHARS = 32


def _stream_event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def stream_chat_response(
    model_name: str,
    model_func,
    db_user_id: int | None,
    user_data: dict,
    resolved_session_id: str,
    user_message_for_history: dict | None,
    allow_guest_file_persistence: bool,
    temporary_chat: bool,
    mind_context: dict[str, Any] | None,
    newly_uploaded_files: list[dict[str, Any]],
) -> ChatStream:
    captured_app = cast(Flask, cast(Any, current_app)._get_current_object())

    def stream_generator() -> Iterator[str]:
        with captured_app.app_context():
            full_response = ""
            internal_reply_parts: list[str] = []
            pending_reply_buffer = ""
            suppress_canmore_output = False
            final_data: dict[str, Any] = {}
            aggregated_sources: list[dict[str, Any]] = []
            current_canvas_textdoc = normalize_canvas_textdoc(user_data.get("canvas_textdoc"))
            stream_completed = False
            persisted = False
            model_stream = None
            live_thought: dict[str, Any] = {}

            def stream_reply_text(chunk_text: str):
                nonlocal pending_reply_buffer, suppress_canmore_output
                if not chunk_text:
                    return

                pending_reply_buffer += chunk_text
                if suppress_canmore_output:
                    return

                marker_index = find_canmore_marker(pending_reply_buffer)
                if marker_index >= 0:
                    visible_text = pending_reply_buffer[:marker_index]
                    pending_reply_buffer = pending_reply_buffer[marker_index:]
                    suppress_canmore_output = True
                    if visible_text:
                        yield _stream_event({"reply_part": visible_text})
                    return

                flush_length = max(0, len(pending_reply_buffer) - CANMORE_STREAM_HOLDBACK_CHARS)
                if flush_length <= 0:
                    return

                visible_text = pending_reply_buffer[:flush_length]
                pending_reply_buffer = pending_reply_buffer[flush_length:]
                yield _stream_event({"reply_part": visible_text})

            def persist_delivery(delivery_status: str) -> list[dict]:
                nonlocal persisted
                if temporary_chat or persisted:
                    return []
                reply_text = (
                    str(final_data["reply"])
                    if "reply" in final_data
                    else "".join(internal_reply_parts)
                    + (
                        f'<think data-open="{live_thought.get("openTime", 0)}" data-close="{int(time.time() * 1000)}">'
                        + html.escape(str(live_thought.get("content") or ""), quote=False)
                        + "</think>"
                        if live_thought.get("content")
                        else ""
                    )
                    + full_response
                )
                model_message = build_model_message_for_history(
                    reply_text,
                    final_data.get("images"),
                    final_data.get("sources"),
                    python_artifacts=final_data.get("python_artifacts"),
                    github_tool=final_data.get("github_tool"),
                    canvas_textdoc=final_data.get("canvas_textdoc"),
                    canvas_updates=final_data.get("canvas_updates"),
                    request_id=user_data.get("request_id"),
                    delivery_status=delivery_status,
                    message_id=user_data.get("assistant_message_id"),
                    context_usage=final_data.get("context_usage"),
                )
                history = persist_chat_operation(
                    resolved_session_id,
                    operation=str(user_data.get("operation") or "send"),
                    target_message_id=user_data.get("target_message_id"),
                    parent_message_id=user_data.get("parent_message_id"),
                    user_message=user_message_for_history,
                    model_message={
                        **model_message,
                        "selected_tools": user_data.get("selected_tools", []),
                    },
                    model_name=model_name,
                    user_id=db_user_id,
                    allow_guest_file_persistence=allow_guest_file_persistence,
                    mind_id=mind_context.get("id") if mind_context else None,
                )
                persisted = True
                return history

            try:
                yield _stream_event({"status": "generating_text"})

                model_stream = model_func(db_user_id, user_data)
                for chunk in model_stream:
                    if isinstance(chunk, dict):
                        if "thinking_update" in chunk:
                            update = chunk["thinking_update"]
                            if update.get("id") != live_thought.get("id"):
                                live_thought = {"id": update.get("id"), "content": ""}
                            live_thought["openTime"] = update.get("openTime", 0)
                            live_thought["content"] = (
                                live_thought["content"] + str(update.get("contentDelta") or "")
                            )[:160_000]
                            yield _stream_event({"thinking_update": chunk["thinking_update"]})
                            continue

                        if "internal_reply_part" in chunk:
                            internal_reply_parts.append(str(chunk.get("internal_reply_part") or ""))
                            live_thought = {}
                            continue

                        if "python_artifacts" in chunk:
                            existing_artifacts = final_data.get("python_artifacts")
                            new_artifacts = chunk.get("python_artifacts")
                            final_data["python_artifacts"] = [
                                *(
                                    existing_artifacts
                                    if isinstance(existing_artifacts, list)
                                    else []
                                ),
                                *(new_artifacts if isinstance(new_artifacts, list) else []),
                            ][:20]
                            continue

                        if "canvas_update" in chunk:
                            update = chunk["canvas_update"]
                            current_canvas_textdoc = normalize_canvas_textdoc(
                                chunk.get("canvas_textdoc") or update.get("textdoc")
                            )
                            final_data["canvas_textdoc"] = current_canvas_textdoc
                            final_data["canvas_updates"] = [
                                *final_data.get("canvas_updates", []),
                                update,
                            ]
                            yield _stream_event({"canvas_update": update})
                            continue

                        if "widget_update" in chunk:
                            yield _stream_event({"widget_update": chunk["widget_update"]})
                            final_data.update(
                                {k: v for k, v in chunk.items() if k != "widget_update"}
                            )
                            continue

                        if "reply_part" in chunk:
                            chunk_str = str(chunk.get("reply_part") or "")
                            full_response += chunk_str
                            yield from stream_reply_text(chunk_str)
                            final_data.update({k: v for k, v in chunk.items() if k != "reply_part"})
                            continue

                        if any(
                            key in chunk for key in ("status", "images", "thinkingTime", "sources")
                        ):
                            stream_chunk = chunk
                            if "sources" in chunk:
                                aggregated_sources = merge_web_sources(
                                    aggregated_sources,
                                    chunk.get("sources"),
                                )
                                stream_chunk = {**chunk, "sources": aggregated_sources}
                            yield _stream_event(stream_chunk)
                            final_data.update(stream_chunk)
                            continue

                        final_data.update(chunk)
                        continue

                    chunk_str = str(chunk)
                    full_response += chunk_str
                    yield from stream_reply_text(chunk_str)

                if not suppress_canmore_output and pending_reply_buffer:
                    yield _stream_event({"reply_part": pending_reply_buffer})

                canvas_result = process_canmore_calls(full_response, current_canvas_textdoc)
                if canvas_result.updates:
                    final_data["canvas_updates"] = [
                        *final_data.get("canvas_updates", []),
                        *canvas_result.updates,
                    ]
                    final_data["canvas_textdoc"] = canvas_result.textdoc
                    for canvas_update in canvas_result.updates:
                        yield _stream_event({"canvas_update": canvas_update})

                final_data["reply"] = "".join(internal_reply_parts) + canvas_result.reply
                final_data["request_id"] = user_data.get("request_id")
                final_data["delivery_status"] = "complete"
                final_data["sessionId"] = resolved_session_id
                final_data["uploaded_files"] = [] if temporary_chat else user_data.get("files", [])
                stream_completed = True
                final_data["history"] = persist_delivery("complete")
                if allow_guest_file_persistence and not temporary_chat:
                    final_data["session_token"] = generate_guest_session_token(
                        resolved_session_id, int(time.time())
                    )
                yield _stream_event(final_data)

            except ProviderRequestError as exc:
                logger.warning("Model request failed: model=%s code=%s", model_name, exc.code)
                yield _stream_event({"error": {"code": exc.code, "status": exc.status}})
            except Exception as exc:
                logger.error("Stream error for '%s': %s", model_name, exc, exc_info=True)
                yield _stream_event({"error": "stream_failed"})

            finally:
                if model_stream is not None and hasattr(model_stream, "close"):
                    try:
                        model_stream.close()
                    except Exception:
                        logger.exception("Failed to close model stream")
                if not temporary_chat and not persisted:
                    try:
                        persist_delivery("complete" if stream_completed else "interrupted")
                    except Exception as exc:
                        logger.exception("Failed to persist chat operation: %s", exc)
                if temporary_chat or not persisted:
                    cleanup_temporary_uploads({"files": newly_uploaded_files})

    headers = {"X-Chat-Request-Id": str(user_data.get("request_id") or "")}
    if allow_guest_file_persistence and not temporary_chat:
        headers["X-Chat-Session-Token"] = generate_guest_session_token(
            resolved_session_id, int(time.time())
        )
    return ChatStream(stream_generator(), headers)
