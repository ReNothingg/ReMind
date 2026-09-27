from __future__ import annotations

import logging
from dataclasses import dataclass

from ai_engine.skills import SKILLS
from config import WEB_SEARCH_ENABLED
from services.model_access import can_user_access_model
from services.python_runner import python_runner_available

logger = logging.getLogger(__name__)


def user_has_github_connection(user_id: int | None) -> bool:
    if user_id is None:
        return False
    from services.github_app import github_app_configured
    from utils.auth import GitHubInstallation

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
    user_id: int | None, *, enabled: bool = True, web_client: bool = True, enable_web: bool = True
) -> SkillAccess:
    gates = {
        "demo_image": enabled and web_client and can_user_access_model("demo_image", user_id),
        "web_client": enabled and web_client,
        "web_search": enabled and web_client and bool(WEB_SEARCH_ENABLED) and enable_web,
        "github": enabled and web_client and user_has_github_connection(user_id),
        "python": enabled and web_client and python_runner_available(user_id),
    }
    available = frozenset(skill.id for skill in SKILLS if gates[skill.access])
    reasons = {
        skill.id: (
            "github_not_connected"
            if skill.access == "github"
            else (
                "authentication_required"
                if skill.access == "python" and user_id is None
                else "tool_disabled"
            )
        )
        for skill in SKILLS
        if skill.id not in available
    }
    return SkillAccess(available, reasons)
