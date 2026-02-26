from __future__ import annotations

import uuid
from datetime import datetime

from flask import request

from routes.api_errors import ApiError, api_error_boundary, require_authenticated_user_id
from services.chat_history import build_share_url, resolve_session_identifier
from utils.auth import ChatShare, UserChatHistory, db
from utils.responses import make_ok


def register_share_routes(api_bp):
    @api_bp.route("/sessions/<session_id>/share", methods=["POST"])
    @api_error_boundary("share_update_failed")
    def share_session(session_id):
        from utils.audit_log import AuditEvents, log_audit_event
        from utils.csrf_protection import get_csrf_token_from_request, validate_csrf_token

        db_user_id = require_authenticated_user_id()
        csrf_token = get_csrf_token_from_request()
        if not csrf_token or not validate_csrf_token(csrf_token):
            log_audit_event(AuditEvents.SECURITY_CSRF_FAILURE, {"endpoint": "share_session"})
            raise ApiError("CSRF validation failed", status=403, code="csrf_failed")

        resolved_session_id, share_entry = resolve_session_identifier(session_id)
        chat = UserChatHistory.query.filter_by(
            user_id=db_user_id, session_id=resolved_session_id
        ).first()
        if not chat:
            raise ApiError("Чат не найден или не принадлежит вам", status=404, code="not_found")

        payload = request.get_json(silent=True) or {}
        make_public = bool(payload.get("is_public", True))

        if share_entry is None:
            share_entry = ChatShare(
                user_id=db_user_id,
                session_id=resolved_session_id,
                public_id=f"p_{uuid.uuid4().hex}",
                is_public=make_public,
            )
            db.session.add(share_entry)
        else:
            share_entry.is_public = make_public
            share_entry.updated_at = datetime.utcnow()

        db.session.commit()
        log_audit_event(
            AuditEvents.MODIFY_CHAT_SHARE,
            {"session_id": resolved_session_id, "is_public": make_public},
            db_user_id,
        )

        return make_ok(
            {
                "session_id": resolved_session_id,
                "is_public": share_entry.is_public,
                "public_id": share_entry.public_id,
                "share_url": build_share_url(share_entry.public_id),
                "read_only": False,
            }
        )
