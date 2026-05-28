from __future__ import annotations

import inspect
import io
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, cast

from flask import Flask, Response, current_app, request, send_file, send_from_directory, session
from werkzeug.utils import secure_filename

from ai_engine import get_model_function
from config import ALLOW_GUEST_CHATS_SAVE
from routes.api_errors import ApiError, api_error_boundary
from routes.features.minds import resolve_bound_mind_context_for_chat, resolve_mind_context_for_chat
from services.chat_history import (
    _generate_guest_session_token,
    append_messages_to_history,
    chat_file_exists,
    has_valid_guest_session_token,
    load_chat_history,
    normalize_message,
    resolve_session_identifier,
)
from services.files import handle_file_upload
from services.model_access import can_user_access_model, get_model_stage
from services.web_search import (
    auto_web_search_requested,
    build_web_search_augmented_message,
    classify_auto_web_search_intent,
    decide_auto_web_search,
    explicit_web_search_requested,
    public_sources,
    rewrite_web_search_query,
    run_web_search,
    web_search_requested,
)
from services.voice import synthesize_text_segments
from utils.auth import UserChatHistory, UserSettings
from utils.input_validation import InputValidator, ValidationError
from utils.rate_limiting import RateLimiter, rate_limit
from utils.responses import logger, make_ok

PUBLIC_UPLOAD_NAME_RE = re.compile(r"^[a-f0-9]{32}(?:\.[a-z0-9]{1,12})$")
chat_limiter = RateLimiter(max_requests=60, time_window=3600)


def _resolve_db_user_id() -> int | None:
    raw_user_id = session.get("user_id")
    if raw_user_id is None:
        return None
    try:
        return int(raw_user_id)
    except (TypeError, ValueError):
        return None


def _resolve_chat_mind_context(
    requested_mind_id: str | None,
    session_id: str,
    user_id: int | None,
) -> dict[str, Any] | None:
    if requested_mind_id:
        return resolve_mind_context_for_chat(requested_mind_id, user_id)

    if user_id is None:
        return None

    chat = UserChatHistory.query.filter_by(user_id=user_id, session_id=session_id).first()
    if not chat:
        return None
    return resolve_bound_mind_context_for_chat(chat.mind_id, user_id)


def _validate_message_in_payload(payload: dict) -> None:
    message = payload.get("message")
    if not message:
        return
    try:
        payload["message"] = InputValidator.validate_chat_message(message)
    except ValidationError as exc:
        raise ApiError(str(exc), status=400, code="invalid_message") from exc


def _extract_uploaded_files() -> list:
    uploaded_files = []
    for key in request.files:
        for file_storage in request.files.getlist(key):
            if file_storage and file_storage.filename:
                uploaded_files.append(file_storage)
    return uploaded_files


def _extract_session_identifier(payload: dict[str, Any]) -> Any:
    return payload.get("session_id") or payload.get("user_id")


def _has_files_payload(value) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    if isinstance(value, str):
        return bool(value.strip())
    return True


def process_request_data() -> tuple[str, dict[str, Any], str]:
    auth_user_id = session.get("user_id")

    def resolve_session_id(raw_identifier: Any) -> str:
        if raw_identifier is None or not str(raw_identifier).strip():
            if auth_user_id is not None:
                raise ApiError(
                    "Session ID is required for authenticated chats.",
                    status=400,
                    code="missing_session_id",
                )
            return f"guest_{uuid.uuid4().hex}"

        safe_identifier = secure_filename(str(raw_identifier))[:200]
        if not safe_identifier:
            raise ApiError("Invalid session ID", status=400, code="invalid_session_id")
        return safe_identifier

    if request.is_json:
        data: dict[str, Any] = request.get_json(silent=True) or {}
        session_id = resolve_session_id(_extract_session_identifier(data))
        model_name = data.get("model", "gemini")
        data["session_id"] = session_id
        data.setdefault("files", [])
        if auth_user_id is None and _has_files_payload(data.get("files")):
            raise ApiError(
                "File uploads are unavailable in guest mode.",
                status=403,
                code="guest_file_upload_disabled",
            )
        _validate_message_in_payload(data)
        return session_id, data, model_name

    if not request.form and not request.files:
        raise ApiError("Empty request", status=400, code="empty_request")

    user_data: dict[str, Any] = request.form.to_dict()
    session_id = resolve_session_id(_extract_session_identifier(user_data))
    model_name = user_data.get("model", "gemini")
    user_data["session_id"] = session_id
    _validate_message_in_payload(user_data)

    uploaded_files = _extract_uploaded_files()
    if auth_user_id is None and uploaded_files:
        raise ApiError(
            "File uploads are unavailable in guest mode.",
            status=403,
            code="guest_file_upload_disabled",
        )
    processed_files = [
        handle_file_upload(file_storage, session_id) for file_storage in uploaded_files
    ]
    user_data["files"] = [file_info for file_info in processed_files if file_info is not None]

    if "meta" in user_data and isinstance(user_data["meta"], str):
        try:
            user_data["meta"] = json.loads(user_data["meta"])
        except json.JSONDecodeError:
            user_data["meta"] = {}

    return session_id, user_data, model_name


def _build_user_message_parts(original_message: str, files: list[dict]) -> list[dict]:
    parts: list[dict] = []
    if original_message:
        parts.append({"text": original_message})

    for file_info in files or []:
        if not isinstance(file_info, dict) or not file_info.get("url_path"):
            continue

        mime_type = file_info.get("mime_type", "")
        part_content = {
            "url_path": file_info.get("url_path"),
            "mime_type": mime_type,
            "original_name": file_info.get("original_name"),
        }
        if mime_type.startswith("image/"):
            parts.append({"image": part_content})
        else:
            parts.append({"file": part_content})

    return parts


def _coerce_image_parts(images: Any) -> list[dict[str, str]]:
    if isinstance(images, str):
        raw_images = [images]
    elif isinstance(images, (list, tuple)):
        raw_images = list(images)
    else:
        return []

    normalized_images: list[dict[str, str]] = []
    for image in raw_images:
        if isinstance(image, str):
            url_path = image.strip()
            mime_type = ""
            original_name = ""
        elif isinstance(image, dict):
            url_path = str(
                image.get("url_path") or image.get("url") or image.get("path") or ""
            ).strip()
            mime_type = str(image.get("mime_type") or "").strip()
            original_name = str(image.get("original_name") or "").strip()
        else:
            continue

        if not url_path:
            continue

        image_part = {"url_path": url_path}
        if mime_type:
            image_part["mime_type"] = mime_type
        if original_name:
            image_part["original_name"] = original_name
        normalized_images.append(image_part)

    return normalized_images


def _build_model_message_parts(reply_text: str, images: Any) -> list[dict]:
    parts: list[dict] = []
    if reply_text:
        parts.append({"text": reply_text})

    for image_part in _coerce_image_parts(images):
        parts.append({"image": image_part})

    return parts


def _extract_web_sources(user_data: dict[str, Any]) -> list[dict[str, Any]]:
    return public_sources(user_data.get("web_search"))


def _stream_event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _build_model_message_for_history(reply_text: str, images: Any, sources: Any) -> dict:
    message = {"role": "model", "parts": _build_model_message_parts(reply_text, images)}
    if isinstance(sources, list) and sources:
        message["sources"] = sources
    return message


def _run_and_attach_web_search(
    user_data: dict[str, Any], original_message: str
) -> list[dict[str, Any]]:
    if not web_search_requested(user_data.get("webSearch")) or not original_message.strip():
        return []

    rewrite = _rewrite_search_query(original_message)
    return _execute_and_attach_web_search(
        user_data,
        original_message,
        search_query=rewrite["query"],
        decision={"search": True, **rewrite},
    )


def _execute_and_attach_web_search(
    user_data: dict[str, Any],
    original_message: str,
    search_query: str | None = None,
    decision: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    query = str(search_query or original_message or "").strip()
    search_payload = run_web_search(query)
    user_data["web_search"] = search_payload
    if decision:
        user_data["web_search_decision"] = decision
    user_data["message"] = build_web_search_augmented_message(original_message, search_payload)
    return public_sources(search_payload)


def _db_auto_web_search_enabled(db_user_id: int | None) -> bool:
    if db_user_id is None:
        return False
    try:
        settings = UserSettings.query.filter_by(user_id=db_user_id).first()
        return bool(settings and settings.automatic_web_search)
    except Exception as exc:
        logger.warning("Failed to load automatic web-search setting: %s", exc, exc_info=True)
        return False


def _auto_web_search_enabled(user_data: dict[str, Any], db_user_id: int | None) -> bool:
    return auto_web_search_requested(user_data.get("autoWebSearch")) or _db_auto_web_search_enabled(
        db_user_id
    )


def _manual_web_search_requested(user_data: dict[str, Any], original_message: str) -> bool:
    return web_search_requested(user_data.get("webSearch")) or explicit_web_search_requested(
        original_message
    )


def _rewrite_search_query(original_message: str) -> dict[str, Any]:
    rewrite = rewrite_web_search_query(original_message)
    query = str(rewrite.get("query") or original_message or "").strip()
    return {
        "query": query or str(original_message or "").strip(),
        "reason": str(rewrite.get("reason") or "").strip(),
        "source": str(rewrite.get("source") or "fallback").strip() or "fallback",
    }


def _resolve_web_search_plan(
    user_data: dict[str, Any],
    original_message: str,
    db_user_id: int | None,
    *,
    auto_enabled: bool | None = None,
    auto_strategy: str | None = None,
) -> dict[str, Any]:
    message = str(original_message or "").strip()
    plan: dict[str, Any] = {"mode": None, "query": message, "decision": None}
    if not message:
        return plan

    if _manual_web_search_requested(user_data, message):
        rewrite = _rewrite_search_query(message)
        return {
            **plan,
            "mode": "manual",
            "query": rewrite["query"],
            "rewrite": rewrite,
        }

    if auto_enabled is None:
        auto_enabled = _auto_web_search_enabled(user_data, db_user_id)
    if not auto_enabled:
        return plan

    if auto_strategy is None:
        auto_strategy = classify_auto_web_search_intent(message)
    if auto_strategy == "skip":
        plan["decision"] = {
            "search": False,
            "query": message,
            "reason": "fast static query",
            "source": "rule",
        }
        return plan
    if auto_strategy == "search":
        rewrite = _rewrite_search_query(message)
        return {
            **plan,
            "mode": "auto",
            "query": rewrite["query"],
            "rewrite": rewrite,
            "decision": {
                "search": True,
                "query": rewrite["query"],
                "reason": "fast search intent",
                "source": "rule",
            },
        }

    decision = decide_auto_web_search(message)
    plan["decision"] = decision
    if decision.get("search"):
        plan["mode"] = "auto"
        if decision.get("source") == "model":
            plan["query"] = str(decision.get("query") or message).strip() or message
        else:
            rewrite = _rewrite_search_query(message)
            plan["query"] = rewrite["query"]
            plan["rewrite"] = rewrite
    return plan


def _attach_web_search_context(
    user_data: dict[str, Any], original_message: str, db_user_id: int | None
) -> None:
    try:
        plan = _resolve_web_search_plan(user_data, original_message, db_user_id)
        if plan.get("mode"):
            _execute_and_attach_web_search(
                user_data,
                original_message,
                search_query=plan.get("query"),
                decision=plan.get("decision"),
            )
    except Exception as exc:
        logger.warning("Web search failed: %s", exc, exc_info=True)


def _resolve_history(
    user_data: dict[str, Any], resolved_session_id: str, db_user_id: int | None
) -> list:
    history_field = user_data.get("history")
    if isinstance(history_field, list):
        return history_field
    if isinstance(history_field, str) and history_field.strip():
        try:
            return json.loads(history_field)
        except json.JSONDecodeError:
            return []
    guest_file_access_allowed = db_user_id is None and has_valid_guest_session_token(
        resolved_session_id
    )
    return load_chat_history(
        resolved_session_id,
        db_user_id,
        allow_file_fallback=guest_file_access_allowed,
        require_guest_token=guest_file_access_allowed,
    )


def _allow_guest_file_persistence(resolved_session_id: str, db_user_id: int | None) -> bool:
    if db_user_id is not None or not ALLOW_GUEST_CHATS_SAVE:
        return False
    if has_valid_guest_session_token(resolved_session_id):
        return True
    return not chat_file_exists(resolved_session_id)


def _stream_chat_response(
    model_name: str,
    model_func,
    db_user_id: int | None,
    user_data: dict,
    resolved_session_id: str,
    original_user_message: str,
    user_message_for_history: dict,
    allow_guest_file_persistence: bool,
    mind_context: dict[str, Any] | None,
):
    captured_app = cast(Flask, cast(Any, current_app)._get_current_object())

    def stream_generator():
        with captured_app.app_context():
            full_response = ""
            final_data: dict[str, Any] = {}
            try:
                message_for_search = str(original_user_message or "")
                manual_search = _manual_web_search_requested(user_data, message_for_search)
                auto_search_enabled = (
                    bool(message_for_search.strip())
                    and not manual_search
                    and _auto_web_search_enabled(user_data, db_user_id)
                )
                auto_search_strategy = (
                    classify_auto_web_search_intent(message_for_search)
                    if auto_search_enabled
                    else None
                )
                if manual_search and message_for_search.strip():
                    yield _stream_event(
                        {
                            "status": "web_search_querying",
                            "message": "Preparing search query...",
                            "mode": "manual",
                        }
                    )
                elif auto_search_enabled and auto_search_strategy == "search":
                    yield _stream_event(
                        {
                            "status": "web_search_querying",
                            "message": "Preparing search query...",
                            "mode": "auto",
                        }
                    )
                elif auto_search_enabled and auto_search_strategy == "model":
                    yield _stream_event(
                        {
                            "status": "web_search_deciding",
                            "message": "Deciding whether web search is needed...",
                            "mode": "auto",
                        }
                    )

                web_search_plan = _resolve_web_search_plan(
                    user_data,
                    message_for_search,
                    db_user_id,
                    auto_enabled=auto_search_enabled,
                    auto_strategy=auto_search_strategy,
                )
                web_search_mode = web_search_plan.get("mode")
                search_query = str(web_search_plan.get("query") or message_for_search)
                if web_search_mode:
                    yield _stream_event(
                        {
                            "status": "web_search_started",
                            "message": "Ищу источники в интернете...",
                            "query": search_query,
                            "mode": web_search_mode,
                            "decision": web_search_plan.get("decision"),
                            "rewrite": web_search_plan.get("rewrite"),
                        }
                    )
                    yield _stream_event(
                        {
                            "status": "web_search_fetching",
                            "query": search_query,
                            "message": "Открываю и читаю найденные страницы...",
                        }
                    )
                    try:
                        web_sources = _execute_and_attach_web_search(
                            user_data,
                            message_for_search,
                            search_query=search_query,
                            decision=web_search_plan.get("decision"),
                        )
                    except Exception as exc:
                        logger.warning("Web search failed: %s", exc, exc_info=True)
                        web_sources = []
                        yield _stream_event(
                            {
                                "status": "web_search_failed",
                                "query": search_query,
                                "message": "Поиск не удался, отвечаю без источников.",
                            }
                        )
                    else:
                        if web_sources:
                            final_data["sources"] = web_sources
                            yield _stream_event(
                                {
                                    "status": "web_search_done",
                                    "query": search_query,
                                    "message": "Источники найдены.",
                                    "sources": web_sources,
                                }
                            )
                        else:
                            yield _stream_event(
                                {
                                    "status": "web_search_no_results",
                                    "query": search_query,
                                    "message": "Подходящие источники не найдены.",
                                }
                            )
                else:
                    if auto_search_enabled and auto_search_strategy == "model":
                        yield _stream_event(
                            {
                                "status": "web_search_skipped",
                                "message": "Web search is not needed for this answer.",
                                "mode": "auto",
                                "decision": web_search_plan.get("decision"),
                            }
                        )
                    web_sources = _extract_web_sources(user_data)
                    if web_sources:
                        final_data["sources"] = web_sources
                        yield _stream_event({"sources": web_sources})

                yield _stream_event(
                    {"status": "generating_text", "message": "Готовлю ответ..."}
                )

                for chunk in model_func(db_user_id, user_data):
                    if isinstance(chunk, dict):
                        if "widget_update" in chunk:
                            yield _stream_event({"widget_update": chunk["widget_update"]})
                            final_data.update(
                                {k: v for k, v in chunk.items() if k != "widget_update"}
                            )
                            continue

                        if "reply_part" in chunk:
                            chunk_str = str(chunk.get("reply_part") or "")
                            full_response += chunk_str
                            yield _stream_event({"reply_part": chunk_str})
                            final_data.update({k: v for k, v in chunk.items() if k != "reply_part"})
                            continue

                        if any(
                            key in chunk for key in ("status", "images", "thinkingTime", "sources")
                        ):
                            yield _stream_event(chunk)
                            final_data.update(chunk)
                            continue

                        final_data.update(chunk)
                        continue

                    chunk_str = str(chunk)
                    full_response += chunk_str
                    yield _stream_event({"reply_part": chunk_str})

                final_data["reply"] = full_response
                final_data["sessionId"] = resolved_session_id
                if allow_guest_file_persistence:
                    final_data["session_token"] = _generate_guest_session_token(
                        resolved_session_id, int(time.time())
                    )
                yield _stream_event(final_data)

            except RuntimeError as exc:
                logger.error("Stream runtime error for '%s': %s", model_name, exc, exc_info=True)
                yield _stream_event({"error": "stream_failed"})

            finally:
                reply_text = str(final_data.get("reply") or full_response or "")
                new_messages_batch = [
                    user_message_for_history,
                    _build_model_message_for_history(
                        reply_text, final_data.get("images"), final_data.get("sources")
                    ),
                ]
                try:
                    append_messages_to_history(
                        resolved_session_id,
                        new_messages_batch,
                        model_name,
                        db_user_id,
                        allow_guest_file_persistence=allow_guest_file_persistence,
                        mind_id=mind_context.get("id") if mind_context else None,
                    )
                except OSError as exc:
                    logger.warning("Failed to persist stream messages: %s", exc)
                    append_messages_to_history(
                        resolved_session_id,
                        [user_message_for_history],
                        model_name,
                        db_user_id,
                        allow_guest_file_persistence=allow_guest_file_persistence,
                        mind_id=mind_context.get("id") if mind_context else None,
                    )

    response = Response(stream_generator(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


def _maybe_return_direct_image(model_output):
    image_bytes = getattr(model_output, "image_bytes", None)
    mime_type = getattr(model_output, "mime_type", None)
    if not isinstance(image_bytes, (bytes, bytearray)) or not isinstance(mime_type, str):
        return None

    return send_file(io.BytesIO(image_bytes), mimetype=mime_type)


def register_chat_routes(api_bp):
    @api_bp.route("/chat", methods=["POST"])
    @rate_limit(chat_limiter, "Too many chat requests. Please wait.")
    @api_error_boundary("chat_unexpected_error")
    def chat():
        session_identifier, user_data, model_name = process_request_data()
        db_user_id = _resolve_db_user_id()

        resolved_session_id, share_entry = resolve_session_identifier(session_identifier)
        if (
            share_entry
            and share_entry.is_public
            and not (db_user_id and share_entry.user_id == db_user_id)
        ):
            raise ApiError("Чат доступен только для чтения.", status=403, code="chat_read_only")
        if not can_user_access_model(model_name, db_user_id):
            stage = get_model_stage(model_name).value
            raise ApiError(
                f"Model '{model_name}' is not available for this account.",
                status=403,
                code="model_access_denied",
                extra={"model": model_name, "stage": stage},
            )

        history = _resolve_history(user_data, resolved_session_id, db_user_id)
        mind_context = _resolve_chat_mind_context(
            user_data.get("mind_id"),
            resolved_session_id,
            db_user_id,
        )
        if mind_context:
            user_data["active_mind"] = mind_context
            user_data["mind_id"] = mind_context["public_id"]
        allow_guest_file_persistence = _allow_guest_file_persistence(
            resolved_session_id, db_user_id
        )
        original_user_message = user_data.get("message", "")
        user_data["history"] = history

        user_message_parts = _build_user_message_parts(
            original_user_message, user_data.get("files", [])
        )
        user_message_for_history = normalize_message({"role": "user", "parts": user_message_parts})

        model_func = get_model_function(model_name)
        if not model_func:
            raise ApiError(
                f"Model '{model_name}' not supported.", status=400, code="model_not_supported"
            )
        if not (user_data.get("message") or user_data.get("files")):
            raise ApiError("'message' or 'files' required", status=400, code="missing_input")

        if inspect.isgeneratorfunction(model_func):
            return _stream_chat_response(
                model_name=model_name,
                model_func=model_func,
                db_user_id=db_user_id,
                user_data=user_data,
                resolved_session_id=resolved_session_id,
                original_user_message=str(original_user_message or ""),
                user_message_for_history=user_message_for_history,
                allow_guest_file_persistence=allow_guest_file_persistence,
                mind_context=mind_context,
            )

        _attach_web_search_context(user_data, str(original_user_message or ""), db_user_id)
        model_output = model_func(db_user_id, user_data)
        web_sources = _extract_web_sources(user_data)
        if isinstance(model_output, dict):
            if web_sources and "sources" not in model_output:
                model_output["sources"] = web_sources
            model_message_for_history = _build_model_message_for_history(
                str(model_output.get("reply") or ""),
                model_output.get("images"),
                model_output.get("sources"),
            )
        else:
            model_message_for_history = _build_model_message_for_history(
                str(model_output), None, web_sources
            )

        new_messages_batch = [user_message_for_history, model_message_for_history]
        append_messages_to_history(
            resolved_session_id,
            new_messages_batch,
            model_name,
            db_user_id,
            allow_guest_file_persistence=allow_guest_file_persistence,
            mind_id=mind_context.get("id") if mind_context else None,
        )

        direct_image_response = _maybe_return_direct_image(model_output)
        if direct_image_response is not None:
            return direct_image_response

        if isinstance(model_output, dict):
            response_data = {"ok": True, **model_output}
        else:
            response_data = {"ok": True, "reply": str(model_output)}
            if web_sources:
                response_data["sources"] = web_sources

        if allow_guest_file_persistence:
            response_data["session_token"] = _generate_guest_session_token(
                resolved_session_id, int(time.time())
            )
        response_data["sessionId"] = resolved_session_id

        return make_ok(response_data)

    @api_bp.route("/translate", methods=["POST"])
    @api_error_boundary("translation_failed")
    def translate():
        payload = request.get_json(silent=True) or {}
        text = payload.get("text")
        target_lang = payload.get("target_lang", "en")

        if not isinstance(text, str) or not text.strip():
            raise ApiError("text required", status=400, code="text_required")
        if not isinstance(target_lang, str) or not target_lang.strip():
            raise ApiError("target_lang required", status=400, code="target_lang_required")

        text = InputValidator.validate_chat_message(text, max_length=10000)
        if not re.match(r"^[a-zA-Z]{2,3}(-[a-zA-Z]{2,4})?$", target_lang.strip()):
            raise ApiError("Invalid target_lang", status=400, code="invalid_target_lang")

        from config import GEMINI_API_KEY, GEMINI_MODEL_NAME

        if not GEMINI_API_KEY:
            raise ApiError(
                "Translation is temporarily unavailable", status=503, code="translation_unavailable"
            )

        import google.generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)
        model_name = GEMINI_MODEL_NAME or "gemini-1.5-flash"
        model = genai.GenerativeModel(model_name)

        prompt = (
            "Translate the following text to the target language.\n"
            f"Target language: {target_lang.strip()}\n"
            "Rules: Return ONLY the translated text. Do not add quotes, explanations, markdown, or extra lines.\n\n"
            f"{text}"
        )

        response = model.generate_content(prompt, generation_config={"temperature": 0})
        translated_text = (getattr(response, "text", None) or "").strip()
        if not translated_text:
            raise ApiError("Translation failed", status=500, code="translation_failed")
        return make_ok({"translated_text": translated_text})

    @api_bp.route("/get-link-metadata", methods=["POST"])
    def get_link_metadata():
        return make_ok({})

    @api_bp.route("/synthesize", methods=["POST"])
    @api_error_boundary("synthesize_failed")
    def synthesize():
        payload = request.get_json(silent=True) or {}
        text = payload.get("text")
        if not text:
            raise ApiError("text required", status=400, code="text_required")
        return make_ok({"segments": synthesize_text_segments(text)})

    @api_bp.route("/uploads/<path:filename>")
    @api_error_boundary("upload_not_found")
    def uploaded_file_route(filename):
        safe_name = secure_filename(filename)
        if not PUBLIC_UPLOAD_NAME_RE.match(safe_name):
            raise ApiError("Not found", status=404, code="not_found")
        return send_from_directory(str(current_app.config["UPLOAD_FOLDER"]), safe_name)

    @api_bp.route("/images/<path:filename>")
    @api_error_boundary("image_not_found")
    def generated_image_route(filename):
        generated_name = secure_filename(Path(filename).name)
        generated_dir = Path(current_app.config["CREATE_IMAGE_FOLDER"])
        if (
            generated_name
            and generated_name == filename
            and (generated_dir / generated_name).is_file()
        ):
            return send_from_directory(str(generated_dir), generated_name)

        static_folder = current_app.static_folder
        if static_folder:
            static_images_dir = Path(static_folder) / "images"
            if static_images_dir.is_dir():
                return send_from_directory(str(static_images_dir), filename)

        raise ApiError("Not found", status=404, code="not_found")
