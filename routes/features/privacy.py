from __future__ import annotations

from flask import request, session

from routes.api_errors import ApiError, api_error_boundary, require_authenticated_user_id
from utils.responses import make_ok


def register_privacy_routes(api_bp):
    @api_bp.route("/api/privacy/export", methods=["GET"])
    @api_error_boundary("privacy_export_failed")
    def export_user_data():
        from utils.audit_log import AuditEvents, log_audit_event
        from utils.privacy import export_user_data as do_export

        user_id = require_authenticated_user_id()
        data = do_export(user_id)
        log_audit_event(AuditEvents.ACCESS_USER_DATA, {"action": "export"}, user_id)
        return make_ok({"data": data})

    @api_bp.route("/api/privacy/delete", methods=["POST"])
    @api_error_boundary("privacy_delete_failed")
    def delete_user_data():
        from utils.csrf_protection import get_csrf_token_from_request, validate_csrf_token
        from utils.privacy import delete_user_data as do_delete

        user_id = require_authenticated_user_id()
        csrf_token = get_csrf_token_from_request()
        if not csrf_token or not validate_csrf_token(csrf_token):
            raise ApiError("CSRF validation failed", status=403, code="csrf_failed")

        payload = request.get_json(silent=True) or {}
        delete_account = bool(payload.get("delete_account", False))
        results = do_delete(user_id, delete_account=delete_account)
        if delete_account:
            session.clear()
        return make_ok({"deleted": results})
