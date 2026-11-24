from flask import request

from backend.responses import make_ok
from backend.routes.api_errors import api_error_boundary, require_authenticated_user_id
from backend.security.rate_limiting import RateLimiter, rate_limit
from backend.services import agent_plugins

mutations = RateLimiter(max_requests=30, time_window=60, namespace="agent_plugins")


def _body():
    if not request.is_json or (request.content_length or 0) > 25000:
        raise agent_plugins.plugin_error("plugin_invalid_manifest")
    return request.get_json(silent=True)


def register_agent_plugin_routes(bp):
    @bp.get("/api/plugins")
    @api_error_boundary("plugin_unavailable")
    def list_agent_plugins():
        return make_ok(agent_plugins.catalog(require_authenticated_user_id()))

    @bp.post("/api/plugins")
    @rate_limit(mutations, "plugin_rate_limited")
    @api_error_boundary("plugin_unavailable")
    def install_agent_plugin():
        plugin = agent_plugins.install_plugin(require_authenticated_user_id(), _body())
        return make_ok({"plugin": plugin}, 201)

    @bp.patch("/api/plugins/<plugin_id>")
    @rate_limit(mutations, "plugin_rate_limited")
    @api_error_boundary("plugin_unavailable")
    def edit_agent_plugin(plugin_id):
        plugin = agent_plugins.edit_plugin(require_authenticated_user_id(), plugin_id, _body())
        return make_ok({"plugin": plugin})

    @bp.delete("/api/plugins/<plugin_id>")
    @rate_limit(mutations, "plugin_rate_limited")
    @api_error_boundary("plugin_unavailable")
    def delete_agent_plugin(plugin_id):
        agent_plugins.remove_plugin(require_authenticated_user_id(), plugin_id)
        return make_ok({"deleted": True})

    @bp.put("/api/plugins/builtin/<skill_id>")
    @rate_limit(mutations, "plugin_rate_limited")
    @api_error_boundary("plugin_unavailable")
    def toggle_builtin_plugin(skill_id):
        owner = require_authenticated_user_id()
        payload = _body()
        if not isinstance(payload, dict) or set(payload) != {"enabled"}:
            raise agent_plugins.plugin_error("plugin_invalid_manifest")
        agent_plugins.set_builtin(owner, skill_id, payload["enabled"])
        return make_ok({"enabled": payload["enabled"]})
