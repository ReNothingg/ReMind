from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.ai_engine.skills import SKILLS
from backend.config import WEB_SEARCH_ENABLED
from backend.services.agent_plugins import disabled_skills
from backend.services.agent_runtime_settings import load_agent_runtime
from backend.services.model_access import can_user_access_model
from backend.services.python_runner import python_runner_available

logger = logging.getLogger(__name__)


def user_has_github_connection(user_id: int | None) -> bool:
    if user_id is None:
        return False
    from backend.db.models import GitHubInstallation
    from backend.services.github.app import github_app_configured

    if not github_app_configured():
        return False
    try:
        return GitHubInstallation.query.filter_by(user_id=user_id).first() is not None
    except Exception:
        logger.exception("Failed to resolve GitHub installation availability")
        return False


@dataclass(frozen=True)
class SkillAccess:
    available: frozenset[str]
    reasons: dict[str, str]


def resolve_skill_access(
    user_id: int | None,
    *,
    enabled: bool = True,
    web_client: bool = True,
    enable_web: bool = True,
    execution_skills: frozenset[str] | None = None,
) -> SkillAccess:
    if execution_skills is None:
        settings = load_agent_runtime(user_id)
        execution_skills = frozenset(
            name for name, active in (
                ("shell", settings["shellEnabled"] and python_runner_available(user_id)),
                ("subagents", settings["subagentMaxDepth"] > 0),
            )
            if active
        )
    gates = {
        "demo_image": enabled and web_client and can_user_access_model("demo_image", user_id),
        "web_client": enabled and web_client,
        "account": enabled and web_client and user_id is not None,
        "web_search": enabled and web_client and bool(WEB_SEARCH_ENABLED) and enable_web,
        "github": enabled and web_client and user_has_github_connection(user_id),
        "python": enabled and web_client and python_runner_available(user_id),
    }
    disabled = disabled_skills(user_id)
    available = frozenset(
        skill.id
        for skill in SKILLS
        if gates[skill.access]
        and skill.id not in disabled
        and (skill.id not in {"shell", "subagents"} or skill.id in execution_skills)
    )
    reasons = {
        skill.id: (
            "github_not_connected"
            if skill.access == "github"
            else (
                "authentication_required"
                if skill.access in {"python", "account"} and user_id is None
                else "tool_disabled"
            )
        )
        for skill in SKILLS
        if skill.id not in available
    }
    reasons.update(dict.fromkeys(disabled, "plugin_disabled"))
    return SkillAccess(available, reasons)
