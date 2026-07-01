from __future__ import annotations

import secrets
from datetime import datetime
from urllib.parse import urlencode

from flask import redirect, request, session, url_for

from config import GITHUB_PUBLIC_BASE_URL
from routes.api_errors import ApiError, api_error_boundary, require_authenticated_user_id
from services.github_app import (
    GitHubAgentExecutionError,
    GitHubAgentService,
    GitHubAPIError,
    build_github_app_install_url,
    build_github_app_page_url,
    build_github_oauth_url,
    exchange_github_oauth_code,
    github_app_configured,
    github_app_missing_fields,
    load_github_app_metadata,
    verify_user_can_access_installation,
)
from utils.auth import GitHubAgentTask, GitHubInstallation, db
from utils.responses import make_ok

GITHUB_OAUTH_STATE_KEY = "github_oauth_state"
GITHUB_OAUTH_AFTER_KEY = "github_oauth_after"
GITHUB_USER_TOKEN_KEY = "github_user_token"
GITHUB_PENDING_INSTALLATION_KEY = "github_pending_installation_id"


def _github_external_url(endpoint: str, **values) -> str:
    if GITHUB_PUBLIC_BASE_URL:
        return f"{GITHUB_PUBLIC_BASE_URL}{url_for(endpoint, **values)}"
    return url_for(endpoint, _external=True, **values)


def _github_frontend_redirect(**params):
    query = urlencode({key: value for key, value in params.items() if value})
    target = "/"
    if query:
        target = f"{target}?{query}"
    target = f"{target}#settings/account"
    return redirect(target, code=303)


def _require_authenticated_redirect():
    if "user_id" not in session:
        return redirect("/?auth=login", code=303)
    return None


def _github_api_error(exc: GitHubAPIError) -> ApiError:
    if exc.status_code == 401:
        return ApiError(
            "GitHub rejected the current credentials. Reconnect GitHub and try again.",
            status=401,
            code="github_auth_failed",
        )
    if exc.status_code == 403:
        return ApiError(exc.message, status=403, code="github_access_denied")
    if exc.status_code == 404:
        return ApiError(exc.message, status=404, code="github_not_found")
    return ApiError(exc.message, status=502, code="github_api_failed")


def _installation_for_user(user_id: int, installation_id: int) -> GitHubInstallation:
    installation = GitHubInstallation.query.filter_by(
        user_id=user_id,
        installation_id=int(installation_id),
    ).first()
    if not installation:
        raise ApiError(
            "GitHub installation not found", status=404, code="github_installation_not_found"
        )
    return installation


def _save_installation(user_id: int, shaped: dict) -> GitHubInstallation:
    installation = GitHubInstallation.query.filter_by(
        user_id=user_id,
        installation_id=int(shaped["installation_id"]),
    ).first()
    if not installation:
        installation = GitHubInstallation(
            user_id=user_id,
            installation_id=int(shaped["installation_id"]),
            account_login=shaped.get("account_login") or "GitHub",
        )
        db.session.add(installation)

    installation.account_login = shaped.get("account_login") or installation.account_login
    installation.account_html_url = shaped.get("account_html_url") or None
    installation.account_avatar_url = shaped.get("account_avatar_url") or None
    installation.target_type = shaped.get("target_type") or None
    installation.repository_selection = shaped.get("repository_selection") or None
    installation.set_permissions(shaped.get("permissions") or {})
    installation.updated_at = datetime.utcnow()
    db.session.commit()
    return installation


def _task_for_user(user_id: int, task_id: str) -> GitHubAgentTask:
    task = GitHubAgentTask.query.filter_by(user_id=user_id, public_id=task_id).first()
    if not task:
        raise ApiError("GitHub task not found", status=404, code="github_task_not_found")
    return task


def _new_task_public_id() -> str:
    return f"gh_{secrets.token_urlsafe(18)}"


def _github_status_payload(user_id: int, selected_installation_id: int | None = None) -> dict:
    missing = github_app_missing_fields()
    installations = (
        GitHubInstallation.query.filter_by(user_id=user_id)
        .order_by(GitHubInstallation.updated_at.desc(), GitHubInstallation.id.desc())
        .all()
    )
    selected = None
    if selected_installation_id is not None:
        selected = next(
            (
                item
                for item in installations
                if int(item.installation_id) == int(selected_installation_id)
            ),
            None,
        )
    if selected is None and installations:
        selected = installations[0]

    repositories = []
    connection_error = None
    if selected and not missing:
        try:
            repositories = GitHubAgentService(int(selected.installation_id)).list_repositories()
        except GitHubAPIError as exc:
            connection_error = _github_api_error(exc).message
        except Exception as exc:
            connection_error = str(exc)

    return {
        "configured": not missing,
        "missing_config": missing,
        "app": load_github_app_metadata(),
        "installations": [installation.to_dict() for installation in installations],
        "selected_installation_id": int(selected.installation_id) if selected else None,
        "repositories": repositories,
        "connection_error": connection_error,
        "urls": {
            "connect": url_for("api.github_oauth_login", after="install"),
            "install": url_for("api.github_install"),
            "disconnect": url_for("api.github_disconnect"),
            "app_page": build_github_app_page_url(),
            "install_page": build_github_app_install_url(),
            "callback": _github_external_url("api.github_oauth_callback"),
            "setup": _github_external_url("api.github_setup"),
        },
    }


def register_github_routes(api_bp):
    @api_bp.route("/auth/github/login", methods=["GET"])
    @api_error_boundary("github_oauth_login_failed")
    def github_oauth_login():
        redirect_response = _require_authenticated_redirect()
        if redirect_response:
            return redirect_response
        if not github_app_configured():
            return _github_frontend_redirect(github_error="config")

        state = secrets.token_urlsafe(24)
        session[GITHUB_OAUTH_STATE_KEY] = state
        after = (request.args.get("after") or "").strip()
        if after:
            session[GITHUB_OAUTH_AFTER_KEY] = after

        callback_url = _github_external_url("api.github_oauth_callback")
        return redirect(build_github_oauth_url(callback_url, state, after=after))

    @api_bp.route("/auth/github/callback", methods=["GET"])
    @api_error_boundary("github_oauth_callback_failed")
    def github_oauth_callback():
        redirect_response = _require_authenticated_redirect()
        if redirect_response:
            return redirect_response
        if not github_app_configured():
            return _github_frontend_redirect(github_error="config")

        expected_state = session.get(GITHUB_OAUTH_STATE_KEY)
        actual_state = (request.args.get("state") or "").strip()
        code = (request.args.get("code") or "").strip()
        if not expected_state or not actual_state or actual_state != expected_state:
            return _github_frontend_redirect(github_error="state")
        if not code:
            return _github_frontend_redirect(github_error="code")

        callback_url = _github_external_url("api.github_oauth_callback")
        user_token = exchange_github_oauth_code(code, callback_url)
        session[GITHUB_USER_TOKEN_KEY] = user_token
        session.pop(GITHUB_OAUTH_STATE_KEY, None)

        db_user_id = require_authenticated_user_id()
        pending_installation_id = session.pop(GITHUB_PENDING_INSTALLATION_KEY, None)
        if pending_installation_id:
            shaped = verify_user_can_access_installation(user_token, int(pending_installation_id))
            _save_installation(db_user_id, shaped)
            return _github_frontend_redirect(github="connected")

        after = session.pop(GITHUB_OAUTH_AFTER_KEY, None)
        if after == "install":
            return redirect(build_github_app_install_url())

        return _github_frontend_redirect(github="authorized")

    @api_bp.route("/auth/github/install", methods=["GET"])
    @api_error_boundary("github_install_failed")
    def github_install():
        redirect_response = _require_authenticated_redirect()
        if redirect_response:
            return redirect_response
        if not github_app_configured():
            return _github_frontend_redirect(github_error="config")
        if not session.get(GITHUB_USER_TOKEN_KEY):
            return redirect(url_for("api.github_oauth_login", after="install"))
        return redirect(build_github_app_install_url())

    @api_bp.route("/auth/github/setup", methods=["GET"])
    @api_error_boundary("github_setup_failed")
    def github_setup():
        redirect_response = _require_authenticated_redirect()
        if redirect_response:
            return redirect_response
        if not github_app_configured():
            return _github_frontend_redirect(github_error="config")

        installation_id = request.args.get("installation_id", type=int)
        if not installation_id:
            return _github_frontend_redirect(github_error="installation")

        user_token = session.get(GITHUB_USER_TOKEN_KEY)
        if not user_token:
            session[GITHUB_PENDING_INSTALLATION_KEY] = installation_id
            return redirect(url_for("api.github_oauth_login", after="setup"))

        db_user_id = require_authenticated_user_id()
        shaped = verify_user_can_access_installation(user_token, installation_id)
        _save_installation(db_user_id, shaped)
        return _github_frontend_redirect(github="connected")

    @api_bp.route("/api/github/status", methods=["GET"])
    @api_error_boundary("github_status_failed")
    def github_status():
        db_user_id = require_authenticated_user_id()
        selected_installation_id = request.args.get("installation_id", type=int)
        return make_ok(_github_status_payload(db_user_id, selected_installation_id))

    @api_bp.route("/api/github/disconnect", methods=["POST"])
    @api_error_boundary("github_disconnect_failed")
    def github_disconnect():
        db_user_id = require_authenticated_user_id()
        payload = request.get_json(silent=True) or {}
        installation_id = payload.get("installation_id")
        query = GitHubInstallation.query.filter_by(user_id=db_user_id)
        if installation_id is not None:
            query = query.filter_by(installation_id=int(installation_id))
        deleted = query.delete(synchronize_session=False)
        db.session.commit()
        if installation_id is None:
            session.pop(GITHUB_USER_TOKEN_KEY, None)
        return make_ok({"deleted": deleted})

    @api_bp.route("/api/github/repositories", methods=["GET"])
    @api_error_boundary("github_repositories_failed")
    def github_repositories():
        db_user_id = require_authenticated_user_id()
        installation_id = request.args.get("installation_id", type=int)
        if not installation_id:
            raise ApiError(
                "installation_id is required", status=400, code="missing_installation_id"
            )
        _installation_for_user(db_user_id, installation_id)
        try:
            repositories = GitHubAgentService(installation_id).list_repositories()
        except GitHubAPIError as exc:
            raise _github_api_error(exc) from exc
        return make_ok({"repositories": repositories})

    @api_bp.route("/api/github/repo-map", methods=["POST"])
    @api_error_boundary("github_repo_map_failed")
    def github_repo_map():
        db_user_id = require_authenticated_user_id()
        payload = request.get_json(silent=True) or {}
        installation_id = payload.get("installation_id")
        repo_full_name = str(payload.get("repo_full_name") or "").strip()
        base_branch = str(payload.get("base_branch") or "").strip() or None
        if not installation_id or not repo_full_name:
            raise ApiError(
                "installation_id and repo_full_name are required",
                status=400,
                code="invalid_github_payload",
            )
        _installation_for_user(db_user_id, int(installation_id))
        try:
            repo_map = GitHubAgentService(int(installation_id)).load_repo_map(
                repo_full_name, base_branch
            )
        except GitHubAPIError as exc:
            raise _github_api_error(exc) from exc
        return make_ok(
            {
                "repository": repo_map["repository"],
                "base_branch": repo_map["base_branch"],
                "tree": repo_map["tree"],
                "tree_stats": repo_map["stats"],
                "truncated": repo_map["truncated"],
                "tree_source": repo_map["source"],
            }
        )

    @api_bp.route("/api/github/agent/plan", methods=["POST"])
    @api_error_boundary("github_agent_plan_failed")
    def github_agent_plan():
        db_user_id = require_authenticated_user_id()
        payload = request.get_json(silent=True) or {}
        installation_id = payload.get("installation_id")
        repo_full_name = str(payload.get("repo_full_name") or "").strip()
        base_branch = str(payload.get("base_branch") or "").strip()
        task_text = str(payload.get("task") or "").strip()
        if not installation_id or not repo_full_name or not base_branch or not task_text:
            raise ApiError(
                "installation_id, repo_full_name, base_branch and task are required",
                status=400,
                code="invalid_github_payload",
            )
        if len(task_text) > 4000:
            raise ApiError("Task is too long", status=400, code="github_task_too_long")

        _installation_for_user(db_user_id, int(installation_id))
        task = GitHubAgentTask(
            public_id=_new_task_public_id(),
            user_id=db_user_id,
            installation_id=int(installation_id),
            repo_full_name=repo_full_name,
            base_branch=base_branch,
            task=task_text,
            status="planning",
        )
        db.session.add(task)
        db.session.commit()

        try:
            plan = GitHubAgentService(int(installation_id)).plan(
                repo_full_name, base_branch, task_text
            )
            task.set_plan(plan)
            task.status = "planned"
            task.updated_at = datetime.utcnow()
            db.session.commit()
        except GitHubAPIError as exc:
            db.session.rollback()
            task.status = "error"
            task.error = _github_api_error(exc).message
            db.session.commit()
            raise _github_api_error(exc) from exc
        except Exception as exc:
            db.session.rollback()
            task.status = "error"
            task.error = str(exc)
            db.session.commit()
            raise

        return make_ok({"task": task.to_dict()})

    @api_bp.route("/api/github/agent/run", methods=["POST"])
    @api_error_boundary("github_agent_run_failed")
    def github_agent_run():
        db_user_id = require_authenticated_user_id()
        payload = request.get_json(silent=True) or {}
        task_id = str(payload.get("task_id") or "").strip()
        if not task_id:
            raise ApiError("task_id is required", status=400, code="missing_task_id")

        task = _task_for_user(db_user_id, task_id)
        _installation_for_user(db_user_id, int(task.installation_id))
        if task.status not in {"planned", "error"}:
            raise ApiError(
                "Task cannot be run from its current state", status=409, code="invalid_task_state"
            )

        task.status = "running"
        task.error = None
        task.updated_at = datetime.utcnow()
        db.session.commit()

        try:
            result = GitHubAgentService(int(task.installation_id)).run(
                repo_full_name=task.repo_full_name,
                base_branch=task.base_branch,
                task=task.task,
                plan=task.get_plan(),
            )
            task.set_edits(result["edits"])
            if result.get("no_changes"):
                task.branch_name = None
                task.diff = None
                task.pull_request_number = None
                task.pull_request_url = None
                task.status = "completed_no_changes"
            else:
                task.branch_name = result["branch_name"]
                task.diff = result["diff"]
                task.pull_request_number = result["pull_request"]["number"]
                task.pull_request_url = result["pull_request"]["url"]
                task.status = "pull_request_opened"
            task.updated_at = datetime.utcnow()
            db.session.commit()
        except GitHubAPIError as exc:
            db.session.rollback()
            task.status = "error"
            task.error = _github_api_error(exc).message
            task.updated_at = datetime.utcnow()
            db.session.commit()
            raise _github_api_error(exc) from exc
        except GitHubAgentExecutionError as exc:
            db.session.rollback()
            task.status = "error"
            task.error = str(exc)
            task.set_edits({"activity": exc.activity})
            task.updated_at = datetime.utcnow()
            db.session.commit()
            raise
        except Exception as exc:
            db.session.rollback()
            task.status = "error"
            task.error = str(exc)
            task.updated_at = datetime.utcnow()
            db.session.commit()
            raise

        return make_ok({"task": task.to_dict()})

    @api_bp.route("/api/github/tasks/<task_id>", methods=["GET"])
    @api_error_boundary("github_task_failed")
    def github_task(task_id):
        db_user_id = require_authenticated_user_id()
        task = _task_for_user(db_user_id, task_id)
        return make_ok({"task": task.to_dict()})
