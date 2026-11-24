from __future__ import annotations

import json
import re
import uuid
from typing import Any

from flask import (
    request,
    session,
)

from backend.ai_engine.registry import DEFAULT_MODEL_ID
from backend.errors import ApiError
from backend.security.input_validation import InputValidator, ValidationError
from backend.services.chat.generation import CHAT_OPERATIONS
from backend.services.files import validate_chat_uploads
from backend.services.tools.beatbox_tools import normalize_beatbox_state
from backend.services.tools.canvas_tools import normalize_canvas_textdoc

CHAT_REQUEST_FIELDS = frozenset(
    {
        "assistant_message_id",
        "autoWebSearch",
        "beatbox_state",
        "cancel_token",
        "canvas_textdoc",
        "files",
        "history",
        "message",
        "meta",
        "mind_id",
        "model",
        "operation",
        "expected_user_id",
        "expected_guest",
        "request_id",
        "session_id",
        "workspace_id",
        "target_message_id",
        "temporary_chat",
        "composer_content",
        "chat_references",
        "selected_tools",
        "thinkingLevel",
        "serviceTier",
        "thinking_level",
        "user_message_id",
        "webSearch",
    }
)


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
    return payload.get("session_id")


def _allowed_chat_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key in CHAT_REQUEST_FIELDS}


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

    def validate_expected_user_id(payload: dict[str, Any]) -> None:
        raw_expected_user_id = payload.get("expected_user_id")
        raw_expected_guest = payload.get("expected_guest")
        expected_guest = False
        if raw_expected_guest is not None:
            if isinstance(raw_expected_guest, bool):
                expected_guest = raw_expected_guest
            elif isinstance(raw_expected_guest, str) and raw_expected_guest.lower() in {
                "true",
                "false",
            }:
                expected_guest = raw_expected_guest.lower() == "true"
            else:
                raise ApiError(
                    "Invalid authenticated user context.",
                    status=400,
                    code="invalid_expected_guest",
                )
        if expected_guest and raw_expected_user_id not in (None, ""):
            raise ApiError(
                "Invalid authenticated user context.",
                status=400,
                code="invalid_auth_context",
            )
        if expected_guest and auth_user_id is not None:
            raise ApiError(
                "Authentication changed. Please retry the request.",
                status=401,
                code="auth_identity_changed",
            )
        if raw_expected_user_id in (None, ""):
            return
        try:
            expected_user_id = int(str(raw_expected_user_id))
            current_user_id = int(auth_user_id) if auth_user_id is not None else None
        except (TypeError, ValueError) as exc:
            raise ApiError(
                "Invalid authenticated user context.",
                status=400,
                code="invalid_expected_user_id",
            ) from exc
        if current_user_id != expected_user_id:
            raise ApiError(
                "Authentication changed. Please retry the request.",
                status=401,
                code="auth_identity_changed",
            )

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
        data = _allowed_chat_fields(raw_data or {})
        validate_expected_user_id(data)
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

    user_data = _allowed_chat_fields(request.form.to_dict())
    validate_expected_user_id(user_data)
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
