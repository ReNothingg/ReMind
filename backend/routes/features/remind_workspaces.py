from pathlib import PurePosixPath
from uuid import uuid4

from flask import request, send_file

from backend.db.models import (
    AgentSkill,
    ReMindWorkspace,
    ReMindWorkspaceFile,
    UserChatHistory,
    WorkspacePatchProposal,
    db,
)
from backend.errors import ApiError
from backend.responses import make_ok
from backend.routes.api_errors import api_error_boundary, require_authenticated_user_id
from backend.security.rate_limiting import RateLimiter, rate_limit
from backend.services import project_artifacts, project_patches, project_resources

mutations = RateLimiter(max_requests=30, time_window=60, namespace="remind_workspace")


def _name(field, limit):
    data = request.get_json(silent=True)
    value = data.get(field) if isinstance(data, dict) else None
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or any(ord(ch) < 32 for ch in value)
    ):
        raise ApiError("invalid_workspace_name", status=400, code="invalid_workspace_name")
    return value.strip()


def _workspace(owner, workspace_id):
    return project_resources.owned_workspace(owner, workspace_id, lock=True)


def register_remind_workspace_routes(bp):
    @bp.get("/api/workspaces")
    @api_error_boundary("workspace_runtime_unavailable")
    def list_remind_workspaces():
        owner = require_authenticated_user_id()
        rows = (
            ReMindWorkspace.query.filter_by(user_id=owner)
            .order_by(ReMindWorkspace.created_at)
            .all()
        )
        return make_ok({"workspaces": [{"id": row.id, "name": row.name} for row in rows]})

    @bp.post("/api/workspaces")
    @rate_limit(mutations, "workspace_rate_limited")
    @api_error_boundary("workspace_runtime_unavailable")
    def create_remind_workspace():
        owner = require_authenticated_user_id()
        row = ReMindWorkspace(id=uuid4().hex, user_id=owner, name=_name("name", 80))
        db.session.add(row)
        db.session.commit()
        return make_ok({"id": row.id, "name": row.name}, 201)

    @bp.patch("/api/workspaces/<workspace_id>")
    @rate_limit(mutations, "workspace_rate_limited")
    @api_error_boundary("workspace_runtime_unavailable")
    def rename_remind_workspace(workspace_id):
        row = _workspace(require_authenticated_user_id(), workspace_id)
        row.name = _name("name", 80)
        db.session.commit()
        return make_ok({"id": row.id, "name": row.name})

    @bp.get("/api/workspaces/<workspace_id>")
    @api_error_boundary("workspace_runtime_unavailable")
    def get_remind_workspace(workspace_id):
        owner = require_authenticated_user_id()
        row = project_resources.owned_workspace(owner, workspace_id)
        return make_ok(project_resources.workspace_document(row))

    @bp.put("/api/workspaces/<workspace_id>/instructions")
    @rate_limit(mutations, "workspace_rate_limited")
    @api_error_boundary("workspace_runtime_unavailable")
    def save_workspace_instructions(workspace_id):
        row = _workspace(require_authenticated_user_id(), workspace_id)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {"instructions"}:
            raise project_resources.resource_error("invalid_workspace_instructions")
        row.instructions = project_resources.validate_instructions(payload["instructions"])
        db.session.commit()
        return make_ok({"instructions": row.instructions})

    @bp.post("/api/workspaces/<workspace_id>/files")
    @rate_limit(mutations, "workspace_rate_limited")
    @api_error_boundary("workspace_runtime_unavailable")
    def add_workspace_files(workspace_id):
        owner = require_authenticated_user_id()
        return make_ok(
            {
                "files": project_resources.upload_files(
                    owner, workspace_id, request.files.getlist("files")
                )
            },
            201,
        )

    @bp.post("/api/workspaces/<workspace_id>/files/from-chat")
    @rate_limit(mutations, "workspace_rate_limited")
    @api_error_boundary("workspace_runtime_unavailable")
    def publish_chat_artifact(workspace_id):
        file, created = project_artifacts.publish(
            require_authenticated_user_id(), workspace_id, request.get_json(silent=True)
        )
        return make_ok({"file": file}, 201 if created else 200)

    @bp.get("/api/workspaces/<workspace_id>/patches/<proposal_id>")
    @api_error_boundary("workspace_runtime_unavailable")
    def inspect_workspace_patch(workspace_id, proposal_id):
        return make_ok(project_patches.inspect(require_authenticated_user_id(), workspace_id, proposal_id))

    @bp.post("/api/workspaces/<workspace_id>/patches/<proposal_id>/apply")
    @rate_limit(mutations, "workspace_rate_limited")
    @api_error_boundary("workspace_runtime_unavailable")
    def apply_workspace_patch(workspace_id, proposal_id):
        return make_ok(project_patches.apply(require_authenticated_user_id(), workspace_id, proposal_id))

    @bp.get("/api/workspaces/<workspace_id>/files/<file_id>")
    @api_error_boundary("workspace_runtime_unavailable")
    def download_workspace_file(workspace_id, file_id):
        owner = require_authenticated_user_id()
        row = project_resources.owned_file(owner, workspace_id, file_id)
        path = project_resources.resource_path(row.storage_name)
        if path is None:
            raise project_resources.resource_error("workspace_file_not_found", 404)
        response = send_file(
            path, as_attachment=True, download_name=PurePosixPath(row.original_name).name, mimetype=row.mime_type
        )
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @bp.delete("/api/workspaces/<workspace_id>/files/<file_id>")
    @rate_limit(mutations, "workspace_rate_limited")
    @api_error_boundary("workspace_runtime_unavailable")
    def delete_workspace_file(workspace_id, file_id):
        owner = require_authenticated_user_id()
        _workspace(owner, workspace_id)
        row = project_resources.owned_file(owner, workspace_id, file_id)
        storage = row.storage_name
        db.session.delete(row)
        db.session.commit()
        project_resources.remove_uploads([storage])
        return make_ok({"deleted": True})

    @bp.delete("/api/workspaces/<workspace_id>")
    @rate_limit(mutations, "workspace_rate_limited")
    @api_error_boundary("workspace_runtime_unavailable")
    def delete_remind_workspace(workspace_id):
        owner = require_authenticated_user_id()
        row = _workspace(owner, workspace_id)
        files = [item.storage_name for item in project_resources.workspace_files(row.id)]
        ReMindWorkspaceFile.query.filter_by(workspace_id=row.id).delete(synchronize_session=False)
        AgentSkill.query.filter_by(user_id=owner, workspace_id=row.id).delete()
        WorkspacePatchProposal.query.filter_by(user_id=owner, workspace_id=row.id).delete()
        UserChatHistory.query.filter_by(user_id=owner, workspace_id=row.id).update(
            {UserChatHistory.workspace_id: None}
        )
        db.session.delete(row)
        db.session.commit()
        project_resources.remove_uploads(files)
        return make_ok({"deleted": True})

    @bp.post("/api/workspaces/<workspace_id>/chats")
    @rate_limit(mutations, "workspace_rate_limited")
    @api_error_boundary("workspace_runtime_unavailable")
    def create_workspace_chat(workspace_id):
        owner = require_authenticated_user_id()
        row = _workspace(owner, workspace_id)
        chat = UserChatHistory(
            user_id=owner, session_id=uuid4().hex, workspace_id=row.id, title=_name("title", 120)
        )
        db.session.add(chat)
        db.session.commit()
        return make_ok({"session_id": chat.session_id, "workspace_id": row.id}, 201)

    @bp.put("/api/workspaces/chats/<session_id>")
    @rate_limit(mutations, "workspace_rate_limited")
    @api_error_boundary("workspace_runtime_unavailable")
    def move_workspace_chat(session_id):
        owner = require_authenticated_user_id()
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or "workspace_id" not in data:
            raise ApiError("invalid_workspace", status=400, code="invalid_workspace")
        workspace_id = data["workspace_id"]
        if workspace_id is not None:
            if not isinstance(workspace_id, str):
                raise ApiError("invalid_workspace", status=400, code="invalid_workspace")
            _workspace(owner, workspace_id)
        chat = UserChatHistory.query.filter_by(user_id=owner, session_id=session_id).first()
        if chat is None:
            raise ApiError("session_not_found", status=404, code="session_not_found")
        chat.workspace_id = workspace_id
        db.session.commit()
        return make_ok({"session_id": session_id, "workspace_id": workspace_id})
