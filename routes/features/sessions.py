from __future__ import annotations

import json
import re
import uuid

from flask import request, session
from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from config import ALLOW_GUEST_CHATS_SAVE
from routes.api_errors import ApiError, api_error_boundary, require_authenticated_user_id
from routes.features.minds import get_mind_for_session_binding, serialize_mind_for_session
from services.attachment_lifecycle import (
    collect_managed_references,
    delete_unreferenced_managed_files,
)
from services.canvas_tools import MAX_TEXTDOC_CONTENT_LENGTH
from services.chat_history import (
    _verify_guest_session_token,
    build_share_url,
    chat_file_exists,
    delete_guest_chat_file,
    has_valid_guest_session_token,
    load_chat_history,
    materialize_conversation_history,
    read_chat_file,
    read_chat_file_secure,
    resolve_session_identifier,
    save_canvas_textdoc_to_history,
    select_conversation_variant,
    write_chat_file,
)
from utils.auth import ChatShare, UserChatHistory, db
from utils.input_validation import InputValidator, ValidationError
from utils.responses import make_ok

MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")


def _safe_session_preview(messages: list) -> str:
    if not messages:
        return ""
    last = messages[-1]
    parts = last.get("parts", [])
    if parts and isinstance(parts[0], dict):
        return str(parts[0].get("text", ""))[:60]
    return ""


def _session_timestamp(chat: UserChatHistory) -> float:
    if chat.updated_at:
        return chat.updated_at.timestamp()
    if chat.created_at:
        return chat.created_at.timestamp()
    return 0.0


def _session_mind_payload(chat: UserChatHistory | None, viewer_id: int | None) -> dict | None:
    if not chat:
        return None
    return serialize_mind_for_session(chat.mind_id, viewer_id)


def _public_history(history: list[dict]) -> list[dict]:
    hidden_fields = {
        "variants",
        "current_variant_index",
        "parent_id",
        "is_active",
        "request_id",
        "delivery_status",
    }
    return [
        {key: value for key, value in message.items() if key not in hidden_fields}
        for message in history
    ]


def _parse_guest_tokens_header() -> dict[str, str]:
    raw_tokens = request.headers.get("X-Guest-Tokens", "")
    if not raw_tokens:
        return {}
    if len(raw_tokens) > 16384:
        raise ApiError("Guest token map too large", status=400, code="invalid_guest_tokens")
    try:
        parsed = json.loads(raw_tokens)
    except json.JSONDecodeError as exc:
        raise ApiError("Invalid guest token map", status=400, code="invalid_guest_tokens") from exc
    if not isinstance(parsed, dict):
        raise ApiError("Invalid guest token map", status=400, code="invalid_guest_tokens")
    return parsed


def register_session_routes(api_bp):
    @api_bp.route("/sessions/<session_id>/canvas", methods=["PUT"])
    @api_error_boundary("canvas_save_failed")
    def save_session_canvas(session_id):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("textdoc"), dict):
            raise ApiError("Invalid Canvas document", status=400, code="invalid_canvas_textdoc")
        raw_content = payload["textdoc"].get("content")
        if not isinstance(raw_content, str) or len(raw_content) > MAX_TEXTDOC_CONTENT_LENGTH:
            raise ApiError("Invalid Canvas document", status=400, code="invalid_canvas_textdoc")
        resolved_session_id, share_entry = resolve_session_identifier(session_id)

        db_user_id = None
        try:
            if "user_id" in session:
                db_user_id = int(session.get("user_id"))
        except (TypeError, ValueError) as exc:
            raise ApiError("Invalid user session", status=401, code="auth_required") from exc

        if db_user_id is not None:
            if share_entry and share_entry.user_id != db_user_id:
                raise ApiError("Chat not found", status=404, code="not_found")
            textdoc = save_canvas_textdoc_to_history(
                resolved_session_id,
                payload["textdoc"],
                user_id=db_user_id,
            )
        else:
            safe_session_id = secure_filename(str(resolved_session_id))
            if (
                not ALLOW_GUEST_CHATS_SAVE
                or not safe_session_id
                or not chat_file_exists(safe_session_id)
            ):
                raise ApiError("Chat not found", status=404, code="not_found")
            if not has_valid_guest_session_token(safe_session_id):
                raise ApiError("Authentication required", status=401, code="auth_required")
            textdoc = save_canvas_textdoc_to_history(
                safe_session_id,
                payload["textdoc"],
                guest_file=True,
            )

        if not textdoc:
            raise ApiError("Canvas document not found", status=404, code="not_found")
        return make_ok({"session_id": resolved_session_id, "textdoc": textdoc})

    @api_bp.route("/sessions/<session_id>/history", methods=["GET"])
    @api_error_boundary("session_history_failed")
    def get_session_history(session_id):
        resolved_session_id, share_entry = resolve_session_identifier(session_id)
        db_user_id = None
        try:
            if "user_id" in session:
                db_user_id = int(session.get("user_id"))
        except (TypeError, ValueError):
            db_user_id = None

        is_public = bool(share_entry and share_entry.is_public)
        is_owner = bool(db_user_id and share_entry and share_entry.user_id == db_user_id)

        if is_public:
            chat = (
                UserChatHistory.query.filter_by(
                    user_id=share_entry.user_id,
                    session_id=resolved_session_id,
                ).first()
                if resolved_session_id
                else None
            )
            history = (
                materialize_conversation_history(chat.get_messages())
                if chat
                else load_chat_history(resolved_session_id)
            )
            if not is_owner:
                history = _public_history(history)
            title = chat.title if chat else None
            return make_ok(
                {
                    "session_id": resolved_session_id,
                    "history": history,
                    "title": title,
                    "mind": _session_mind_payload(chat, db_user_id),
                    "is_public": True,
                    "is_owner": is_owner,
                    "public_id": share_entry.public_id if share_entry else None,
                    "share_url": build_share_url(share_entry.public_id) if share_entry else None,
                    "read_only": not is_owner,
                }
            )

        if db_user_id is not None:
            chat = UserChatHistory.query.filter_by(
                user_id=db_user_id, session_id=resolved_session_id
            ).first()
            if chat:
                return make_ok(
                    {
                        "session_id": resolved_session_id,
                        "history": materialize_conversation_history(chat.get_messages()),
                        "title": chat.title,
                        "mind": _session_mind_payload(chat, db_user_id),
                        "is_public": False,
                        "is_owner": True,
                    }
                )

        if db_user_id is not None:
            raise ApiError("Chat not found", status=404, code="not_found")

        if not ALLOW_GUEST_CHATS_SAVE:
            raise ApiError("Chat not found", status=404, code="not_found")

        safe_session_id = secure_filename(str(resolved_session_id))
        if not safe_session_id or not chat_file_exists(safe_session_id):
            raise ApiError("Chat not found", status=404, code="not_found")
        if not has_valid_guest_session_token(safe_session_id):
            raise ApiError("Authentication required", status=401, code="auth_required")

        data = read_chat_file_secure(safe_session_id, require_auth=True)
        history = materialize_conversation_history(
            data.get("history", []) if isinstance(data, dict) else []
        )
        title = data.get("title") if isinstance(data, dict) else None
        return make_ok(
            {
                "session_id": resolved_session_id,
                "history": history,
                "title": title,
                "mind": None,
                "is_public": False,
                "is_owner": False,
            }
        )

    @api_bp.route("/sessions", methods=["GET"])
    @api_error_boundary("sessions_list_failed")
    def list_sessions():
        sessions = []
        db_user_id = None
        page = max(1, request.args.get("page", default=1, type=int) or 1)
        page_size = max(1, min(request.args.get("page_size", default=50, type=int) or 50, 100))
        total = 0
        has_more = False

        if "user_id" in session:
            try:
                db_user_id = int(session.get("user_id"))
            except (TypeError, ValueError) as exc:
                raise ApiError("Invalid user session", status=401, code="auth_required") from exc

            base_query = (
                db.session.query(UserChatHistory, ChatShare.public_id, ChatShare.is_public)
                .outerjoin(
                    ChatShare,
                    and_(
                        ChatShare.user_id == db_user_id,
                        ChatShare.session_id == UserChatHistory.session_id,
                    ),
                )
                .filter(UserChatHistory.user_id == db_user_id)
            )
            total = base_query.count()
            has_more = (page * page_size) < total
            rows = (
                base_query.order_by(
                    UserChatHistory.updated_at.desc(), UserChatHistory.created_at.desc()
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            seen_session_ids: set[str] = set()
            for chat, public_id, is_public in rows:
                if chat.session_id in seen_session_ids:
                    continue
                seen_session_ids.add(chat.session_id)
                sessions.append(
                    {
                        "session_id": chat.session_id,
                        "last_updated": _session_timestamp(chat),
                        "title": chat.title or "Новый чат",
                        "last_message": _safe_session_preview(
                            materialize_conversation_history(chat.get_messages())
                        ),
                        "is_public": bool(is_public),
                        "public_id": public_id,
                        "mind": _session_mind_payload(chat, db_user_id),
                    }
                )

        request_ids = request.args.get("ids")
        if not db_user_id and request_ids and ALLOW_GUEST_CHATS_SAVE:
            token_map = _parse_guest_tokens_header()
            id_list = request_ids.split(",")[:100]
            for raw_session_id in id_list:
                safe_sid = secure_filename(raw_session_id.strip())
                if not safe_sid:
                    continue

                token = token_map.get(raw_session_id.strip()) or token_map.get(safe_sid)
                if not token or not _verify_guest_session_token(token, safe_sid):
                    continue

                data = read_chat_file(safe_sid)
                if not data:
                    continue

                history = materialize_conversation_history(data.get("history", []))
                sessions.append(
                    {
                        "session_id": safe_sid,
                        "last_updated": data.get("last_updated", 0),
                        "title": data.get("title", "Новый чат"),
                        "last_message": _safe_session_preview(history),
                    }
                )

        if not db_user_id:
            sessions.sort(key=lambda item: item.get("last_updated", 0), reverse=True)
            total = len(sessions)
            start = (page - 1) * page_size
            end = start + page_size
            has_more = end < total
            sessions = sessions[start:end]

        return make_ok(
            {
                "sessions": sessions,
                "page": page,
                "page_size": page_size,
                "total": total,
                "has_more": has_more,
            }
        )

    @api_bp.route("/sessions/<session_id>/branch", methods=["PUT"])
    @api_error_boundary("session_branch_failed")
    def select_session_branch(session_id):
        payload = request.get_json(silent=True) or {}
        message_id = payload.get("message_id")
        if not isinstance(message_id, str) or not MESSAGE_ID_RE.fullmatch(message_id):
            raise ApiError("Invalid message ID", status=400, code="invalid_message_id")

        resolved_session_id, share_entry = resolve_session_identifier(session_id)
        raw_user_id = session.get("user_id")
        db_user_id = int(raw_user_id) if isinstance(raw_user_id, int) else None
        if share_entry and (db_user_id is None or share_entry.user_id != db_user_id):
            raise ApiError("Chat not found", status=404, code="not_found")

        try:
            if db_user_id is not None:
                history = select_conversation_variant(
                    resolved_session_id,
                    message_id,
                    user_id=db_user_id,
                )
            else:
                safe_session_id = secure_filename(str(resolved_session_id))
                if (
                    not ALLOW_GUEST_CHATS_SAVE
                    or not safe_session_id
                    or not has_valid_guest_session_token(safe_session_id)
                ):
                    raise ApiError("Authentication required", status=401, code="auth_required")
                history = select_conversation_variant(
                    safe_session_id,
                    message_id,
                    allow_guest_file_persistence=True,
                )
        except ValueError as exc:
            raise ApiError("Chat branch not found", status=404, code=str(exc)) from exc

        return make_ok({"session_id": resolved_session_id, "history": history})

    @api_bp.route("/sessions", methods=["POST"])
    @api_error_boundary("session_create_failed")
    def create_session():
        if "user_id" not in session:
            return make_ok({"session_id": f"guest_{uuid.uuid4().hex}"})

        db_user_id = require_authenticated_user_id()
        data = request.get_json(silent=True) or {}
        raw_session_id = data.get("session_id")
        if raw_session_id:
            try:
                session_id = InputValidator.validate_session_id(str(raw_session_id))
            except ValidationError as exc:
                raise ApiError(str(exc), status=400, code="invalid_session_id") from exc
        else:
            session_id = f"user_{uuid.uuid4().hex}"

        raw_title = data.get("title", "Новый чат")
        title = str(raw_title).strip()[:200] if raw_title else "Новый чат"
        if not title:
            title = "Новый чат"

        existing = UserChatHistory.query.filter_by(
            user_id=db_user_id, session_id=session_id
        ).first()
        if existing:
            return make_ok({"session_id": existing.session_id})
        chat = UserChatHistory(user_id=db_user_id, session_id=session_id, title=title)
        db.session.add(chat)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            existing = UserChatHistory.query.filter_by(
                user_id=db_user_id, session_id=session_id
            ).first()
            if existing:
                return make_ok({"session_id": existing.session_id})
            raise
        return make_ok({"session_id": session_id})

    @api_bp.route("/sessions/<session_id>/mind", methods=["PUT", "DELETE"])
    @api_error_boundary("session_mind_update_failed")
    def update_session_mind(session_id):
        db_user_id = require_authenticated_user_id()
        resolved_session_id, _share_entry = resolve_session_identifier(session_id)
        chat = UserChatHistory.query.filter_by(
            user_id=db_user_id, session_id=resolved_session_id
        ).first()
        if not chat:
            raise ApiError("Chat not found", status=404, code="not_found")

        if request.method == "DELETE":
            chat.mind_id = None
            db.session.commit()
            return make_ok({"session_id": resolved_session_id, "mind": None})

        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            raise ApiError("Invalid JSON payload", status=400, code="invalid_json")

        public_mind_id = data.get("mind_id")
        if public_mind_id is None or str(public_mind_id).strip() == "":
            chat.mind_id = None
            db.session.commit()
            return make_ok({"session_id": resolved_session_id, "mind": None})

        mind = get_mind_for_session_binding(str(public_mind_id), db_user_id)
        if mind is None:
            raise ApiError("Mind not found", status=404, code="not_found")

        chat.mind_id = mind.id
        db.session.commit()
        return make_ok(
            {
                "session_id": resolved_session_id,
                "mind": serialize_mind_for_session(mind.id, db_user_id),
            }
        )

    @api_bp.route("/sessions/<session_id>/rename", methods=["POST"])
    @api_error_boundary("session_rename_failed")
    def rename_session(session_id):
        resolved_session_id, _share_entry = resolve_session_identifier(session_id)
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            raise ApiError("Invalid JSON payload", status=400, code="invalid_json")

        title = str(data.get("title") or "").strip()[:200]
        if not title:
            raise ApiError("Title is required", status=400, code="invalid_title")

        raw_user_id = session.get("user_id")
        if isinstance(raw_user_id, int):
            updated = UserChatHistory.query.filter_by(
                user_id=raw_user_id, session_id=resolved_session_id
            ).update({"title": title}, synchronize_session=False)
            if not updated:
                raise ApiError("Chat not found", status=404, code="not_found")
            db.session.commit()
        else:
            safe_session_id = secure_filename(str(resolved_session_id))
            if (
                not ALLOW_GUEST_CHATS_SAVE
                or not safe_session_id
                or not has_valid_guest_session_token(safe_session_id)
            ):
                raise ApiError("Authentication required", status=401, code="auth_required")
            chat_data = read_chat_file_secure(safe_session_id, require_auth=True)
            if not chat_data:
                raise ApiError("Chat not found", status=404, code="not_found")
            chat_data["title"] = title
            write_chat_file(safe_session_id, chat_data)
        return make_ok({"session_id": resolved_session_id, "title": title})

    @api_bp.route("/sessions/<session_id>", methods=["DELETE"])
    @api_error_boundary("session_delete_failed")
    def delete_session(session_id):
        from utils.audit_log import AuditEvents, log_audit_event

        raw_user_id = session.get("user_id")
        if isinstance(raw_user_id, int):
            chat = UserChatHistory.query.filter_by(
                user_id=raw_user_id, session_id=session_id
            ).first()
            if not chat:
                raise ApiError("Chat not found", status=404, code="not_found")
            managed_references = collect_managed_references(chat.get_messages())
            db.session.delete(chat)
            ChatShare.query.filter_by(user_id=raw_user_id, session_id=session_id).delete(
                synchronize_session=False
            )
            db.session.commit()
            delete_unreferenced_managed_files(managed_references)
            log_audit_event(AuditEvents.DELETE_CHAT, {"session_id": session_id}, raw_user_id)
            return "", 204

        safe_session_id = secure_filename(str(session_id))
        if (
            not ALLOW_GUEST_CHATS_SAVE
            or not safe_session_id
            or not has_valid_guest_session_token(safe_session_id)
        ):
            raise ApiError("Authentication required", status=401, code="auth_required")
        guest_chat_data = read_chat_file_secure(safe_session_id, require_auth=True)
        managed_references = collect_managed_references(guest_chat_data)
        if not delete_guest_chat_file(safe_session_id):
            raise ApiError("Chat not found", status=404, code="not_found")
        delete_unreferenced_managed_files(managed_references)
        return "", 204
