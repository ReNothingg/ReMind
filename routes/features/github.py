from __future__ import annotations

import secrets
from datetime import datetime
from urllib.parse import urlencode

from flask import redirect, request, session, url_for

from config import GITHUB_APP_SLUG, GITHUB_PUBLIC_BASE_URL
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
    verify_user_can_access_installation,
)
from services.github_oauth_flow import GitHubOAuthFlowError, GitHubOAuthFlowStore
from utils.auth import GitHubAgentTask, GitHubInstallation, db
from utils.responses import make_ok

GITHUB_OAUTH_FLOW_SESSION_KEY = "github_oauth_flow_id"
_LEGACY_GITHUB_OAUTH_SESSION_KEYS = (
    "github_oauth_state",
    "github_oauth_after",
    "github_user_token",
    "github_pending_installation_id",
)


def _github_external_url(endpoint: str, **values) -> str:
    if GITHUB_PUBLIC_BASE_URL:
        return f"{GITHUB_PUBLIC_BASE_URL}{url_for(endpoint, **values)}"
    return url_for(endpoint, _external=True, **values)


def _github_frontend_redirect(**params):
    query = urlencode({key: value for key, value in params.items() if value})
    target = "/github"
    if query:
        target = f"{target}?{query}"
    return redirect(target, code=303)


def _require_authenticated_redirect():
    if "user_id" not in session:
        return redirect("/?auth=login", code=303)
    return None


def _clear_legacy_github_oauth_session() -> None:
    for key in _LEGACY_GITHUB_OAUTH_SESSION_KEYS:
        session.pop(key, None)


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


def _github_connection_payload(user_id: int, selected_installation_id: int | None = None) -> dict:
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

    return {
        "configured": not missing,
        "missing_config": missing,
        "app": {
            "name": GITHUB_APP_SLUG or "GitHub App",
            "slug": GITHUB_APP_SLUG,
            "page_url": build_github_app_page_url(),
            "install_url": build_github_app_install_url(),
        },
        "installations": [installation.to_dict() for installation in installations],
        "selected_installation_id": int(selected.installation_id) if selected else None,
        "repositories": [],
        "connection_error": None,
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


def _start_github_oauth(
    user_id: int,
    *,
    after: str = "",
    pending_installation_id: int | None = None,
):
    _clear_legacy_github_oauth_session()
    try:
        oauth_start = GitHubOAuthFlowStore.from_config().start(
            user_id,
            after=after,
            pending_installation_id=pending_installation_id,
        )
    except GitHubOAuthFlowError:
        return _github_frontend_redirect(github_error="oauth_storage")

    session.pop(GITHUB_OAUTH_FLOW_SESSION_KEY, None)
    callback_url = _github_external_url("api.github_oauth_callback")
    return redirect(build_github_oauth_url(callback_url, oauth_start.state, after=after))


def register_github_routes(api_bp):
    @api_bp.route("/auth/github/login", methods=["GET"])
    @api_error_boundary("github_oauth_login_failed")
    def github_oauth_login():
        redirect_response = _require_authenticated_redirect()
        if redirect_response:
            return redirect_response
        if not github_app_configured():
            return _github_frontend_redirect(github_error="config")

        after = (request.args.get("after") or "").strip()
        return _start_github_oauth(
            require_authenticated_user_id(),
            after="install" if after == "install" else "",
        )

    @api_bp.route("/auth/github/callback", methods=["GET"])
    @api_error_boundary("github_oauth_callback_failed")
    def github_oauth_callback():
        redirect_response = _require_authenticated_redirect()
        if redirect_response:
            return redirect_response
        if not github_app_configured():
            return _github_frontend_redirect(github_error="config")

        actual_state = (request.args.get("state") or "").strip()
        code = (request.args.get("code") or "").strip()
        if not code:
            return _github_frontend_redirect(github_error="code")
        db_user_id = require_authenticated_user_id()
        _clear_legacy_github_oauth_session()
        try:
            oauth_store = GitHubOAuthFlowStore.from_config()
            oauth_state = oauth_store.consume_state(actual_state, db_user_id)
        except GitHubOAuthFlowError:
            return _github_frontend_redirect(github_error="oauth_storage")
        if not oauth_state:
            return _github_frontend_redirect(github_error="state")

        callback_url = _github_external_url("api.github_oauth_callback")
        user_token = exchange_github_oauth_code(code, callback_url)
        if oauth_state.pending_installation_id:
            shaped = verify_user_can_access_installation(
                user_token, oauth_state.pending_installation_id
            )
            _save_installation(db_user_id, shaped)
            session.pop(GITHUB_OAUTH_FLOW_SESSION_KEY, None)
            return _github_frontend_redirect(github="connected")

        if oauth_state.after == "install":
            try:
                oauth_store.store_credential(oauth_state.flow_id, db_user_id, user_token)
            except GitHubOAuthFlowError:
                return _github_frontend_redirect(github_error="oauth_storage")
            session[GITHUB_OAUTH_FLOW_SESSION_KEY] = oauth_state.flow_id
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
        db_user_id = require_authenticated_user_id()
        _clear_legacy_github_oauth_session()
        flow_id = session.get(GITHUB_OAUTH_FLOW_SESSION_KEY)
        try:
            has_credential = GitHubOAuthFlowStore.from_config().has_credential(flow_id, db_user_id)
        except GitHubOAuthFlowError:
            return _github_frontend_redirect(github_error="oauth_storage")
        if not has_credential:
            return _start_github_oauth(db_user_id, after="install")
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

        db_user_id = require_authenticated_user_id()
        _clear_legacy_github_oauth_session()
        flow_id = session.pop(GITHUB_OAUTH_FLOW_SESSION_KEY, None)
        try:
            user_token = GitHubOAuthFlowStore.from_config().consume_credential(flow_id, db_user_id)
        except GitHubOAuthFlowError:
            return _github_frontend_redirect(github_error="oauth_storage")
        if not user_token:
            return _start_github_oauth(
                db_user_id,
                after="setup",
                pending_installation_id=installation_id,
            )

        shaped = verify_user_can_access_installation(user_token, installation_id)
        _save_installation(db_user_id, shaped)
        return _github_frontend_redirect(github="connected")

    @api_bp.route("/api/github/connection", methods=["GET"])
    @api_bp.route("/api/github/status", methods=["GET"])
    @api_error_boundary("github_connection_failed")
    def github_connection():
        _clear_legacy_github_oauth_session()
        db_user_id = require_authenticated_user_id()
        selected_installation_id = request.args.get("installation_id", type=int)
        return make_ok(_github_connection_payload(db_user_id, selected_installation_id))

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
        flow_id = session.pop(GITHUB_OAUTH_FLOW_SESSION_KEY, None)
        _clear_legacy_github_oauth_session()
        try:
            GitHubOAuthFlowStore.from_config().discard_credential(flow_id)
        except GitHubOAuthFlowError:
            pass
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
        if task.status in {"pull_request_opened", "completed_no_changes"}:
            return make_ok({"task": task.to_dict()})
        if task.status == "error":
            raise ApiError(
                "A failed GitHub task cannot be retried safely. Create and review a new plan.",
                status=409,
                code="github_task_retry_requires_new_plan",
            )
        _installation_for_user(db_user_id, int(task.installation_id))
        if task.status != "planned":
            raise ApiError(
                "Task cannot be run from its current state", status=409, code="invalid_task_state"
            )

        claimed_at = datetime.utcnow()
        claimed = GitHubAgentTask.query.filter_by(
            user_id=db_user_id,
            public_id=task_id,
            status="planned",
        ).update(
            {
                "status": "running",
                "error": None,
                "updated_at": claimed_at,
            },
            synchronize_session=False,
        )
        db.session.commit()
        db.session.expire_all()
        task = _task_for_user(db_user_id, task_id)
        if claimed != 1:
            if task.status in {"pull_request_opened", "completed_no_changes"}:
                return make_ok({"task": task.to_dict()})
            raise ApiError(
                "Task cannot be run from its current state", status=409, code="invalid_task_state"
            )

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
            if any(item.get("code") == "approvedPlanStale" for item in exc.activity):
                raise ApiError(str(exc), status=409, code="github_approved_plan_stale") from exc
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
