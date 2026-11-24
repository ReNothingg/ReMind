import secrets

from flask import redirect, request, session

from backend.ai_engine.errors import ProviderRequestError
from backend.errors import ApiError
from backend.responses import make_ok
from backend.routes.api_errors import api_error_boundary, require_authenticated_user_id
from backend.security.rate_limiting import api_limiter, rate_limit
from backend.services import chatgpt_account


def register_chatgpt_routes(bp):
    @bp.get("/api/chatgpt")
    @api_error_boundary("chatgpt_status_failed")
    def chatgpt_status():
        data = chatgpt_account.status(require_authenticated_user_id())
        data["login_error"] = bool(session.pop("chatgpt_login_error", False))
        return make_ok(data)

    @bp.post("/api/chatgpt/connect")
    @rate_limit(api_limiter, "chatgpt_rate_limited")
    @api_error_boundary("chatgpt_login_failed")
    def chatgpt_connect():
        user_id = require_authenticated_user_id()
        state = secrets.token_urlsafe(36)
        options = request.get_json(silent=True) or {}
        try:
            url = chatgpt_account.start_login(
                user_id,
                state,
                different_account=isinstance(options, dict)
                and options.get("different_account") is True,
            )
        except ProviderRequestError as exc:
            raise ApiError(exc.code, status=exc.status, code=exc.code) from exc
        session["chatgpt_oauth_state"] = state
        return make_ok({"url": url})

    @bp.get("/auth/callback")
    def chatgpt_callback():
        user_id = session.get("user_id")
        state = session.get("chatgpt_oauth_state")
        if (
            user_id
            and state
            and secrets.compare_digest(state.encode(), request.args.get("state", "").encode())
        ):
            session.pop("chatgpt_oauth_state", None)
            try:
                chatgpt_account.complete_login(int(user_id), state, request.args)
            except ProviderRequestError:
                session["chatgpt_login_error"] = True
        response = redirect("/#settings/models", code=303)
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @bp.delete("/api/chatgpt")
    @api_error_boundary("chatgpt_disconnect_failed")
    def chatgpt_disconnect():
        session.pop("chatgpt_oauth_state", None)
        return make_ok({"revoked": chatgpt_account.disconnect(require_authenticated_user_id())})
