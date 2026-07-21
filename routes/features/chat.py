from __future__ import annotations

import inspect
import io
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, cast

from flask import (
    Flask,
    Response,
    after_this_request,
    current_app,
    request,
    send_file,
    send_from_directory,
    session,
)
from sqlalchemy import and_
from werkzeug.utils import secure_filename

from ai_engine import get_model_function
from ai_engine.registry import DEFAULT_MODEL_ID
from config import ALLOW_GUEST_CHATS_SAVE, CHAT_MAX_VARIANTS_PER_TURN, UPLOAD_FOLDER
from routes.api_errors import ApiError, api_error_boundary
from routes.features.minds import resolve_bound_mind_context_for_chat, resolve_mind_context_for_chat
from services.beatbox_tools import normalize_beatbox_state
from services.canvas_tools import (
    find_canmore_marker,
    normalize_canvas_textdoc,
    process_canmore_calls,
)
from services.chat_history import (
    _generate_guest_session_token,
    chat_file_exists,
    conversation_context_for_operation,
    has_valid_guest_session_token,
    load_chat_graph,
    load_chat_history,
    normalize_message,
    persist_chat_operation,
    resolve_session_identifier,
)
from services.files import (
    handle_file_upload,
    restore_stored_file_for_model,
    validate_chat_uploads,
)
from services.model_access import can_user_access_model, get_model_stage, model_exists
from services.translation import TranslationUnavailableError, translate_text
from services.voice import TTS_MAX_CHARS, synthesize_text_segments
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
from utils.auth import ChatShare, UserChatHistory, UserSettings
from utils.input_validation import InputValidator, ValidationError
from utils.privacy import SERVICE_IMPROVEMENT_SETTING_KEY
from utils.rate_limiting import RateLimiter, anonymous_rate_limit, rate_limit
from utils.responses import logger, make_ok
from utils.url_security import UnsafeUrlError, validate_public_http_url

PUBLIC_UPLOAD_NAME_RE = re.compile(r"^[a-f0-9]{32}(?:\.[a-z0-9]{1,12})$")
translation_limiter = RateLimiter(max_requests=60, time_window=3600, namespace="translation")
anonymous_translation_limiter = RateLimiter(
    max_requests=10, time_window=3600, namespace="anonymous_translation"
)
synthesize_limiter = RateLimiter(max_requests=30, time_window=3600, namespace="synthesize")
anonymous_synthesize_limiter = RateLimiter(
    max_requests=5, time_window=3600, namespace="anonymous_synthesize"
)
ANONYMOUS_TRANSLATION_MAX_CHARS = 2000
CHAT_OPERATIONS = {"send", "regenerate", "edit"}
CHAT_MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
CANMORE_STREAM_HOLDBACK_CHARS = 32


def _resolve_db_user_id() -> int | None:
    raw_user_id = session.get("user_id")
    if raw_user_id is None:
        return None
    try:
        return int(raw_user_id)
    except (TypeError, ValueError):
        return None


def _find_uploaded_file_reference(value: Any, url_path: str) -> dict[str, Any] | None:
    if isinstance(value, list):
        for item in value:
            if reference := _find_uploaded_file_reference(item, url_path):
                return reference
        return None
    if not isinstance(value, dict):
        return None

    for attachment_key in ("file", "image"):
        attachment = value.get(attachment_key)
        if isinstance(attachment, dict) and attachment.get("url_path") == url_path:
            return attachment
    for item in value.values():
        if reference := _find_uploaded_file_reference(item, url_path):
            return reference
    return None


def _chat_uploaded_file_reference(chat: UserChatHistory, url_path: str) -> dict[str, Any] | None:
    return _find_uploaded_file_reference(chat.get_messages(), url_path)


def _uploaded_file_access(filename: str, user_id: int | None) -> tuple[str, dict[str, Any]] | None:
    url_path = f"/uploads/{filename}"
    if user_id is not None:
        owner_candidates = UserChatHistory.query.filter(
            UserChatHistory.user_id == user_id,
            UserChatHistory.messages_data.contains(url_path),
        ).all()
        for chat in owner_candidates:
            if reference := _chat_uploaded_file_reference(chat, url_path):
                return "owner", reference

    public_candidates = (
        UserChatHistory.query.join(
            ChatShare,
            and_(
                ChatShare.user_id == UserChatHistory.user_id,
                ChatShare.session_id == UserChatHistory.session_id,
            ),
        )
        .filter(
            ChatShare.is_public.is_(True),
            UserChatHistory.messages_data.contains(url_path),
        )
        .all()
    )
    for chat in public_candidates:
        if reference := _chat_uploaded_file_reference(chat, url_path):
            return "public", reference
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


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _validated_message_id(value: Any, *, required: bool = False) -> str | None:
    text = str(value or "").strip()
    if not text:
        if required:
            raise ApiError("Message ID is required", status=400, code="missing_message_id")
        return None
    if not CHAT_MESSAGE_ID_RE.fullmatch(text):
        raise ApiError("Invalid message ID", status=400, code="invalid_message_id")
    return text


def _stored_message_text(message: dict[str, Any] | None) -> str:
    if not isinstance(message, dict):
        return ""
    return "\n".join(
        str(part.get("text") or "")
        for part in message.get("parts", [])
        if isinstance(part, dict) and part.get("text")
    ).strip()


def _stored_attachment_parts(message: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(message, dict):
        return []
    return [
        dict(part)
        for part in message.get("parts", [])
        if isinstance(part, dict) and ("image" in part or "file" in part)
    ]


def _cleanup_temporary_uploads(user_data: dict[str, Any]) -> None:
    upload_root = Path(UPLOAD_FOLDER).resolve()
    for file_info in user_data.get("files", []):
        if not isinstance(file_info, dict) or not file_info.get("path"):
            continue
        try:
            path = Path(str(file_info["path"])).resolve()
            if path.parent == upload_root and path.is_file():
                path.unlink()
        except OSError:
            logger.warning("Could not remove a temporary chat upload", exc_info=True)


def _persist_pending_uploads(user_data: dict[str, Any], session_id: str) -> list[dict[str, Any]]:
    pending_uploads = user_data.pop("_pending_uploads", [])
    processed_files: list[dict[str, Any]] = []
    for file_storage in pending_uploads:
        try:
            file_info = handle_file_upload(file_storage, session_id)
        except Exception as exc:
            _cleanup_temporary_uploads({"files": processed_files})
            raise ApiError(
                "The attachment could not be processed.",
                status=400,
                code="attachment_processing_failed",
            ) from exc
        if file_info is None:
            _cleanup_temporary_uploads({"files": processed_files})
            raise ApiError(
                "The attachment could not be processed.",
                status=400,
                code="attachment_processing_failed",
            )
        processed_files.append(file_info)
    user_data["files"] = processed_files
    return processed_files


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

        safe_identifier = str(raw_identifier).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", safe_identifier):
            raise ApiError("Invalid session ID", status=400, code="invalid_session_id")
        return safe_identifier

    if request.is_json:
        raw_data = request.get_json(silent=True)
        if raw_data is not None and not isinstance(raw_data, dict):
            raise ApiError("Invalid JSON payload", status=400, code="invalid_json")
        data: dict[str, Any] = raw_data or {}
        operation = str(data.get("operation") or "send").strip().lower()
        if operation not in CHAT_OPERATIONS:
            raise ApiError("Invalid chat operation", status=400, code="invalid_chat_operation")
        data["operation"] = operation
        session_id = resolve_session_id(_extract_session_identifier(data))
        model_name = str(data.get("model") or "").strip() or DEFAULT_MODEL_ID
        data["session_id"] = session_id
        data["canvas_textdoc"] = normalize_canvas_textdoc(data.get("canvas_textdoc"))
        data["beatbox_state"] = normalize_beatbox_state(data.get("beatbox_state"))
        if _has_files_payload(data.get("files")):
            if auth_user_id is None:
                raise ApiError(
                    "File uploads are unavailable in guest mode.",
                    status=403,
                    code="guest_file_upload_disabled",
                )
            raise ApiError(
                "Attachment metadata cannot be supplied directly.",
                status=400,
                code="inline_attachment_metadata_not_allowed",
            )
        data["files"] = []
        _validate_message_in_payload(data)
        return session_id, data, model_name

    if not request.form and not request.files:
        raise ApiError("Empty request", status=400, code="empty_request")

    user_data: dict[str, Any] = request.form.to_dict()
    operation = str(user_data.get("operation") or "send").strip().lower()
    if operation not in CHAT_OPERATIONS:
        raise ApiError("Invalid chat operation", status=400, code="invalid_chat_operation")
    user_data["operation"] = operation
    session_id = resolve_session_id(_extract_session_identifier(user_data))
    model_name = str(user_data.get("model") or "").strip() or DEFAULT_MODEL_ID
    user_data["session_id"] = session_id
    _validate_message_in_payload(user_data)

    uploaded_files = _extract_uploaded_files()
    if operation == "regenerate" and uploaded_files:
        raise ApiError(
            "Regeneration reuses the original attachments",
            status=400,
            code="regenerate_attachments_not_allowed",
        )
    if auth_user_id is None and uploaded_files:
        raise ApiError(
            "File uploads are unavailable in guest mode.",
            status=403,
            code="guest_file_upload_disabled",
        )
    uploads_valid, upload_error_code, upload_error = validate_chat_uploads(uploaded_files)
    if not uploads_valid:
        raise ApiError(
            upload_error or "Invalid attachment.",
            status=400,
            code=upload_error_code or "invalid_attachment",
        )

    # Persistence is intentionally deferred until chat/session/model/idempotency
    # validation has completed. Invalid requests must never leave orphan files.
    user_data["_pending_uploads"] = uploaded_files
    user_data["files"] = []

    if "meta" in user_data and isinstance(user_data["meta"], str):
        try:
            user_data["meta"] = json.loads(user_data["meta"])
        except json.JSONDecodeError:
            user_data["meta"] = {}

    user_data["canvas_textdoc"] = normalize_canvas_textdoc(user_data.get("canvas_textdoc"))
    user_data["beatbox_state"] = normalize_beatbox_state(user_data.get("beatbox_state"))

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


def _merge_web_sources(
    existing: Any,
    incoming: Any,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    positions: dict[str, int] = {}

    for source in [
        *(existing if isinstance(existing, list) else []),
        *(incoming if isinstance(incoming, list) else []),
    ]:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or source.get("final_url") or "").strip()
        if url:
            identity = f"url:{url}"
        else:
            identity = "meta:" + "\x1f".join(
                str(source.get(field) or "").strip().casefold()
                for field in ("site_name", "title", "display_url")
            )
        if identity in positions:
            current = merged[positions[identity]]
            for key, value in source.items():
                if not current.get(key) and value:
                    current[key] = value
            continue
        positions[identity] = len(merged)
        merged.append(dict(source))

    return merged


def _stream_event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _build_model_message_for_history(
    reply_text: str,
    images: Any,
    sources: Any,
    github_tool: Any = None,
    canvas_textdoc: Any = None,
    canvas_updates: Any = None,
    request_id: str | None = None,
    delivery_status: str | None = None,
    message_id: str | None = None,
) -> dict:
    message: dict[str, Any] = {
        "id": message_id or f"a_{uuid.uuid4().hex}",
        "role": "model",
        "parts": _build_model_message_parts(reply_text, images),
    }
    if isinstance(sources, list) and sources:
        message["sources"] = sources
    if isinstance(github_tool, dict) and github_tool:
        message["github_tool"] = github_tool
    normalized_canvas = normalize_canvas_textdoc(canvas_textdoc)
    if normalized_canvas:
        message["canvas_textdoc"] = normalized_canvas
    if isinstance(canvas_updates, list) and canvas_updates:
        message["canvas_updates"] = canvas_updates
    if request_id:
        message["request_id"] = request_id
    if delivery_status in {"complete", "interrupted"}:
        message["delivery_status"] = delivery_status
    return message


def _find_previous_delivery(history: list, request_id: str) -> dict[str, Any] | None:
    for message in reversed(history):
        if not isinstance(message, dict) or message.get("role") != "model":
            continue
        if message.get("request_id") != request_id:
            continue
        reply = "\n".join(
            str(part.get("text") or "")
            for part in message.get("parts", [])
            if isinstance(part, dict) and part.get("text")
        )
        return {
            "reply": reply,
            "request_id": request_id,
            "delivery_status": message.get("delivery_status") or "complete",
            "sources": message.get("sources") or [],
            "canvas_textdoc": message.get("canvas_textdoc"),
            "canvas_updates": message.get("canvas_updates") or [],
            "recovered": True,
        }
    return None


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


def _load_privacy_controls(db_user_id: int | None) -> dict[str, bool]:
    if db_user_id is None:
        return {"service_improvement_opt_in": False}
    try:
        settings = UserSettings.query.filter_by(user_id=db_user_id).first()
        settings_data = settings.get_settings() if settings else {}
        return {
            "service_improvement_opt_in": bool(
                settings_data.get(SERVICE_IMPROVEMENT_SETTING_KEY, False)
            )
        }
    except Exception as exc:
        logger.warning("Failed to load privacy controls: %s", exc, exc_info=True)
        return {"service_improvement_opt_in": False}


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
    user_message_for_history: dict | None,
    allow_guest_file_persistence: bool,
    temporary_chat: bool,
    mind_context: dict[str, Any] | None,
    newly_uploaded_files: list[dict[str, Any]],
):
    captured_app = cast(Flask, cast(Any, current_app)._get_current_object())

    def stream_generator():
        with captured_app.app_context():
            full_response = ""
            internal_reply_parts: list[str] = []
            streamed_response = ""
            pending_reply_buffer = ""
            suppress_canmore_output = False
            final_data: dict[str, Any] = {}
            aggregated_sources: list[dict[str, Any]] = []
            current_canvas_textdoc = normalize_canvas_textdoc(user_data.get("canvas_textdoc"))
            stream_completed = False
            persisted = False

            def stream_reply_text(chunk_text: str):
                nonlocal pending_reply_buffer, streamed_response, suppress_canmore_output
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
                        streamed_response += visible_text
                        yield _stream_event({"reply_part": visible_text})
                    return

                flush_length = max(0, len(pending_reply_buffer) - CANMORE_STREAM_HOLDBACK_CHARS)
                if flush_length <= 0:
                    return

                visible_text = pending_reply_buffer[:flush_length]
                pending_reply_buffer = pending_reply_buffer[flush_length:]
                streamed_response += visible_text
                yield _stream_event({"reply_part": visible_text})

            def persist_delivery(delivery_status: str) -> list[dict]:
                nonlocal persisted
                if temporary_chat or persisted:
                    return []
                reply_text = (
                    str(final_data["reply"])
                    if "reply" in final_data
                    else str(full_response or streamed_response or "")
                )
                model_message = _build_model_message_for_history(
                    reply_text,
                    final_data.get("images"),
                    final_data.get("sources"),
                    github_tool=final_data.get("github_tool"),
                    canvas_textdoc=final_data.get("canvas_textdoc"),
                    canvas_updates=final_data.get("canvas_updates"),
                    request_id=user_data.get("request_id"),
                    delivery_status=delivery_status,
                    message_id=user_data.get("assistant_message_id"),
                )
                history = persist_chat_operation(
                    resolved_session_id,
                    operation=str(user_data.get("operation") or "send"),
                    target_message_id=user_data.get("target_message_id"),
                    parent_message_id=user_data.get("parent_message_id"),
                    user_message=user_message_for_history,
                    model_message=model_message,
                    model_name=model_name,
                    user_id=db_user_id,
                    allow_guest_file_persistence=allow_guest_file_persistence,
                    mind_id=mind_context.get("id") if mind_context else None,
                )
                persisted = True
                return history

            try:
                yield _stream_event({"status": "generating_text", "message": "Готовлю ответ..."})

                for chunk in model_func(db_user_id, user_data):
                    if isinstance(chunk, dict):
                        if "thinking_update" in chunk:
                            yield _stream_event({"thinking_update": chunk["thinking_update"]})
                            continue

                        if "internal_reply_part" in chunk:
                            internal_reply_parts.append(str(chunk.get("internal_reply_part") or ""))
                            continue

                        if "canvas_update" in chunk:
                            yield _stream_event({"canvas_update": chunk["canvas_update"]})
                            final_data.update(
                                {k: v for k, v in chunk.items() if k != "canvas_update"}
                            )
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
                                aggregated_sources = _merge_web_sources(
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
                    streamed_response += pending_reply_buffer
                    yield _stream_event({"reply_part": pending_reply_buffer})

                canvas_result = process_canmore_calls(full_response, current_canvas_textdoc)
                if canvas_result.updates:
                    final_data["canvas_updates"] = canvas_result.updates
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
                    final_data["session_token"] = _generate_guest_session_token(
                        resolved_session_id, int(time.time())
                    )
                yield _stream_event(final_data)

            except Exception as exc:
                logger.error("Stream error for '%s': %s", model_name, exc, exc_info=True)
                yield _stream_event({"error": "stream_failed"})

            finally:
                if not temporary_chat and not persisted:
                    try:
                        persist_delivery("complete" if stream_completed else "interrupted")
                    except Exception as exc:
                        logger.exception("Failed to persist chat operation: %s", exc)
                if temporary_chat or not persisted:
                    _cleanup_temporary_uploads({"files": newly_uploaded_files})

    response = Response(stream_generator(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["X-Chat-Request-Id"] = str(user_data.get("request_id") or "")
    if allow_guest_file_persistence and not temporary_chat:
        response.headers["X-Chat-Session-Token"] = _generate_guest_session_token(
            resolved_session_id, int(time.time())
        )
    return response


def _maybe_return_direct_image(model_output):
    image_bytes = getattr(model_output, "image_bytes", None)
    mime_type = getattr(model_output, "mime_type", None)
    if not isinstance(image_bytes, (bytes, bytearray)) or not isinstance(mime_type, str):
        return None

    return send_file(io.BytesIO(image_bytes), mimetype=mime_type)


def register_chat_routes(api_bp):
    @api_bp.route("/chat", methods=["POST"])
    @api_error_boundary("chat_unexpected_error")
    def chat():
        session_identifier, user_data, model_name = process_request_data()
        db_user_id = _resolve_db_user_id()
        raw_request_id = str(user_data.get("request_id") or uuid.uuid4().hex).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", raw_request_id):
            raise ApiError("Invalid request ID", status=400, code="invalid_request_id")
        user_data["request_id"] = raw_request_id

        resolved_session_id, share_entry = resolve_session_identifier(session_identifier)
        if share_entry and not (db_user_id and share_entry.user_id == db_user_id):
            if not share_entry.is_public:
                raise ApiError("Chat not found", status=404, code="not_found")
            raise ApiError("Чат доступен только для чтения.", status=403, code="chat_read_only")
        if not model_exists(model_name):
            raise ApiError(
                f"Model '{model_name}' not supported.", status=400, code="model_not_supported"
            )
        if not can_user_access_model(model_name, db_user_id):
            stage = get_model_stage(model_name).value
            raise ApiError(
                f"Model '{model_name}' is not available for this account.",
                status=403,
                code="model_access_denied",
                extra={"model": model_name, "stage": stage},
            )

        operation = str(user_data.get("operation") or "send").strip().lower()
        if operation not in CHAT_OPERATIONS:
            raise ApiError("Invalid chat operation", status=400, code="invalid_chat_operation")
        target_message_id = _validated_message_id(
            user_data.get("target_message_id"), required=operation != "send"
        )
        user_message_id = _validated_message_id(user_data.get("user_message_id")) or (
            f"u_{uuid.uuid4().hex}"
        )
        assistant_message_id = (
            _validated_message_id(user_data.get("assistant_message_id")) or f"a_{uuid.uuid4().hex}"
        )
        temporary_chat = _coerce_bool(user_data.get("temporary_chat"))
        allow_guest_file_persistence = _allow_guest_file_persistence(
            resolved_session_id, db_user_id
        )

        persisted_graph = load_chat_graph(
            resolved_session_id,
            db_user_id,
            allow_file_fallback=db_user_id is None
            and has_valid_guest_session_token(resolved_session_id),
            require_guest_token=db_user_id is None,
        )
        previous_delivery = _find_previous_delivery(persisted_graph, raw_request_id)
        if previous_delivery:
            previous_delivery["sessionId"] = resolved_session_id
            previous_delivery["history"] = load_chat_history(
                resolved_session_id,
                db_user_id,
                allow_file_fallback=allow_guest_file_persistence,
                require_guest_token=db_user_id is None,
            )
            if allow_guest_file_persistence:
                previous_delivery["session_token"] = _generate_guest_session_token(
                    resolved_session_id, int(time.time())
                )
            return make_ok(previous_delivery)

        if not temporary_chat:
            existing_message_ids = {
                str(message.get("id"))
                for message in persisted_graph
                if isinstance(message, dict) and message.get("id")
            }
            incoming_message_ids = [assistant_message_id]
            if operation in {"send", "edit"}:
                incoming_message_ids.append(user_message_id)
            if len(set(incoming_message_ids)) != len(incoming_message_ids) or any(
                message_id in existing_message_ids for message_id in incoming_message_ids
            ):
                raise ApiError(
                    "Message ID already exists",
                    status=409,
                    code="message_id_conflict",
                )

        parent_message_id: str | None = None
        target_message = next(
            (message for message in persisted_graph if message.get("id") == target_message_id),
            None,
        )
        if operation in {"regenerate", "edit"} and target_message:
            sibling_count = sum(
                1
                for message in persisted_graph
                if message.get("parent_id") == target_message.get("parent_id")
            )
            if sibling_count >= CHAT_MAX_VARIANTS_PER_TURN:
                raise ApiError(
                    "Conversation version limit reached",
                    status=409,
                    code="chat_variant_limit_reached",
                )
        if temporary_chat:
            history = _resolve_history(user_data, resolved_session_id, db_user_id)
        else:
            try:
                history, parent_message_id = conversation_context_for_operation(
                    persisted_graph, operation, target_message_id
                )
            except ValueError as exc:
                raise ApiError(
                    "Chat message not found",
                    status=404,
                    code=str(exc),
                ) from exc
        mind_context = _resolve_chat_mind_context(
            user_data.get("mind_id"),
            resolved_session_id,
            db_user_id,
        )
        if mind_context:
            user_data["active_mind"] = mind_context
            user_data["mind_id"] = mind_context["public_id"]

        model_func = get_model_function(model_name)
        if not model_func:
            raise ApiError(
                f"Model '{model_name}' not supported.", status=400, code="model_not_supported"
            )
        is_streaming_model = inspect.isgeneratorfunction(model_func)
        original_user_message = str(user_data.get("message") or "")
        inherited_attachment_parts: list[dict[str, Any]] = []
        if operation == "regenerate" and not temporary_chat:
            parent_user = next(
                (
                    message
                    for message in persisted_graph
                    if message.get("id") == (target_message or {}).get("parent_id")
                ),
                None,
            )
            if not parent_user:
                raise ApiError(
                    "Regeneration source not found",
                    status=404,
                    code="invalid_regenerate_target",
                )
            original_user_message = _stored_message_text(parent_user)
            inherited_attachment_parts = _stored_attachment_parts(parent_user)
        elif operation == "edit" and not temporary_chat:
            inherited_attachment_parts = _stored_attachment_parts(target_message)

        restored_inherited_files: list[dict[str, Any]] = []
        if operation in {"regenerate", "edit"} and not temporary_chat:
            restored_inherited_files = [
                restored
                for part in inherited_attachment_parts
                if isinstance(part.get("image") or part.get("file"), dict)
                and (
                    restored := restore_stored_file_for_model(part.get("image") or part.get("file"))
                )
            ]

        if not (
            original_user_message or user_data.get("_pending_uploads") or restored_inherited_files
        ):
            raise ApiError("'message' or 'files' required", status=400, code="missing_input")

        uploaded_files_for_history = _persist_pending_uploads(user_data, resolved_session_id)
        if operation in {"regenerate", "edit"} and not temporary_chat:
            user_data["files"] = (
                [*uploaded_files_for_history, *restored_inherited_files]
                if operation == "edit"
                else restored_inherited_files
            )

        if uploaded_files_for_history:

            @after_this_request
            def cleanup_uncommitted_uploads(response):
                streaming_response_will_own_cleanup = (
                    is_streaming_model and response.status_code < 400
                )
                if not streaming_response_will_own_cleanup and (
                    temporary_chat or response.status_code >= 400
                ):
                    _cleanup_temporary_uploads({"files": uploaded_files_for_history})
                return response

        user_data["message"] = original_user_message

        user_data["history"] = history
        user_data["history_is_canonical"] = not temporary_chat
        user_data["privacy"] = _load_privacy_controls(db_user_id)
        user_data["temporary_chat"] = temporary_chat

        user_message_parts = (
            _build_user_message_parts(original_user_message, uploaded_files_for_history)
            + inherited_attachment_parts
        )
        user_message_for_history = (
            normalize_message(
                {
                    "id": user_message_id,
                    "role": "user",
                    "parts": user_message_parts,
                    "request_id": raw_request_id,
                }
            )
            if operation in {"send", "edit"}
            else None
        )
        user_data["operation"] = operation
        user_data["target_message_id"] = target_message_id
        user_data["parent_message_id"] = parent_message_id
        user_data["assistant_message_id"] = assistant_message_id

        if is_streaming_model:
            return _stream_chat_response(
                model_name=model_name,
                model_func=model_func,
                db_user_id=db_user_id,
                user_data=user_data,
                resolved_session_id=resolved_session_id,
                original_user_message=str(original_user_message or ""),
                user_message_for_history=user_message_for_history,
                allow_guest_file_persistence=allow_guest_file_persistence,
                temporary_chat=temporary_chat,
                mind_context=mind_context,
                newly_uploaded_files=uploaded_files_for_history,
            )

        _attach_web_search_context(user_data, str(original_user_message or ""), db_user_id)
        model_output = model_func(db_user_id, user_data)
        web_sources = _extract_web_sources(user_data)
        canvas_textdoc = normalize_canvas_textdoc(user_data.get("canvas_textdoc"))
        non_stream_canvas_updates: list[dict[str, Any]] = []
        non_stream_canvas_textdoc: dict[str, Any] | None = None
        if isinstance(model_output, dict):
            canvas_result = process_canmore_calls(
                str(model_output.get("reply") or ""), canvas_textdoc
            )
            if canvas_result.updates:
                model_output["reply"] = canvas_result.reply
                model_output["canvas_updates"] = canvas_result.updates
                model_output["canvas_textdoc"] = canvas_result.textdoc
                non_stream_canvas_updates = canvas_result.updates
                non_stream_canvas_textdoc = canvas_result.textdoc
            if web_sources and "sources" not in model_output:
                model_output["sources"] = web_sources
            model_message_for_history = _build_model_message_for_history(
                str(model_output.get("reply") or ""),
                model_output.get("images"),
                model_output.get("sources"),
                canvas_textdoc=model_output.get("canvas_textdoc"),
                canvas_updates=model_output.get("canvas_updates"),
                request_id=raw_request_id,
                delivery_status="complete",
                message_id=assistant_message_id,
            )
        else:
            canvas_result = process_canmore_calls(str(model_output), canvas_textdoc)
            if canvas_result.updates:
                non_stream_canvas_updates = canvas_result.updates
                non_stream_canvas_textdoc = canvas_result.textdoc
            model_message_for_history = _build_model_message_for_history(
                canvas_result.reply,
                None,
                web_sources,
                canvas_textdoc=canvas_result.textdoc if canvas_result.updates else None,
                canvas_updates=canvas_result.updates,
                request_id=raw_request_id,
                delivery_status="complete",
                message_id=assistant_message_id,
            )
            model_output = canvas_result.reply

        canonical_history: list[dict] = []
        if not temporary_chat:
            canonical_history = persist_chat_operation(
                resolved_session_id,
                operation=operation,
                target_message_id=target_message_id,
                parent_message_id=parent_message_id,
                user_message=user_message_for_history,
                model_message=model_message_for_history,
                model_name=model_name,
                user_id=db_user_id,
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
            if non_stream_canvas_updates:
                response_data["canvas_updates"] = non_stream_canvas_updates
                response_data["canvas_textdoc"] = non_stream_canvas_textdoc

        if allow_guest_file_persistence and not temporary_chat:
            response_data["session_token"] = _generate_guest_session_token(
                resolved_session_id, int(time.time())
            )
        response_data["sessionId"] = resolved_session_id
        response_data["uploaded_files"] = [] if temporary_chat else user_data.get("files", [])
        response_data["request_id"] = raw_request_id
        response_data["delivery_status"] = "complete"
        response_data["history"] = canonical_history

        return make_ok(response_data)

    @api_bp.route("/translate", methods=["POST"])
    @anonymous_rate_limit(anonymous_translation_limiter)
    @rate_limit(translation_limiter)
    @api_error_boundary("translation_failed")
    def translate():
        payload = request.get_json(silent=True) or {}
        text = payload.get("text")
        target_lang = payload.get("target_lang", "en")

        if not isinstance(text, str) or not text.strip():
            raise ApiError("text required", status=400, code="text_required")
        if not isinstance(target_lang, str) or not target_lang.strip():
            raise ApiError("target_lang required", status=400, code="target_lang_required")

        max_length = 10000 if _resolve_db_user_id() is not None else ANONYMOUS_TRANSLATION_MAX_CHARS
        text = InputValidator.validate_chat_message(text, max_length=max_length)
        if not re.match(r"^[a-zA-Z]{2,3}(-[a-zA-Z]{2,4})?$", target_lang.strip()):
            raise ApiError("Invalid target_lang", status=400, code="invalid_target_lang")

        try:
            translated_text, used_fallback = translate_text(text, target_lang.strip())
        except TranslationUnavailableError as exc:
            raise ApiError(
                "Translation is temporarily unavailable",
                status=503,
                code="translation_unavailable",
            ) from exc
        return make_ok({"translated_text": translated_text, "fallback": used_fallback})

    @api_bp.route("/get-link-metadata", methods=["POST"])
    @api_error_boundary("link_metadata_failed")
    def get_link_metadata():
        payload = request.get_json(silent=True) or {}
        url = payload.get("url")
        if not isinstance(url, str):
            raise ApiError("URL is required", status=400, code="url_required")
        try:
            validated_url = validate_public_http_url(url)
        except UnsafeUrlError as exc:
            raise ApiError(str(exc), status=400, code="invalid_url") from exc
        return make_ok({"url": validated_url})

    @api_bp.route("/synthesize", methods=["POST"])
    @anonymous_rate_limit(anonymous_synthesize_limiter)
    @rate_limit(synthesize_limiter)
    @api_error_boundary("synthesize_failed")
    def synthesize():
        payload = request.get_json(silent=True) or {}
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ApiError("text required", status=400, code="text_required")
        try:
            text = InputValidator.validate_chat_message(text, max_length=TTS_MAX_CHARS)
        except ValidationError as exc:
            raise ApiError(str(exc), status=400, code="invalid_text") from exc
        return make_ok({"segments": synthesize_text_segments(text)})

    @api_bp.route("/uploads/<path:filename>")
    @api_error_boundary("upload_not_found")
    def uploaded_file_route(filename):
        safe_name = secure_filename(filename)
        if safe_name != filename or not PUBLIC_UPLOAD_NAME_RE.fullmatch(safe_name):
            raise ApiError("Not found", status=404, code="not_found")
        access_and_reference = _uploaded_file_access(safe_name, _resolve_db_user_id())
        if access_and_reference is None:
            raise ApiError("Not found", status=404, code="not_found")

        _access, attachment = access_and_reference
        extension = Path(safe_name).suffix.lower().lstrip(".")
        as_attachment = extension not in {"gif", "jpeg", "jpg", "png", "webp"}
        original_name = str(attachment.get("original_name") or "").replace("\\", "/")
        download_name = Path(original_name).name.replace("\r", "").replace("\n", "")[:255]
        response = send_from_directory(
            str(current_app.config["UPLOAD_FOLDER"]),
            safe_name,
            as_attachment=as_attachment,
            download_name=(download_name or safe_name) if as_attachment else None,
        )
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

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
