from __future__ import annotations

import json
import re
import secrets
from datetime import datetime
from difflib import get_close_matches
from typing import Any, cast

from services.github_app import (
    GitHubAgentExecutionError,
    GitHubAgentService,
    GitHubAPIError,
    github_app_configured,
    github_app_missing_fields,
)
from services.ai_provider import generate_json
from utils.auth import GitHubAgentTask, GitHubInstallation, db

TASK_ID_RE = re.compile(r"(?<![A-Za-z0-9_-])(gh_[A-Za-z0-9_-]{12,})(?![A-Za-z0-9_-])")
REPO_FULL_NAME_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?![A-Za-z0-9_.-])"
)
BASE_BRANCH_RE = re.compile(
    r"(?:base(?:\s+branch)?|branch|ветк[аиу]|базов(?:ая|ую)\s+ветк[аиу])"
    r"\s*[:=]?\s*[`'\"]?([A-Za-z0-9._/-]{1,120})",
    re.IGNORECASE,
)
AI_ROUTER_CONFIDENCE_THRESHOLD = 0.55

GITHUB_TERMS = (
    "github",
    "git hub",
    "гитхаб",
    "гитхаба",
    "гита",
    "repo",
    "repository",
    "repositories",
    "репо",
    "репозитор",
    "pull request",
    "pr",
    "пулл реквест",
    "пул реквест",
)


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


INFO_TERMS = (
    "access",
    "available",
    "connected",
    "profile",
    "account",
    "username",
    "repositories",
    "repos",
    "list",
    "show",
    "tell",
    "look",
    "посмотри",
    "скажи",
    "расскажи",
    "доступ",
    "подключ",
    "профиль",
    "аккаунт",
    "репозитории",
    "репозиториях",
    "репы",
    "список",
)
CONTEXT_TERMS = (
    "there",
    "that repo",
    "this repo",
    "that project",
    "this project",
    "same repo",
    "same repository",
    "там",
    "туда",
    "в нем",
    "в ней",
    "в проекте",
    "в репо",
    "в репозитории",
    "моем репо",
    "моем репозитории",
    "моем гитхаб проекте",
    "этом репо",
    "этом репозитории",
)
FOLLOWUP_TERMS = (
    "code",
    "comments",
    "change",
    "changes",
    "fix it",
    "do it",
    "try again",
    "did not change",
    "didn't change",
    "код",
    "коде",
    "комментар",
    "правк",
    "изменени",
    "не внес",
    "не сделал",
    "не измени",
    "удали",
    "удалить",
    "убери",
    "убрать",
    "додел",
    "передел",
    "попробуй",
    "ну сделай",
    "давай",
)
RECENT_BRANCH_TERMS = (
    "these",
    "this pr",
    "last pr",
    "pull request",
    "comments",
    "just added",
    "эти",
    "этот pr",
    "этот pull request",
    "последн",
    "пулл реквест",
    "pull request",
    "комментар",
    "только что",
    "добавлен",
    "изменения",
)
CHANGE_SUMMARY_TERMS = (
    "what changed",
    "what did you change",
    "what changes",
    "what code changes",
    "show changes",
    "summarize changes",
    "какие изменения",
    "какие правки",
    "что изменил",
    "что изменилось",
    "что поменял",
    "что сделал",
    "что по коду",
    "изменения по коду",
    "расскажи",
)
RESULT_EXPLANATION_TERMS = (
    "what",
    "why",
    "what happened",
    "explain",
    "why no changes",
    "no changes",
    "чё",
    "че",
    "что",
    "почему",
    "что это",
    "что это значит",
    "объясни",
    "поясни",
    "не создан",
    "не создано",
    "нет изменений",
)
ACTION_TERMS = (
    "add",
    "change",
    "create",
    "delete",
    "edit",
    "fix",
    "implement",
    "localize",
    "refactor",
    "remove",
    "rename",
    "update",
    "bug",
    "bugs",
    "добав",
    "измени",
    "изменить",
    "поменяй",
    "поменять",
    "исправ",
    "найди",
    "найти",
    "созда",
    "сдела",
    "обнов",
    "удал",
    "локализ",
    "рефактор",
    "баг",
    "ошиб",
)
CONFIRM_TERMS = (
    "confirm",
    "confirmed",
    "approve",
    "run",
    "start",
    "create pr",
    "open pr",
    "подтверд",
    "запусти",
    "создай pr",
    "создай pull request",
    "открой pr",
    "открой pull request",
)


def handle_github_chat_message(
    user_id: int | None,
    message: str,
    history: list[Any] | None = None,
) -> dict[str, Any] | None:
    text = str(message or "").strip()
    if not text:
        return None

    history_items = history or []
    confirmation_task_id = _confirmation_task_id(text)
    route = None if confirmation_task_id else _classify_github_chat_route(text, history_items)
    if route:
        intent = route["intent"]
        effective_text = _effective_text_from_ai_route(text, route, history_items)
        summary_intent = intent == "summary"
        info_intent = intent == "info"
        task_intent = intent == "task"
    else:
        effective_text = _merge_recent_task_if_needed(text, history_items)
        summary_intent = _looks_like_recent_github_change_summary(effective_text, history_items)
        info_intent = _looks_like_github_info_request(effective_text, history_items)
        task_intent = _looks_like_github_task(effective_text, history_items)

    if not confirmation_task_id and not task_intent and not info_intent and not summary_intent:
        return None

    if not user_id:
        return {
            "reply": (
                "Чтобы работать с GitHub из чата, сначала войдите в аккаунт ReMind "
                "и подключите GitHub в настройках аккаунта."
            ),
            "github_tool": {"handled": True, "status": "auth_required"},
        }

    missing_config = github_app_missing_fields()
    if missing_config or not github_app_configured():
        return {
            "reply": (
                "GitHub App еще не настроен на сервере. Не хватает конфигурации: "
                + ", ".join(missing_config or ["GitHub App credentials"])
                + "."
            ),
            "github_tool": {"handled": True, "status": "config_missing"},
        }

    if confirmation_task_id:
        return _run_confirmed_task(user_id, confirmation_task_id)

    if summary_intent:
        summary = _handle_recent_github_change_summary(effective_text, history_items)
        if summary is not None:
            return summary

    installations = _load_installations(user_id)
    if not installations:
        return {
            "reply": (
                "GitHub пока не подключен. Откройте Настройки -> Аккаунт -> "
                "Подключенные приложения и подключите GitHub."
            ),
            "github_tool": {"handled": True, "status": "not_connected"},
        }

    if info_intent and not task_intent:
        return _handle_github_info_request(effective_text, history_items, installations)

    repo_result = _resolve_repo(user_id, effective_text, installations, history_items)
    if repo_result.get("reply"):
        return {
            "reply": repo_result["reply"],
            "github_tool": {"handled": True, "status": repo_result["status"]},
        }

    repo = repo_result["repo"]
    task_text = _extract_task_text(effective_text, repo["full_name"])
    if len(task_text) < 8:
        return {
            "reply": (
                f"Репозиторий `{repo['full_name']}` найден. Теперь напишите, "
                "какое изменение нужно сделать в коде."
            ),
            "github_tool": {"handled": True, "status": "task_required", "repo": repo},
        }

    return _create_plan_task(
        user_id=user_id,
        installation_id=int(repo["installation_id"]),
        repo_full_name=str(repo["full_name"]),
        base_branch=_resolve_base_branch(effective_text, repo, history_items),
        task_text=task_text,
    )


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    normalized = text.lower()
    return any(term in normalized for term in terms)


def _contains_result_explanation(text: str) -> bool:
    normalized = text.lower()
    for term in RESULT_EXPLANATION_TERMS:
        pattern = rf"(?<![A-Za-zА-Яа-яЁё0-9_]){re.escape(term)}(?![A-Za-zА-Яа-яЁё0-9_])"
        if re.search(pattern, normalized):
            return True
    return False


def _contains_github_reference(text: str) -> bool:
    normalized = text.lower()
    long_terms = tuple(term for term in GITHUB_TERMS if term != "pr")
    return _contains_any(normalized, long_terms) or bool(re.search(r"\bpr\b", normalized))


def _should_use_ai_router(text: str, history: list[Any]) -> bool:
    return bool(
        TASK_ID_RE.search(text)
        or REPO_FULL_NAME_RE.search(text)
        or _contains_github_reference(text)
        or _recent_github_repo_context(history)
        or _recent_github_task_context(history)
        or _recent_github_profile_context(history)
    )


def _classify_github_chat_route(text: str, history: list[Any]) -> dict[str, Any] | None:
    if not _should_use_ai_router(text, history):
        return None
    raw_route = generate_json(_build_github_route_prompt(text, history))
    if not isinstance(raw_route, dict):
        return None

    intent = str(raw_route.get("intent") or "none").strip().lower()
    if intent not in {"task", "info", "summary", "none"}:
        return None
    try:
        confidence = float(raw_route.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0
    if confidence < AI_ROUTER_CONFIDENCE_THRESHOLD:
        return None
    if intent == "none":
        return {"intent": "none", "confidence": confidence}

    repo_full_name = str(raw_route.get("repo_full_name") or "").strip()
    if repo_full_name and not REPO_FULL_NAME_RE.fullmatch(repo_full_name):
        repo_full_name = ""
    task_text = str(raw_route.get("task_text") or "").strip()
    return {
        "intent": intent,
        "confidence": confidence,
        "repo_full_name": repo_full_name,
        "task_text": task_text,
        "use_recent_repo": bool(raw_route.get("use_recent_repo")),
        "use_recent_task": bool(raw_route.get("use_recent_task")),
    }


def _build_github_route_prompt(text: str, history: list[Any]) -> str:
    recent_task = _recent_github_task_context(history)
    recent_repo = _recent_github_repo_context(history)
    recent_messages = []
    for item in history[-8:]:
        if not isinstance(item, dict):
            continue
        github_tool = _dict_or_empty(item.get("github_tool"))
        task = _dict_or_empty(github_tool.get("task"))
        recent_messages.append(
            {
                "role": item.get("role"),
                "text": _history_text(item)[:700],
                "github_tool": (
                    {
                        "status": github_tool.get("status"),
                        "repo_full_name": task.get("repo_full_name")
                        or github_tool.get("profile_login"),
                        "task_status": task.get("status"),
                        "task_id": task.get("id"),
                        "has_diff": bool(task.get("diff")),
                        "pull_request_url": task.get("pull_request_url"),
                    }
                    if github_tool
                    else None
                ),
            }
        )
    return json.dumps(
        {
            "instruction": (
                "You are the intent router for the ReMind GitHub chat tool. "
                "Return only JSON. Decide whether the latest user message should be handled "
                "by the GitHub tool before the normal assistant. Do not plan code and do not "
                "claim repository access. Classify colloquial follow-ups from context, not by "
                "keyword matching. In Russian, phrases like 'не хочешь еще 2 файла поменять', "
                "'можно туда еще', 'попробуй нормально', and similar requests after a GitHub PR "
                "are new task requests, not summaries. Questions like 'что ты поменял', "
                "'че?', 'почему PR не создан' after a GitHub result are summaries/explanations. "
                "Use intent='task' when the user wants to inspect, change, fix, refactor, edit, "
                "or open a PR for a repository. Use intent='info' for connected GitHub accounts, "
                "profile, access, repository list, or status. Use intent='summary' for questions "
                "about the last GitHub task/PR/diff/no-change result. Use intent='none' for unrelated chat. "
                "If intent='task' and the latest message depends on context, set use_recent_repo=true. "
                "If the latest message is a short continuation like 'do it' or 'ну сделай', "
                "set use_recent_task=true and put a useful merged task_text. "
                "If no repository is explicit but a recent GitHub repo is clearly referenced by "
                "there/там/that repo/context, use repo_full_name from recent_repo."
            ),
            "schema": {
                "intent": "task|info|summary|none",
                "confidence": "number from 0 to 1",
                "repo_full_name": "owner/repo or empty string",
                "use_recent_repo": "boolean",
                "use_recent_task": "boolean",
                "task_text": "for task intent only; concise user request in the user's language",
                "reason": "short private routing reason",
            },
            "latest_user_message": text,
            "recent_repo": recent_repo,
            "recent_task": (
                {
                    "repo_full_name": recent_task.get("repo_full_name"),
                    "status": recent_task.get("status"),
                    "task": recent_task.get("task"),
                    "branch_name": recent_task.get("branch_name"),
                    "has_diff": bool(recent_task.get("diff")),
                    "pull_request_url": recent_task.get("pull_request_url"),
                }
                if recent_task
                else None
            ),
            "recent_messages": recent_messages,
        },
        ensure_ascii=False,
    )


def _effective_text_from_ai_route(text: str, route: dict[str, Any], history: list[Any]) -> str:
    effective = (
        str(route.get("task_text") or text).strip() if route.get("intent") == "task" else text
    )
    if route.get("use_recent_task"):
        recent_task_text = _find_recent_github_request(history)
        if recent_task_text and recent_task_text.lower() not in effective.lower():
            effective = f"{recent_task_text}\n{effective}"

    repo_full_name = str(route.get("repo_full_name") or "").strip()
    if not repo_full_name and route.get("use_recent_repo"):
        repo_full_name = _recent_github_repo_context(history)
    if repo_full_name and not REPO_FULL_NAME_RE.search(effective):
        effective = f"{effective}\nRepository: {repo_full_name}"
    return effective


def _is_russian_text(text: str) -> bool:
    return bool(re.search(r"[а-яА-ЯёЁ]", str(text or "")))


def _language(text: str, history: list[Any] | None = None) -> str:
    if _is_russian_text(text):
        return "ru"
    for item in reversed((history or [])[-4:]):
        if isinstance(item, dict) and _is_russian_text(_history_text(item)):
            return "ru"
    return "en"


def _looks_like_github_info_request(text: str, history: list[Any]) -> bool:
    normalized = text.lower()
    if _contains_github_reference(normalized) and _contains_any(normalized, INFO_TERMS):
        return True
    if _recent_github_profile_context(history) and _contains_any(
        normalized,
        ("посмотри", "скажи", "расскажи", "look", "tell", "show"),
    ):
        return True
    return False


def _looks_like_recent_github_change_summary(text: str, history: list[Any]) -> bool:
    task = _recent_github_task_context(history)
    if not task:
        return False
    normalized = text.lower()
    if _contains_any(normalized, CONFIRM_TERMS):
        return False
    if _contains_any(normalized, CHANGE_SUMMARY_TERMS):
        return True
    if not _contains_result_explanation(normalized):
        return False
    status = str(task.get("status") or "")
    return status in {"completed_no_changes", "run_failed", "error", "pull_request_opened"} or bool(
        task.get("diff") or task.get("edits")
    )


def _looks_like_github_task(text: str, history: list[Any] | None = None) -> bool:
    if not text:
        return False
    has_action = _contains_any(text, ACTION_TERMS)
    has_followup = _contains_any(text, FOLLOWUP_TERMS)
    if not has_action and not has_followup:
        return False
    if bool(REPO_FULL_NAME_RE.search(text)) or _contains_github_reference(text):
        return True
    if not _recent_github_repo_context(history or []):
        return False
    return has_followup or has_action or _contains_any(text, CONTEXT_TERMS)


def _confirmation_task_id(text: str) -> str | None:
    match = TASK_ID_RE.search(text)
    if not match:
        return None
    if not _contains_any(text, CONFIRM_TERMS):
        return None
    return match.group(0)


def _merge_recent_task_if_needed(text: str, history: list[Any]) -> str:
    recent_task = _find_recent_github_request(history)
    if REPO_FULL_NAME_RE.search(text) and not _contains_any(text, ACTION_TERMS):
        if recent_task:
            return f"{recent_task}\nRepository: {text}"
        return text

    normalized = text.lower()
    if (
        recent_task
        and _recent_github_repo_context(history)
        and len(normalized) <= 80
        and _contains_any(
            normalized, ("ну сделай", "давай", "do it", "go ahead", "try again", "попробуй")
        )
    ):
        return f"{recent_task}\n{text}"

    return text


def _find_recent_github_request(history: list[Any]) -> str:
    for item in reversed(history[-8:]):
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        text = _history_text(item)
        if _confirmation_task_id(text):
            continue
        if _looks_like_github_task(text) and not REPO_FULL_NAME_RE.search(text):
            return text
        if _recent_github_repo_context(history) and (
            _contains_any(text, FOLLOWUP_TERMS) or _contains_any(text, ACTION_TERMS)
        ):
            return text
    return ""


def _recent_github_profile_context(history: list[Any]) -> bool:
    for item in reversed(history[-8:]):
        if not isinstance(item, dict):
            continue
        text = _history_text(item).lower()
        if _contains_github_reference(text) and _contains_any(
            text, ("profile", "профиль", "account", "аккаунт")
        ):
            return True
    return False


def _recent_github_repo_context(history: list[Any]) -> str:
    for item in reversed(history[-12:]):
        if not isinstance(item, dict):
            continue
        github_tool = item.get("github_tool")
        if isinstance(github_tool, dict):
            task = github_tool.get("task")
            if isinstance(task, dict):
                repo_full_name = str(task.get("repo_full_name") or "").strip()
                if repo_full_name:
                    return repo_full_name
            repo = github_tool.get("repo")
            if isinstance(repo, dict):
                repo_full_name = str(repo.get("full_name") or "").strip()
                if repo_full_name:
                    return repo_full_name

        matches = [match.group(1) for match in REPO_FULL_NAME_RE.finditer(_history_text(item))]
        if matches:
            return matches[-1]
    return ""


def _recent_github_task_context(history: list[Any]) -> dict[str, Any]:
    for item in reversed(history[-12:]):
        if not isinstance(item, dict):
            continue
        github_tool = item.get("github_tool")
        if isinstance(github_tool, dict) and isinstance(github_tool.get("task"), dict):
            return github_tool["task"]
    return {}


def _handle_recent_github_change_summary(text: str, history: list[Any]) -> dict[str, Any] | None:
    task = _recent_github_task_context(history)
    if not task:
        return None
    reply = _format_recent_change_summary(task, _language(text, history))
    return {
        "reply": reply,
        "github_tool": {
            "handled": True,
            "status": "summary",
            "task": task,
        },
    }


def _history_text(item: dict[str, Any]) -> str:
    parts = item.get("parts") or []
    chunks: list[str] = []
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict) and part.get("text"):
                chunks.append(str(part.get("text") or ""))
            elif isinstance(part, str):
                chunks.append(part)
    return "\n".join(chunks).strip()


def _load_installations(user_id: int) -> list[GitHubInstallation]:
    return (
        GitHubInstallation.query.filter_by(user_id=user_id)
        .order_by(GitHubInstallation.updated_at.desc(), GitHubInstallation.id.desc())
        .all()
    )


def _load_repositories(
    installations: list[GitHubInstallation],
) -> tuple[list[dict[str, Any]], list[str]]:
    repositories: list[dict[str, Any]] = []
    errors: list[str] = []
    for installation in installations:
        try:
            items = GitHubAgentService(int(installation.installation_id)).list_repositories()
        except GitHubAPIError as exc:
            errors.append(f"{installation.account_login}: {exc.message}")
            continue
        except Exception as exc:
            errors.append(f"{installation.account_login}: {exc}")
            continue

        for item in items:
            if not isinstance(item, dict) or not item.get("full_name"):
                continue
            repositories.append(
                {
                    **item,
                    "installation_id": int(installation.installation_id),
                    "account_login": installation.account_login,
                }
            )
    return repositories, errors


def _handle_github_info_request(
    text: str,
    history: list[Any],
    installations: list[GitHubInstallation],
) -> dict[str, Any]:
    language = _language(text, history)
    repositories, errors = _load_repositories(installations)
    username = _resolve_profile_login(text, history, installations)
    if language == "ru":
        reply = _format_github_info_reply_ru(text, username, installations, repositories, errors)
    else:
        reply = _format_github_info_reply_en(text, username, installations, repositories, errors)
    return {
        "reply": reply,
        "github_tool": {
            "handled": True,
            "status": "info",
            "installations": [item.to_dict() for item in installations],
            "repositories": repositories[:20],
            "repository_count": len(repositories),
            "profile_login": username,
        },
    }


def _resolve_profile_login(
    text: str,
    history: list[Any],
    installations: list[GitHubInstallation],
) -> str:
    known_logins = [item.account_login for item in installations if item.account_login]
    search_space = [text]
    search_space.extend(
        _history_text(item) for item in reversed(history[-8:]) if isinstance(item, dict)
    )
    for chunk in search_space:
        chunk_lower = chunk.lower()
        for login in known_logins:
            if login.lower() in chunk_lower:
                return login
    return known_logins[0] if len(known_logins) == 1 else ""


def _repo_visibility_counts(repositories: list[dict[str, Any]]) -> tuple[int, int]:
    private_count = sum(1 for repo in repositories if repo.get("private"))
    public_count = max(0, len(repositories) - private_count)
    return public_count, private_count


def _format_repo_examples(repositories: list[dict[str, Any]], limit: int = 8) -> list[str]:
    return [
        str(repo.get("full_name") or "") for repo in repositories[:limit] if repo.get("full_name")
    ]


def _format_github_info_reply_ru(
    text: str,
    username: str,
    installations: list[GitHubInstallation],
    repositories: list[dict[str, Any]],
    errors: list[str],
) -> str:
    public_count, private_count = _repo_visibility_counts(repositories)
    account_names = (
        ", ".join(f"`{item.account_login}`" for item in installations if item.account_login)
        or "GitHub"
    )
    examples = _format_repo_examples(repositories)

    lines = [
        "GitHub подключен через ReMind GitHub App.",
        f"Подключенные аккаунты/организации: {account_names}.",
        f"Доступно репозиториев через App: {len(repositories)}.",
    ]
    if repositories:
        lines.append(f"Видимость: публичных {public_count}, приватных {private_count}.")
    if username:
        lines.extend(
            [
                "",
                f"По профилю `{username}` я могу уверенно говорить только о данных, которые доступны через подключенную GitHub App: установке и выбранных репозиториях.",
                "Я не буду придумывать общую статистику профиля, README, followers или активность, если GitHub tool их не получил.",
            ]
        )
    if examples:
        lines.extend(["", "Примеры доступных репозиториев:"])
        lines.extend(f"- `{name}`" for name in examples)
        remaining = len(repositories) - len(examples)
        if remaining > 0:
            lines.append(f"- и еще {remaining}")
    if errors:
        lines.extend(["", "Ошибки при чтении части установок:"])
        lines.extend(f"- {error}" for error in errors[:5])
    lines.extend(
        [
            "",
            "Для изменений в коде напиши задачу и репозиторий в формате `owner/repo`. Сначала я покажу план, а PR создам только после явного подтверждения.",
        ]
    )
    return "\n".join(lines)


def _format_github_info_reply_en(
    text: str,
    username: str,
    installations: list[GitHubInstallation],
    repositories: list[dict[str, Any]],
    errors: list[str],
) -> str:
    public_count, private_count = _repo_visibility_counts(repositories)
    account_names = (
        ", ".join(f"`{item.account_login}`" for item in installations if item.account_login)
        or "GitHub"
    )
    examples = _format_repo_examples(repositories)

    lines = [
        "GitHub is connected through the ReMind GitHub App.",
        f"Connected accounts/organizations: {account_names}.",
        f"Repositories available through the App: {len(repositories)}.",
    ]
    if repositories:
        lines.append(f"Visibility: {public_count} public, {private_count} private.")
    if username:
        lines.extend(
            [
                "",
                f"For profile `{username}`, I can only state data confirmed by the connected GitHub App: installation and selected repositories.",
                "I will not invent profile README, followers, or activity stats unless the GitHub tool actually retrieves them.",
            ]
        )
    if examples:
        lines.extend(["", "Example available repositories:"])
        lines.extend(f"- `{name}`" for name in examples)
        remaining = len(repositories) - len(examples)
        if remaining > 0:
            lines.append(f"- and {remaining} more")
    if errors:
        lines.extend(["", "Errors while reading some installations:"])
        lines.extend(f"- {error}" for error in errors[:5])
    lines.extend(
        [
            "",
            "For code changes, send a task and a repository in `owner/repo` format. I will show a plan first and create a PR only after explicit confirmation.",
        ]
    )
    return "\n".join(lines)


def _resolve_repo(
    user_id: int,
    text: str,
    installations: list[GitHubInstallation],
    history: list[Any] | None = None,
) -> dict[str, Any]:
    repositories, errors = _load_repositories(installations)
    if not repositories:
        detail = f" GitHub вернул ошибку: {'; '.join(errors)}." if errors else ""
        return {
            "status": "no_repositories",
            "reply": (
                "У подключенной GitHub App нет доступных репозиториев."
                f"{detail} Проверьте, что в установке GitHub App выбран нужный репозиторий."
            ),
        }

    repo_tokens = [match.group(1) for match in REPO_FULL_NAME_RE.finditer(text)]
    if not repo_tokens:
        recent_repo = _recent_github_repo_context(history or [])
        if recent_repo:
            by_full_name = {str(repo["full_name"]).lower(): repo for repo in repositories}
            repo = by_full_name.get(recent_repo.lower())
            if repo:
                return {"status": "ok", "repo": repo}

        return {
            "status": "repo_required",
            "reply": (
                "Укажите репозиторий в формате `owner/repo`, например "
                f"`{repositories[0]['full_name']}`.\n\n" + _format_available_repos(repositories)
            ),
        }

    by_full_name = {str(repo["full_name"]).lower(): repo for repo in repositories}
    for token in repo_tokens:
        repo = by_full_name.get(token.lower())
        if repo:
            return {"status": "ok", "repo": repo}

    token = repo_tokens[0]
    suggestions = _repo_suggestions(token, repositories)
    suggestion_text = (
        "\n\nПохожие доступные репозитории:\n" + "\n".join(f"- `{item}`" for item in suggestions)
        if suggestions
        else "\n\n" + _format_available_repos(repositories)
    )
    return {
        "status": "repo_not_connected",
        "reply": (
            f"Репозиторий `{token}` не найден среди подключенных к ReMind GitHub App."
            f"{suggestion_text}\n\n"
            "Выберите доступный репозиторий или обновите установку GitHub App в GitHub."
        ),
    }


def _repo_suggestions(token: str, repositories: list[dict[str, Any]]) -> list[str]:
    names = [str(repo["full_name"]) for repo in repositories]
    lower_to_original = {name.lower(): name for name in names}
    matches = get_close_matches(token.lower(), list(lower_to_original), n=5, cutoff=0.45)
    return [lower_to_original[match] for match in matches]


def _format_available_repos(repositories: list[dict[str, Any]], limit: int = 8) -> str:
    visible = repositories[:limit]
    lines = ["Доступные репозитории:"]
    lines.extend(f"- `{repo['full_name']}`" for repo in visible)
    remaining = len(repositories) - len(visible)
    if remaining > 0:
        lines.append(f"- и еще {remaining}")
    return "\n".join(lines)


def _extract_task_text(text: str, repo_full_name: str) -> str:
    task = re.sub(re.escape(repo_full_name), " ", text, flags=re.IGNORECASE)
    task = re.sub(r"\bRepository:\s*", " ", task, flags=re.IGNORECASE)
    task = re.sub(
        r"(?i)\b(github|git hub|repo|repository|repositories|pull request|pr)\b",
        " ",
        task,
    )
    task = re.sub(
        r"(?i)\b(гитхаб[ае]?|репо|репозитор(?:ий|ии|ия)?|пулл?\s+реквест|pr)\b", " ", task
    )
    task = re.sub(r"\s+", " ", task).strip(" .:-\n\t")
    return task or text.strip()


def _extract_base_branch(text: str, repo: dict[str, Any]) -> str:
    match = BASE_BRANCH_RE.search(text)
    if match:
        branch = match.group(1).strip("`'\".,; ")
        if branch and "/" not in branch[:1]:
            return branch
    return str(repo.get("default_branch") or "main").strip() or "main"


def _followup_targets_recent_branch(text: str) -> bool:
    return _contains_any(text, RECENT_BRANCH_TERMS)


def _resolve_base_branch(text: str, repo: dict[str, Any], history: list[Any]) -> str:
    if BASE_BRANCH_RE.search(text):
        return _extract_base_branch(text, repo)

    if _followup_targets_recent_branch(text):
        recent_task = _recent_github_task_context(history)
        recent_repo = str(recent_task.get("repo_full_name") or "").strip().lower()
        branch_name = str(recent_task.get("branch_name") or "").strip()
        if recent_repo == str(repo.get("full_name") or "").strip().lower() and branch_name:
            return branch_name

    return str(repo.get("default_branch") or "main").strip() or "main"


def _new_task_public_id() -> str:
    return f"gh_{secrets.token_urlsafe(18)}"


def _create_plan_task(
    *,
    user_id: int,
    installation_id: int,
    repo_full_name: str,
    base_branch: str,
    task_text: str,
) -> dict[str, Any]:
    task = GitHubAgentTask(
        public_id=_new_task_public_id(),
        user_id=user_id,
        installation_id=installation_id,
        repo_full_name=repo_full_name,
        base_branch=base_branch,
        task=task_text,
        status="planning",
    )
    db.session.add(task)
    db.session.commit()

    try:
        plan = GitHubAgentService(installation_id).plan(repo_full_name, base_branch, task_text)
        task.set_plan(plan)
        task.status = "planned"
        task.updated_at = datetime.utcnow()
        db.session.commit()
    except GitHubAPIError as exc:
        db.session.rollback()
        task.status = "error"
        task.error = exc.message
        task.updated_at = datetime.utcnow()
        db.session.commit()
        return {
            "reply": f"GitHub не смог построить план для `{repo_full_name}`: {exc.message}",
            "github_tool": {"handled": True, "status": "plan_failed", "task": task.to_dict()},
        }
    except Exception as exc:
        db.session.rollback()
        task.status = "error"
        task.error = str(exc)
        task.updated_at = datetime.utcnow()
        db.session.commit()
        return {
            "reply": f"Не удалось построить GitHub-план: {exc}",
            "github_tool": {"handled": True, "status": "plan_failed", "task": task.to_dict()},
        }

    task_payload = task.to_dict()
    return {
        "reply": _format_plan_reply(task_payload),
        "github_tool": {"handled": True, "status": "planned", "task": task_payload},
    }


def _run_confirmed_task(user_id: int, task_id: str) -> dict[str, Any]:
    task = GitHubAgentTask.query.filter_by(user_id=user_id, public_id=task_id).first()
    if not task:
        return {
            "reply": (
                f"GitHub-задача `{task_id}` не найдена. Этот ID не был сохранен "
                "GitHub-инструментом, поэтому я не могу по нему создать PR. "
                "Напишите задачу еще раз, и я составлю новый подтверждаемый план."
            ),
            "github_tool": {"handled": True, "status": "task_not_found"},
        }
    if task.status not in {"planned", "error"}:
        return {
            "reply": (
                f"GitHub-задачу `{task_id}` нельзя запустить из текущего статуса "
                f"`{task.status}`."
            ),
            "github_tool": {
                "handled": True,
                "status": "invalid_task_state",
                "task": task.to_dict(),
            },
        }

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
        task.error = exc.message
        task.updated_at = datetime.utcnow()
        db.session.commit()
        return {
            "reply": f"GitHub отклонил выполнение задачи `{task_id}`: {exc.message}",
            "github_tool": {"handled": True, "status": "run_failed", "task": task.to_dict()},
        }
    except GitHubAgentExecutionError as exc:
        db.session.rollback()
        task.status = "error"
        task.error = str(exc)
        task.set_edits({"activity": exc.activity})
        task.updated_at = datetime.utcnow()
        db.session.commit()
        return {
            "reply": f"AI-редактор не смог подготовить изменения для `{task_id}`: {exc}",
            "github_tool": {"handled": True, "status": "run_failed", "task": task.to_dict()},
        }
    except Exception as exc:
        db.session.rollback()
        task.status = "error"
        task.error = str(exc)
        task.updated_at = datetime.utcnow()
        db.session.commit()
        return {
            "reply": f"Не удалось выполнить GitHub-задачу `{task_id}`: {exc}",
            "github_tool": {"handled": True, "status": "run_failed", "task": task.to_dict()},
        }

    task_payload = task.to_dict()
    return {
        "reply": _format_run_reply(task_payload),
        "github_tool": {"handled": True, "status": task.status, "task": task_payload},
    }


def _labels_for_task(task: dict[str, Any]) -> dict[str, Any]:
    if _is_russian_text(str(task.get("task") or "")):
        return {
            "plan_ready": "План готов для `{repo}` от ветки `{branch}`.",
            "task_id": "ID задачи",
            "steps": "Шаги:",
            "files": "Файлы:",
            "risks": "Риски:",
            "step_fallback": "Шаг",
            "not_written": "Я еще ничего не записал в репозиторий.",
            "confirm": "Чтобы создать ветку и PR, напишите: `Подтвердить GitHub PR {task_id}`",
            "no_pr": "PR не создан для `{repo}`: безопасных изменений не найдено.",
            "findings": "Наблюдения:",
            "done": "Готово: создан Pull Request для `{repo}`.",
            "branch": "Ветка",
            "diff": "Изменения",
            "diff_truncated": "# Изменения сокращены в чате.",
            "actions": {
                "inspect": "проверка",
                "edit": "редактирование",
                "update": "редактирование",
                "create": "создание",
                "delete": "удаление",
            },
        }
    return {
        "plan_ready": "Plan ready for `{repo}` from branch `{branch}`.",
        "task_id": "Task ID",
        "steps": "Steps:",
        "files": "Files:",
        "risks": "Risks:",
        "step_fallback": "Step",
        "not_written": "I have not written anything to the repository yet.",
        "confirm": "To create the branch and PR, write: `Confirm GitHub PR {task_id}`",
        "no_pr": "No PR was created for `{repo}`: no safe changes were found.",
        "findings": "Findings:",
        "done": "Done: opened a Pull Request for `{repo}`.",
        "branch": "Branch",
        "diff": "Diff",
        "diff_truncated": "# Diff truncated in chat.",
        "actions": {},
    }


def _format_plan_reply(task: dict[str, Any]) -> str:
    plan = task.get("plan") or {}
    labels = _labels_for_task(task)
    lines = [
        labels["plan_ready"].format(repo=task["repo_full_name"], branch=task["base_branch"]),
        "",
        f"{labels['task_id']}: `{task['id']}`",
    ]
    summary = str(plan.get("summary") or "").strip()
    if summary:
        lines.extend(["", summary])

    steps = [item for item in plan.get("steps") or [] if isinstance(item, dict)]
    if steps:
        lines.extend(["", labels["steps"]])
        for index, step in enumerate(steps[:8], start=1):
            title = str(step.get("title") or "").strip() or labels["step_fallback"]
            details = str(step.get("details") or "").strip()
            lines.append(f"{index}. {title}" + (f" - {details}" if details else ""))

    files = [item for item in plan.get("files") or [] if isinstance(item, dict)]
    if files:
        lines.extend(["", labels["files"]])
        action_labels = _dict_or_empty(labels.get("actions"))
        for item in files[:12]:
            path = str(item.get("path") or "").strip()
            action = str(item.get("action") or "inspect").strip()
            action_label = action_labels.get(action.lower(), action)
            reason = str(item.get("reason") or "").strip()
            lines.append(f"- `{path}` ({action_label})" + (f" - {reason}" if reason else ""))

    risks = [str(item).strip() for item in plan.get("risks") or [] if str(item).strip()]
    if risks:
        lines.extend(["", labels["risks"]])
        lines.extend(f"- {risk}" for risk in risks[:6])

    lines.extend(
        [
            "",
            labels["not_written"],
            labels["confirm"].format(task_id=task["id"]),
        ]
    )
    return "\n".join(lines)


def _format_run_reply(task: dict[str, Any]) -> str:
    labels = _labels_for_task(task)
    if task.get("status") == "completed_no_changes":
        edits = task.get("edits") or {}
        language = "ru" if _is_russian_text(str(task.get("task") or "")) else "en"
        reason = _human_no_changes_reason(
            str(edits.get("no_changes_reason") or edits.get("summary") or "").strip(),
            language,
        )
        findings = [str(item).strip() for item in edits.get("findings") or [] if str(item).strip()]
        lines = [
            labels["no_pr"].format(repo=task["repo_full_name"]),
        ]
        if reason:
            lines.extend(["", reason])
        if findings:
            lines.extend(["", labels["findings"]])
            lines.extend(f"- {item}" for item in findings[:8])
        return "\n".join(lines)

    lines = [
        labels["done"].format(repo=task["repo_full_name"]),
        "",
        f"- PR: {task.get('pull_request_url')}",
        f"- {labels['branch']}: `{task.get('branch_name')}`",
    ]
    return "\n".join(lines)


def _format_recent_change_summary(task: dict[str, Any], language: str) -> str:
    repo = str(task.get("repo_full_name") or "").strip() or "GitHub repository"
    pr_url = str(task.get("pull_request_url") or "").strip()
    pr_number = task.get("pull_request_number")
    branch = str(task.get("branch_name") or "").strip()
    status = str(task.get("status") or "").strip()
    edits = _dict_or_empty(task.get("edits"))
    diff = str(task.get("diff") or "").strip()
    files = _summarize_diff_files(diff)
    edit_items = [item for item in edits.get("edits") or [] if isinstance(item, dict)]
    edit_summary = str(edits.get("summary") or "").strip()

    if language == "ru":
        if status == "completed_no_changes" and not pr_url:
            lines = [f"По фактической GitHub-задаче для `{repo}`:"]
        else:
            lines = [f"По фактическому GitHub PR для `{repo}`:"]
        if pr_url:
            pr_label = f"PR #{pr_number}" if pr_number else "PR"
            lines.append(f"- {pr_label}: {pr_url}")
        if branch:
            lines.append(f"- Ветка: `{branch}`")
        if status == "completed_no_changes" or not diff:
            reason = _human_no_changes_reason(
                str(edits.get("no_changes_reason") or edit_summary or "").strip(),
                language,
            )
            lines.append("")
            lines.append(
                "PR не создан, потому что фактический diff пустой. "
                "Я не должен утверждать, что код изменен, если сохраненных изменений нет."
            )
            if reason:
                lines.append(f"Причина: {reason}")
            return "\n".join(lines)

        if edit_summary:
            lines.extend(["", edit_summary])
        if files:
            lines.extend(["", "Файлы в diff:"])
            for item in files[:12]:
                lines.append(
                    f"- `{item['path']}`: {item['additions']} добавлено, {item['deletions']} удалено"
                )
                for removed in item["removed"][:3]:
                    lines.append(f"  - удалено: `{removed}`")
                for added in item["added"][:3]:
                    lines.append(f"  - добавлено: `{added}`")
        elif edit_items:
            lines.extend(["", "Файлы из результата редактора:"])
            for item in edit_items[:12]:
                path = str(item.get("path") or "").strip()
                action = str(item.get("action") or "update").strip()
                reason = str(item.get("reason") or "").strip()
                lines.append(f"- `{path}` ({action})" + (f" - {reason}" if reason else ""))
        lines.extend(
            [
                "",
                "Это только данные из сохраненного результата GitHub-инструмента; я не добавляю сюда предположения из плана.",
            ]
        )
        return "\n".join(lines)

    if status == "completed_no_changes" and not pr_url:
        lines = [f"From the actual GitHub task for `{repo}`:"]
    else:
        lines = [f"From the actual GitHub PR for `{repo}`:"]
    if pr_url:
        pr_label = f"PR #{pr_number}" if pr_number else "PR"
        lines.append(f"- {pr_label}: {pr_url}")
    if branch:
        lines.append(f"- Branch: `{branch}`")
    if status == "completed_no_changes" or not diff:
        reason = _human_no_changes_reason(
            str(edits.get("no_changes_reason") or edit_summary or "").strip(),
            language,
        )
        lines.append("")
        lines.append("The actual diff is empty, so I will not invent code changes.")
        if reason:
            lines.append(f"Reason: {reason}")
        return "\n".join(lines)

    if edit_summary:
        lines.extend(["", edit_summary])
    if files:
        lines.extend(["", "Files in the diff:"])
        for item in files[:12]:
            lines.append(
                f"- `{item['path']}`: {item['additions']} added, {item['deletions']} deleted"
            )
            for removed in item["removed"][:3]:
                lines.append(f"  - deleted: `{removed}`")
            for added in item["added"][:3]:
                lines.append(f"  - added: `{added}`")
    elif edit_items:
        lines.extend(["", "Files from the editor result:"])
        for item in edit_items[:12]:
            path = str(item.get("path") or "").strip()
            action = str(item.get("action") or "update").strip()
            reason = str(item.get("reason") or "").strip()
            lines.append(f"- `{path}` ({action})" + (f" - {reason}" if reason else ""))
    lines.extend(
        [
            "",
            "This is based only on the saved GitHub tool result; I am not adding assumptions from the plan.",
        ]
    )
    return "\n".join(lines)


def _human_no_changes_reason(reason: str, language: str) -> str:
    clean_reason = str(reason or "").strip()
    if not clean_reason:
        return ""

    normalized = clean_reason.lower()
    if "only proposed edits that leave files unchanged" in normalized:
        if language == "ru":
            return (
                "AI-редактор предложил только правки, которые не меняют файлы. "
                "Поэтому ветка и PR не создавались."
            )
        return "The AI editor only proposed no-op edits, so no branch or PR was created."
    if "only proposed cosmetic css token edits" in normalized:
        if language == "ru":
            return (
                "AI-редактор предложил только косметические изменения CSS-токенов, "
                "а не безопасный багфикс. Поэтому ветка и PR не создавались."
            )
        return "The AI editor only proposed cosmetic CSS token edits, not a safe bug fix."
    if "returned no valid file edits" in normalized:
        if language == "ru":
            return "AI-редактор не вернул ни одной валидной правки файла."
        return "The AI editor did not return any valid file edits."
    if "did not return json edits" in normalized:
        if language == "ru":
            return "AI-редактор вернул ответ не в формате JSON-правок."
        return "The AI editor did not return JSON edits."
    if "did not return valid json edits after retry" in normalized:
        if language == "ru":
            return (
                "AI-редактор дважды не вернул валидный JSON с правками, поэтому PR не создавался."
            )
        return "The AI editor did not return valid JSON edits after retry, so no PR was created."
    if language == "ru" and not _is_russian_text(clean_reason):
        return f"Техническая причина: {clean_reason}"
    return clean_reason


def _summarize_diff_files(diff: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in str(diff or "").splitlines():
        diff_match = re.match(r"^diff --git a/(.+?) b/(.+)$", raw_line)
        if diff_match:
            if current:
                files.append(current)
            current = {
                "path": diff_match.group(2),
                "additions": 0,
                "deletions": 0,
                "added": [],
                "removed": [],
            }
            continue
        status_match = re.match(r"^#\s+[A-Za-z]+:\s+(.+)$", raw_line)
        if status_match and current:
            current["path"] = status_match.group(1).strip() or current["path"]
            continue
        if not current:
            continue
        if (
            raw_line.startswith("+++ ")
            or raw_line.startswith("--- ")
            or raw_line.startswith("@@")
            or raw_line.startswith("index ")
        ):
            continue
        if raw_line.startswith("+"):
            current["additions"] += 1
            line = raw_line[1:].strip()
            if line:
                current["added"].append(line)
        elif raw_line.startswith("-"):
            current["deletions"] += 1
            line = raw_line[1:].strip()
            if line:
                current["removed"].append(line)
    if current:
        files.append(current)
    return files
