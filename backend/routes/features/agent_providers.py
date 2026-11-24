from flask import request

from backend.responses import make_ok
from backend.routes.api_errors import api_error_boundary, require_authenticated_user_id
from backend.security.rate_limiting import RateLimiter, rate_limit
from backend.services.agent_models import (
    preview_catalog,
    provider_status,
    remove_key,
    save_key,
)
from backend.services.agent_runtime_settings import load_agent_runtime, save_agent_runtime
from backend.services.web_research_settings import (
    save_web_research,
    web_research_status,
)

provider_changes = RateLimiter(max_requests=12, time_window=300, namespace="agent_provider_changes")


def register_agent_provider_routes(bp):
    @bp.get("/api/agent/runtime")
    @api_error_boundary("agent_runtime_failed")
    def get_agent_runtime():
        return make_ok(load_agent_runtime(require_authenticated_user_id()))

    @bp.put("/api/agent/runtime")
    @rate_limit(provider_changes, "provider_rate_limited")
    @api_error_boundary("agent_runtime_failed")
    def update_agent_runtime():
        owner = require_authenticated_user_id()
        return make_ok(save_agent_runtime(owner, request.get_json(silent=True)))

    @bp.get("/api/agent/web-research")
    @api_error_boundary("web_settings_failed")
    def get_web_research():
        return make_ok(web_research_status(require_authenticated_user_id()))

    @bp.put("/api/agent/web-research")
    @rate_limit(provider_changes, "provider_rate_limited")
    @api_error_boundary("web_settings_failed")
    def update_web_research():
        owner = require_authenticated_user_id()
        return make_ok(save_web_research(owner, request.get_json(silent=True)))

    @bp.route("/api/agent/telegram", methods=["GET", "PUT"])
    @api_error_boundary("telegram_agent_failed")
    def telegram_agent_preferences():
        from backend.services.telegram.agent import connection_status, update_preferences

        owner = require_authenticated_user_id()
        if request.method == "PUT":
            return make_ok(update_preferences(owner, request.get_json(silent=True)))
        return make_ok(connection_status(owner))

    @bp.get("/api/agent/providers")
    @api_error_boundary("provider_catalog_failed")
    def get_agent_providers():
        return make_ok({"providers": provider_status(require_authenticated_user_id())})

    @bp.post("/api/agent/providers/<provider>/discover")
    @rate_limit(provider_changes, "provider_rate_limited")
    @api_error_boundary("provider_catalog_failed")
    def discover_agent_provider(provider):
        owner = require_authenticated_user_id()
        return make_ok({"models": preview_catalog(owner, provider, request.get_json(silent=True))})

    @bp.route("/api/agent/providers/<provider>", methods=["PUT", "POST", "DELETE"])
    @rate_limit(provider_changes, "provider_rate_limited")
    @api_error_boundary("provider_catalog_failed")
    def change_agent_provider(provider):
        owner = require_authenticated_user_id()
        body = request.get_json(silent=True)
        if request.method == "DELETE":
            remove_key(owner, provider, body)
        else:
            save_key(owner, provider, refresh=request.method == "POST", options=body)
        return make_ok({"providers": provider_status(owner)})
