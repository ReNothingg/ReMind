from flask import Response, request

from backend.responses import make_ok
from backend.routes.api_errors import api_error_boundary, require_authenticated_user_id
from backend.security.rate_limiting import RateLimiter, rate_limit
from backend.services import codex_account, workspaces

login_limiter = RateLimiter(max_requests=24, time_window=300, namespace="workspace_enter")


def bearer():
    value = request.headers.get("Authorization", "")
    return value[7:] if value.startswith("Bearer ") and len(value) < 16384 else ""


def register_workspace_routes(bp):
    @bp.get("/internal/agent/public-key")
    def workspace_public_key():
        return Response(workspaces.public_key(), mimetype="text/plain")

    @bp.post("/internal/agent/rpc-check")
    @api_error_boundary("workspace_session_expired")
    def verify_workspace_rpc():
        row, _ = workspaces.verify(bearer(), "rpc")
        return make_ok({"workspace": row.workspace_id, "generation": row.generation})

    @bp.post("/internal/agent/cleanup")
    @api_error_boundary("workspace_runtime_unavailable")
    def check_retired_workspace():
        return make_ok(
            {"instruction": workspaces.cleanup_instruction(request.get_json(silent=True))}
        )

    @bp.get("/api/agent/codex")
    @api_error_boundary("workspace_runtime_unavailable")
    def codex_status():
        owner = require_authenticated_user_id()
        data = codex_account.describe(owner, refresh=request.args.get("refresh") == "1")
        return make_ok({key: value for key, value in data.items() if key != "models"})

    @bp.post("/api/agent/codex")
    @rate_limit(login_limiter, "workspace_rate_limited")
    @api_error_boundary("workspace_runtime_unavailable")
    def codex_login():
        return make_ok(codex_account.start(require_authenticated_user_id()))

    @bp.delete("/api/agent/codex")
    @api_error_boundary("workspace_runtime_unavailable")
    def codex_logout():
        codex_account.unlink(require_authenticated_user_id())
        return make_ok({"connected": False})

    @bp.post("/api/agent/codex/cancel")
    @api_error_boundary("workspace_runtime_unavailable")
    def cancel_codex_login():
        owner = require_authenticated_user_id()
        slot = workspaces.existing(owner)
        if slot:
            workspaces.rpc(slot, "codex/cancel", owner=owner)
        return make_ok({"ok": True})
