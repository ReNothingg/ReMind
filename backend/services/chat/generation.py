from __future__ import annotations

import inspect
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import after_this_request

from backend.ai_engine import get_model_function
from backend.config import ALLOW_GUEST_CHATS_SAVE, CHAT_MAX_VARIANTS_PER_TURN
from backend.db.models import UserChatHistory, UserSettings
from backend.errors import ApiError
from backend.responses import logger
from backend.services.agent_plugins import disabled_skills
from backend.services.chat.attachments import (
    build_model_message_for_history,
    build_user_message_parts,
    cleanup_temporary_uploads,
    persist_pending_uploads,
    stored_attachment_parts,
)
from backend.services.chat.cancellation import generation_scope
from backend.services.chat.conversation import conversation_context_for_operation, normalize_message
from backend.services.chat.history import (
    chat_file_exists,
    generate_guest_session_token,
    has_valid_guest_session_token,
    load_chat_graph,
    load_chat_history,
    persist_chat_operation,
    resolve_session_identifier,
)
from backend.services.chat.model_selection import next_model_selection, used_model_selection
from backend.services.chat.search import (
    attach_web_search_context,
    extract_web_sources,
)
from backend.services.chat.session_references import (
    capture_references,
    latest_references,
    parse_reference_ids,
    reference_error,
    reference_target_scope,
)
from backend.services.chat.streaming import ChatStream, stream_chat_response
from backend.services.context_usage import normalize_context_usage
from backend.services.files import restore_stored_file_for_model
from backend.services.minds import (
    require_portable_mind,
    resolve_bound_mind_context_for_chat,
    resolve_mind_context_for_chat,
)
from backend.services.model_access import can_user_access_model, get_model_stage, model_exists
from backend.services.privacy import SERVICE_IMPROVEMENT_SETTING_KEY
from backend.services.project_conversations import bind_project_chat, verify_project_chat
from backend.services.tools.canvas_tools import (
    normalize_canvas_textdoc,
    process_canmore_calls,
)
from backend.services.tools.composer_tools import validate_composer_content, validate_selected_tools


@dataclass(frozen=True)
class ChatImage:
    data: bytes | bytearray
    mime_type: str


CHAT_OPERATIONS = {"send", "regenerate", "edit"}


CHAT_MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")


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
            "context_usage": normalize_context_usage(message.get("context_usage")),
            "recovered": True,
        }
    return None


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


def _load_chat_preferences(user_id: int | None) -> tuple[bool, dict[str, bool]]:
    privacy_controls = {"service_improvement_opt_in": False}
    if user_id is None:
        return False, privacy_controls
    try:
        settings = UserSettings.query.filter_by(user_id=user_id).first()
    except Exception as exc:
        logger.warning("Failed to load chat preferences: %s", exc, exc_info=True)
        return False, privacy_controls
    if settings is None:
        return False, privacy_controls
    try:
        privacy_controls["service_improvement_opt_in"] = bool(
            settings.get_settings().get(SERVICE_IMPROVEMENT_SETTING_KEY, False)
        )
    except Exception as exc:
        logger.warning("Failed to load privacy controls: %s", exc, exc_info=True)
    return bool(settings.automatic_web_search), privacy_controls


def _maybe_direct_image(model_output: Any) -> ChatImage | None:
    image_bytes = getattr(model_output, "image_bytes", None)
    mime_type = getattr(model_output, "mime_type", None)
    if not isinstance(image_bytes, (bytes, bytearray)) or not isinstance(mime_type, str):
        return None

    return ChatImage(image_bytes, mime_type)


def generate_chat(
    session_identifier: str,
    user_data: dict[str, Any],
    model_name: str,
    *,
    db_user_id: int | None,
    remote_addr: str | None,
) -> dict[str, Any] | ChatImage | ChatStream:
    disabled = disabled_skills(db_user_id)
    order = time.time_ns()
    raw_request_id = str(user_data.get("request_id") or uuid.uuid4().hex).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", raw_request_id):
        raise ApiError("Invalid request ID", status=400, code="invalid_request_id")
    user_data["request_id"] = raw_request_id
    if (token := user_data.pop("cancel_token", None)) is not None:
        scope = generation_scope(db_user_id, session_identifier, raw_request_id, token)
        if scope is None:
            raise ApiError("invalid_generation_token", status=400, code="invalid_generation_token")
        user_data["_cancel_scope"] = scope

    resolved_session_id, share_entry = resolve_session_identifier(session_identifier)
    if session_identifier.startswith("p_") and share_entry is None:
        raise ApiError("Chat not found", status=404, code="not_found")
    if share_entry and not (db_user_id and share_entry.user_id == db_user_id):
        if not share_entry.is_public:
            raise ApiError("Chat not found", status=404, code="not_found")
        raise ApiError("Чат доступен только для чтения.", status=403, code="chat_read_only")
    temporary_chat = _coerce_bool(user_data.get("temporary_chat"))
    if db_user_id is not None and not temporary_chat and user_data.get("_automation") is not True:
        user_data["_selection_request_order"] = order
        if not user_data.get("model") and (choice := next_model_selection(db_user_id, resolved_session_id)):
            model_name = choice["model"]
            if not (user_data.get("thinkingLevel") or user_data.get("thinking_level")) and "thinkingLevel" in choice:
                user_data["thinkingLevel"] = choice["thinkingLevel"]
            if not user_data.get("serviceTier") and "serviceTier" in choice:
                user_data["serviceTier"] = choice["serviceTier"]
    if model_name == "demo_image" and model_name in disabled:
        raise ApiError("tool_unavailable", status=403, code="tool_unavailable")
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
    speed = user_data.get("serviceTier") or "standard"
    if speed not in ("standard", "fast", "ultrafast"):
        raise ApiError("model_speed_unavailable", status=400, code="model_speed_unavailable")
    if speed != "standard":
        from backend.services.model_access import list_accessible_models

        model_caps = next(
            (item for item in list_accessible_models(db_user_id) if item["id"] == model_name), {}
        )
        if speed not in model_caps.get("serviceTiers", []):
            raise ApiError("model_speed_unavailable", status=400, code="model_speed_unavailable")

    user_data["selected_tools"] = validate_selected_tools(
        user_data.get("selected_tools"), db_user_id
    )
    user_data["composer_content"] = validate_composer_content(
        user_data.get("composer_content"),
        str(user_data.get("message") or ""),
        user_data["selected_tools"],
        model_name,
    )
    if "web" in user_data["selected_tools"]:
        user_data["webSearch"] = True

    operation = str(user_data.get("operation") or "send").strip().lower()
    if operation not in CHAT_OPERATIONS:
        raise ApiError("Invalid chat operation", status=400, code="invalid_chat_operation")
    workspace_id = user_data.pop("workspace_id", None)
    if workspace_id is not None:
        verify_project_chat(db_user_id, workspace_id, resolved_session_id)
        if temporary_chat or operation != "send" or user_data.get("_automation"):
            raise ApiError(
                "workspace_chat_scope_changed", status=409, code="workspace_chat_scope_changed"
            )
    target_message_id = _validated_message_id(
        user_data.get("target_message_id"), required=operation != "send"
    )
    user_message_id = _validated_message_id(user_data.get("user_message_id")) or (
        f"u_{uuid.uuid4().hex}"
    )
    assistant_message_id = (
        _validated_message_id(user_data.get("assistant_message_id")) or f"a_{uuid.uuid4().hex}"
    )
    allow_guest_file_persistence = _allow_guest_file_persistence(resolved_session_id, db_user_id)

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
            previous_delivery["session_token"] = generate_guest_session_token(
                resolved_session_id, int(time.time())
            )
        return previous_delivery

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
        if model_name.startswith(("key/", "codex/", "chatgpt/")):
            require_portable_mind(mind_context, db_user_id)
        user_data["active_mind"] = mind_context
        user_data["mind_id"] = mind_context["public_id"]
        allowed_skills = mind_context.get("skill_ids")
        if allowed_skills is not None and set(user_data["selected_tools"]).difference(
            allowed_skills
        ):
            raise ApiError("tool_unavailable", status=403, code="tool_unavailable")

    user_data["model"] = model_name
    user_data["session_id"] = resolved_session_id
    if db_user_id is not None and not (
        temporary_chat or user_data.get("_automation") or (share_entry and share_entry.is_public)
    ):
        meta = user_data.get("meta")
        zone = meta.get("time_zone") if isinstance(meta, dict) else None
        if not isinstance(zone, str) or not re.fullmatch(r"[A-Za-z0-9_+/-]{1,80}", zone):
            zone = "UTC"
        try:
            ZoneInfo(zone)
        except (ValueError, ZoneInfoNotFoundError):
            zone = "UTC"
        user_data["_schedule_origin"] = {
            "session_id": resolved_session_id,
            "request_id": raw_request_id,
            "model": model_name,
            "zone": zone,
        }
    model_func = get_model_function(model_name)
    if not model_func:
        raise ApiError(
            f"Model '{model_name}' not supported.", status=400, code="model_not_supported"
        )
    is_streaming_model = inspect.isgeneratorfunction(model_func)
    original_user_message = str(user_data.get("message") or "")
    inherited_attachment_parts: list[dict[str, Any]] = []
    inherited_references = []
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
        inherited_attachment_parts = stored_attachment_parts(parent_user)
        inherited_references = parent_user.get("chat_references", [])
    elif operation == "edit" and not temporary_chat:
        inherited_attachment_parts = stored_attachment_parts(target_message)
        inherited_references = (target_message or {}).get("chat_references", [])

    raw_references = user_data.pop("chat_references", None)
    current_ids = parse_reference_ids(raw_references)
    references_allowed = bool(
        db_user_id and not temporary_chat and not (share_entry and share_entry.is_public)
        and (not mind_context or mind_context.get("owner_id") == db_user_id)
        and not any(user_data.get(key) for key in (
            "_automation", "telegram_context", "external_telegram", "telegram_agent"
        ))
        and is_streaming_model and model_name not in {"demo_image", "mindart"}
    )
    if current_ids and (not references_allowed or operation == "regenerate"):
        raise reference_error("chat_reference_private_only", 400)
    current_references = []
    if references_allowed:
        if current_ids:
            scope = reference_target_scope(db_user_id, resolved_session_id, workspace_id)
            current_references = capture_references(db_user_id, resolved_session_id, scope, current_ids)
        elif raw_references is None:
            current_references = inherited_references
        user_data["_session_references"] = latest_references(current_references, history)

    restored_inherited_files: list[dict[str, Any]] = []
    if operation in {"regenerate", "edit"} and not temporary_chat:
        restored_inherited_files = [
            restored
            for part in inherited_attachment_parts
            if isinstance(attachment := part.get("image") or part.get("file"), dict)
            and (restored := restore_stored_file_for_model(attachment))
        ]

    if not (original_user_message or user_data.get("_pending_uploads") or restored_inherited_files):
        raise ApiError("'message' or 'files' required", status=400, code="missing_input")

    uploaded_files_for_history = persist_pending_uploads(user_data, resolved_session_id)
    if operation in {"regenerate", "edit"} and not temporary_chat:
        user_data["files"] = (
            [*uploaded_files_for_history, *restored_inherited_files]
            if operation == "edit"
            else restored_inherited_files
        )

    if uploaded_files_for_history:

        @after_this_request
        def cleanup_uncommitted_uploads(response):
            streaming_response_will_own_cleanup = is_streaming_model and response.status_code < 400
            if not streaming_response_will_own_cleanup and (
                temporary_chat or response.status_code >= 400
            ):
                cleanup_temporary_uploads({"files": uploaded_files_for_history})
            return response

    if workspace_id is not None:
        bind_project_chat(db_user_id, workspace_id, resolved_session_id)
        user_data["_workspace_scope"] = workspace_id

    user_data["message"] = original_user_message

    user_data["history"] = history
    user_data["history_is_canonical"] = not temporary_chat
    user_data["_context_is_private_web"] = bool(
        db_user_id is not None and not temporary_chat and not (share_entry and share_entry.is_public)
    )
    user_data["tool_rate_key"] = (
        f"user_{db_user_id}" if db_user_id is not None else f"guest_{remote_addr or 'unknown'}"
    )
    auto_web_search, privacy_controls = _load_chat_preferences(db_user_id)
    if user_data.get("_automation") is True:
        auto_web_search = False
    if "web" in disabled or (
        mind_context
        and mind_context.get("skill_ids") is not None
        and "web" not in mind_context["skill_ids"]
    ):
        user_data["webSearch"] = False
        auto_web_search = False
    user_data["privacy"] = privacy_controls
    user_data["temporary_chat"] = temporary_chat
    user_data["autoWebSearch"] = auto_web_search

    user_message_parts = (
        build_user_message_parts(original_user_message, uploaded_files_for_history)
        + inherited_attachment_parts
    )
    user_message_for_history = (
        normalize_message(
            {
                "id": user_message_id,
                "role": "user",
                "parts": user_message_parts,
                "composer_content": user_data.get("composer_content"),
                "chat_references": current_references,
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
        return stream_chat_response(
            model_name=model_name,
            model_func=model_func,
            db_user_id=db_user_id,
            user_data=user_data,
            resolved_session_id=resolved_session_id,
            user_message_for_history=user_message_for_history,
            allow_guest_file_persistence=allow_guest_file_persistence,
            temporary_chat=temporary_chat,
            mind_context=mind_context,
            newly_uploaded_files=uploaded_files_for_history,
        )

    if "web" not in disabled and (
        user_data.get("_automation") is not True or user_data.get("webSearch")
    ):
        attach_web_search_context(
            user_data, original_user_message, auto_enabled=auto_web_search, owner=db_user_id
        )
    model_output = model_func(db_user_id, user_data)
    web_sources = extract_web_sources(user_data)
    canvas_textdoc = normalize_canvas_textdoc(user_data.get("canvas_textdoc"))
    non_stream_canvas_updates: list[dict[str, Any]] = []
    non_stream_canvas_textdoc: dict[str, Any] | None = None
    if isinstance(model_output, dict):
        canvas_result = process_canmore_calls(str(model_output.get("reply") or ""), canvas_textdoc)
        if canvas_result.updates:
            model_output["reply"] = canvas_result.reply
            model_output["canvas_updates"] = canvas_result.updates
            model_output["canvas_textdoc"] = canvas_result.textdoc
            non_stream_canvas_updates = canvas_result.updates
            non_stream_canvas_textdoc = canvas_result.textdoc
        if web_sources and "sources" not in model_output:
            model_output["sources"] = web_sources
        model_message_for_history = build_model_message_for_history(
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
        model_message_for_history = build_model_message_for_history(
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
            model_message={
                **model_message_for_history,
                "selected_tools": user_data.get("selected_tools", []),
            },
            model_name=model_name,
            user_id=db_user_id,
            allow_guest_file_persistence=allow_guest_file_persistence,
            mind_id=mind_context.get("id") if mind_context else None,
            require_existing=user_data.get("_automation") is True,
            workspace_scope=workspace_id,
            selection=used_model_selection(model_name, user_data),
        )

    direct_image_response = _maybe_direct_image(model_output)
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
        response_data["session_token"] = generate_guest_session_token(
            resolved_session_id, int(time.time())
        )
    response_data["sessionId"] = resolved_session_id
    response_data["uploaded_files"] = [] if temporary_chat else user_data.get("files", [])
    response_data["request_id"] = raw_request_id
    response_data["delivery_status"] = "complete"
    response_data["history"] = canonical_history

    return response_data
