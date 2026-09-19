from __future__ import annotations

import logging
from typing import Any

from config import GITHUB_AGENT_MAX_FILE_CHARS
from services.github_app import (
    GitHubAgentService,
    GitHubAPIError,
    parse_repo_full_name,
)
from services.image_tools import crop_image, tile_image
from services.python_runner import (
    execute_python,
)
from services.tool_protocol import ModelToolResult
from services.web_search import public_sources, run_web_search

logger = logging.getLogger(__name__)

MAX_GITHUB_REPOSITORIES = 100
MAX_GITHUB_TREE_PATHS = 600


def execute_model_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    user_id: int | None,
    input_files: Any = None,
    allow_artifacts: bool = True,
) -> ModelToolResult:
    if name == "web_search":
        return _execute_web_search(arguments)
    if name == "github_list_repositories":
        return _execute_github_list_repositories(user_id)
    if name == "github_get_repository_map":
        return _execute_github_repository_map(user_id, arguments)
    if name == "github_read_file":
        return _execute_github_read_file(user_id, arguments)
    if name == "python_execute":
        return _execute_python(user_id, arguments, input_files, allow_artifacts)
    if name == "image_crop":
        result = crop_image(
            arguments,
            input_files=input_files,
            allow_artifacts=allow_artifacts,
            user_id=user_id,
        )
        events = [{"python_artifacts": result.artifacts}] if result.artifacts else []
        return ModelToolResult(
            {**result.output, "artifacts": result.artifacts},
            events=events,
            model_artifacts=result.model_artifacts,
            reusable_files=result.reusable_files,
        )
    if name == "image_tile":
        result = tile_image(arguments, input_files=input_files, user_id=user_id)
        return ModelToolResult(
            result.output,
            model_artifacts=result.model_artifacts,
        )
    return ModelToolResult({"ok": False, "error": "unknown_tool"})


def _execute_python(
    user_id: int | None,
    arguments: dict[str, Any],
    input_files: Any,
    allow_artifacts: bool,
) -> ModelToolResult:
    result = execute_python(
        arguments.get("code"),
        user_id=user_id,
        input_files=input_files,
        allow_artifacts=allow_artifacts,
        include_model_artifacts=True,
    )
    events = [{"python_artifacts": result.artifacts}] if result.artifacts else []
    return ModelToolResult(
        result.output,
        events=events,
        model_artifacts=result.model_artifacts,
        reusable_files=result.reusable_files,
    )


def _execute_web_search(arguments: dict[str, Any]) -> ModelToolResult:
    query = str(arguments.get("query") or "").strip()[:500]
    if not query:
        return ModelToolResult({"ok": False, "error": "invalid_query"})

    events: list[dict[str, Any]] = [
        {"status": "web_search_started", "query": query},
        {"status": "web_search_fetching", "query": query},
    ]
    try:
        payload = run_web_search(query)
    except Exception:
        logger.exception("Model-requested web search failed")
        events.append({"status": "web_search_failed", "query": query})
        return ModelToolResult(
            {"ok": False, "error": "web_search_failed", "query": query}, events=events
        )

    sources = public_sources(payload)
    events.append(
        {
            "status": "web_search_done" if sources else "web_search_no_results",
            "query": query,
            "sources": sources,
        }
    )
    return ModelToolResult(
        {
            "ok": True,
            "query": query,
            "context": str(payload.get("context") or ""),
        },
        events=events,
        sources=sources,
    )


def _github_installations(user_id: int | None) -> list[Any]:
    if user_id is None:
        return []
    try:
        from utils.auth import GitHubInstallation

        return (
            GitHubInstallation.query.filter_by(user_id=int(user_id))
            .order_by(GitHubInstallation.updated_at.desc(), GitHubInstallation.id.desc())
            .all()
        )
    except Exception:
        logger.exception("Failed to load GitHub installations for model tools")
        return []


def _repository_service(
    user_id: int | None, repo_full_name: str
) -> tuple[GitHubAgentService, dict[str, Any]]:
    if not repo_full_name or len(repo_full_name) > 240:
        raise ValueError("invalid_repository")
    parse_repo_full_name(repo_full_name)
    for installation in _github_installations(user_id):
        service = GitHubAgentService(int(installation.installation_id))
        repositories = service.list_repositories()
        for repository in repositories:
            if str(repository.get("full_name") or "").lower() == repo_full_name.lower():
                return service, repository
    raise ValueError("repository_not_connected")


def _execute_github_list_repositories(user_id: int | None) -> ModelToolResult:
    repositories: list[dict[str, Any]] = []
    try:
        for installation in _github_installations(user_id):
            service = GitHubAgentService(int(installation.installation_id))
            for repository in service.list_repositories():
                repositories.append(
                    {
                        **repository,
                        "installation_id": int(installation.installation_id),
                        "account_login": installation.account_login,
                    }
                )
                if len(repositories) >= MAX_GITHUB_REPOSITORIES:
                    break
            if len(repositories) >= MAX_GITHUB_REPOSITORIES:
                break
    except (GitHubAPIError, ValueError):
        logger.exception("Model-requested GitHub repository listing failed")
        return ModelToolResult({"ok": False, "error": "github_request_failed"})

    return ModelToolResult(
        {
            "ok": True,
            "repositories": repositories,
            "truncated": len(repositories) >= MAX_GITHUB_REPOSITORIES,
        }
    )


def _execute_github_repository_map(
    user_id: int | None, arguments: dict[str, Any]
) -> ModelToolResult:
    repo_full_name = str(arguments.get("repo_full_name") or "").strip()
    try:
        branch = _bounded_ref(arguments.get("branch"))
        service, _repository = _repository_service(user_id, repo_full_name)
        repo_map = service.load_repo_map(repo_full_name, branch)
    except (GitHubAPIError, ValueError):
        logger.exception("Model-requested GitHub repository map failed")
        return ModelToolResult({"ok": False, "error": "github_repository_unavailable"})

    paths = [
        item for item in repo_map.get("flat", []) if isinstance(item, dict) and item.get("path")
    ]
    return ModelToolResult(
        {
            "ok": True,
            "repository": repo_map.get("repository"),
            "base_branch": repo_map.get("base_branch"),
            "stats": repo_map.get("stats"),
            "paths": paths[:MAX_GITHUB_TREE_PATHS],
            "truncated": bool(repo_map.get("truncated")) or len(paths) > MAX_GITHUB_TREE_PATHS,
        }
    )


def _execute_github_read_file(user_id: int | None, arguments: dict[str, Any]) -> ModelToolResult:
    repo_full_name = str(arguments.get("repo_full_name") or "").strip()
    raw_path = str(arguments.get("path") or "").strip()
    try:
        requested_ref = _bounded_ref(arguments.get("ref"))
        service, repository = _repository_service(user_id, repo_full_name)
        owner, repo = parse_repo_full_name(repo_full_name)
        path = _safe_github_read_path(raw_path)
        ref = requested_ref or str(repository.get("default_branch") or "main")
        payload = service.client.get_text_file(owner, repo, path, ref)
    except (GitHubAPIError, ValueError):
        logger.exception("Model-requested GitHub file read failed")
        return ModelToolResult({"ok": False, "error": "github_file_unavailable"})

    content = str(payload.get("content") or "")
    return ModelToolResult(
        {
            "ok": True,
            "repository": repo_full_name,
            "ref": ref,
            "path": path,
            "size": payload.get("size"),
            "content": content[:GITHUB_AGENT_MAX_FILE_CHARS],
            "truncated": len(content) > GITHUB_AGENT_MAX_FILE_CHARS,
        }
    )


def _safe_github_read_path(raw_path: str) -> str:
    from services.github_app import _is_sensitive_or_protected_path, _normalize_path

    if not raw_path or len(raw_path) > 1024:
        raise ValueError("invalid_path")
    path = _normalize_path(raw_path)
    if _is_sensitive_or_protected_path(path):
        raise ValueError("sensitive_path_blocked")
    return path


def _bounded_ref(value: Any) -> str | None:
    ref = str(value or "").strip()
    if not ref:
        return None
    if len(ref) > 255 or any(ord(character) < 32 for character in ref):
        raise ValueError("invalid_ref")
    return ref
