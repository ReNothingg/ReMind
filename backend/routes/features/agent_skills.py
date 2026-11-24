from flask import request

from backend.responses import make_ok
from backend.routes.api_errors import api_error_boundary, require_authenticated_user_id
from backend.security.rate_limiting import RateLimiter, rate_limit
from backend.services import agent_skills
from backend.services.skill_packages import MAX_ARCHIVE_BYTES, skill_error, unpack_skill

mutations = RateLimiter(max_requests=30, time_window=60, namespace="agent_skill_library")


def _json_body():
    if not request.is_json or (request.content_length or 0) > 1024 * 1024:
        raise skill_error("skill_invalid_document")
    return request.get_json(silent=True)


def register_agent_skill_routes(bp):
    @bp.get("/api/agent/skills")
    @bp.get("/api/workspaces/<workspace_id>/skills")
    @api_error_boundary("skill_library_unavailable")
    def list_imported_skills(workspace_id=None):
        return make_ok(
            {"skills": agent_skills.library(require_authenticated_user_id(), workspace_id)}
        )

    @bp.post("/api/agent/skills")
    @bp.post("/api/workspaces/<workspace_id>/skills")
    @rate_limit(mutations, "skill_rate_limited")
    @api_error_boundary("skill_library_unavailable")
    def install_imported_skill(workspace_id=None):
        skill, created = agent_skills.install_skill(
            require_authenticated_user_id(), workspace_id, _json_body()
        )
        return make_ok({"skill": skill}, 201 if created else 200)

    @bp.get("/api/agent/skills/<skill_id>")
    @bp.get("/api/workspaces/<workspace_id>/skills/<skill_id>")
    @api_error_boundary("skill_library_unavailable")
    def inspect_imported_skill(skill_id, workspace_id=None):
        return make_ok(
            {
                "skill": agent_skills.inspect_skill(
                    require_authenticated_user_id(), workspace_id, skill_id
                )
            }
        )

    @bp.patch("/api/agent/skills/<skill_id>")
    @bp.patch("/api/workspaces/<workspace_id>/skills/<skill_id>")
    @rate_limit(mutations, "skill_rate_limited")
    @api_error_boundary("skill_library_unavailable")
    def toggle_imported_skill(skill_id, workspace_id=None):
        return make_ok(
            {
                "skill": agent_skills.toggle_skill(
                    require_authenticated_user_id(), workspace_id, skill_id, _json_body()
                )
            }
        )

    @bp.delete("/api/agent/skills/<skill_id>")
    @bp.delete("/api/workspaces/<workspace_id>/skills/<skill_id>")
    @rate_limit(mutations, "skill_rate_limited")
    @api_error_boundary("skill_library_unavailable")
    def delete_imported_skill(skill_id, workspace_id=None):
        agent_skills.remove_skill(require_authenticated_user_id(), workspace_id, skill_id)
        return make_ok({"deleted": True})

    @bp.post("/api/agent/skills/unpack")
    @rate_limit(mutations, "skill_rate_limited")
    @api_error_boundary("skill_library_unavailable")
    def preview_skill_archive():
        require_authenticated_user_id()
        request.max_content_length = MAX_ARCHIVE_BYTES + 16 * 1024
        if (
            not request.mimetype == "multipart/form-data"
            or len(request.files.getlist("package")) != 1
        ):
            raise skill_error("skill_invalid_package")
        return make_ok(unpack_skill(request.files["package"]))
