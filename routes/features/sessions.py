from __future__ import annotations

import json
import uuid
from datetime import datetime

from flask import request, session
from sqlalchemy import and_
from werkzeug.utils import secure_filename

from config import ALLOW_GUEST_CHATS_SAVE
from routes.api_errors import ApiError, api_error_boundary, require_authenticated_user_id
from services.chat_history import (
    _verify_guest_session_token,
    build_share_url,
    load_chat_history,
    read_chat_file,
    read_chat_file_secure,
    resolve_session_identifier,
)
from utils.auth import ChatShare, UserChatHistory, db
from utils.input_validation import InputValidator, ValidationError
from utils.responses import logger, make_ok


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
                UserChatHistory.query.filter_by(session_id=resolved_session_id).first()
                if resolved_session_id
                else None
            )
            history = chat.get_messages() if chat else load_chat_history(resolved_session_id)
            title = chat.title if chat else None
            return make_ok(
                {
                    "session_id": resolved_session_id,
                    "history": history,
                    "title": title,
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
                        "history": chat.get_messages(),
                        "title": chat.title,
                        "is_public": False,
                        "is_owner": True,
                    }
                )

        if not ALLOW_GUEST_CHATS_SAVE and "user_id" not in session:
            return make_ok({"session_id": resolved_session_id, "history": [], "title": None})

        safe_session_id = secure_filename(str(resolved_session_id))
        data = read_chat_file_secure(safe_session_id, require_auth=True)
        history = data.get("history", []) if isinstance(data, dict) else []
        title = data.get("title") if isinstance(data, dict) else None
        return make_ok(
            {
                "session_id": resolved_session_id,
                "history": history,
                "title": title,
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
            for chat, public_id, is_public in rows:
                sessions.append(
                    {
                        "session_id": chat.session_id,
                        "last_updated": _session_timestamp(chat),
                        "title": chat.title or "Новый чат",
                        "last_message": _safe_session_preview(chat.get_messages()),
                        "is_public": bool(is_public),
                        "public_id": public_id,
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

                history = data.get("history", [])
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

        chat = UserChatHistory(user_id=db_user_id, session_id=session_id, title=title)
        db.session.add(chat)
        db.session.commit()
        return make_ok({"session_id": session_id})

    @api_bp.route("/sessions/<session_id>", methods=["DELETE"])
    @api_error_boundary("session_delete_failed")
    def delete_session(session_id):
        from utils.audit_log import AuditEvents, log_audit_event

        db_user_id = require_authenticated_user_id()
        chat = UserChatHistory.query.filter_by(user_id=db_user_id, session_id=session_id).first()
        if not chat:
            raise ApiError("Chat not found", status=404, code="not_found")

        db.session.delete(chat)
        db.session.commit()
        log_audit_event(AuditEvents.DELETE_CHAT, {"session_id": session_id}, db_user_id)
        return "", 204
