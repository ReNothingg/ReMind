from __future__ import annotations

import json
from typing import Any

from ai_engine.skills import SKILL_IDS, SKILLS
from services.skill_access import resolve_skill_access

TOOL_IDS = SKILL_IDS


def composer_tool_catalog(user_id: int | None) -> list[dict[str, Any]]:
    access = resolve_skill_access(user_id)
    reasons = {
        "github_not_connected": "githubConnect",
        "authentication_required": "signIn",
        "tool_disabled": "unavailable",
    }
    return [
        {
            "id": skill.id,
            "available": skill.id in access.available,
            "titleKey": skill.title_key or f"composer.tools.{skill.id}",
            "descriptionKey": skill.description_key or f"composer.tools.{skill.id}Description",
            **(
                {"unavailableKey": f"composer.tools.{reasons[access.reasons[skill.id]]}"}
                if skill.id not in access.available
                else {}
            ),
        }
        for skill in SKILLS
        if not skill.hide_unavailable or skill.id in access.available
    ]


def validate_selected_tools(value: Any, user_id: int | None) -> list[str]:
    from routes.api_errors import ApiError

    if value is None:
        return []
    if isinstance(value, str):
        if len(value) > 512:
            raise ApiError("Invalid tool selection", status=400, code="invalid_tool_selection")
        try:
            value = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ApiError(
                "Invalid tool selection", status=400, code="invalid_tool_selection"
            ) from exc
    if (
        not isinstance(value, list)
        or len(value) > len(TOOL_IDS)
        or any(not isinstance(tool, str) or tool not in TOOL_IDS for tool in value)
    ):
        raise ApiError("Invalid tool selection", status=400, code="invalid_tool_selection")
    selected = list(dict.fromkeys(value))
    if not selected:
        return []
    available = {tool["id"] for tool in composer_tool_catalog(user_id) if tool["available"]}
    if any(tool not in available for tool in selected):
        raise ApiError("Selected tool is unavailable", status=403, code="tool_unavailable")
    return selected


def validate_composer_content(
    value: Any, message: str, selected: list[str], model: str
) -> str | None:

    import re

    from routes.api_errors import ApiError

    if value is None:
        return None
    if not isinstance(value, str) or len(value) > len(message) + 2048:
        raise ApiError("Invalid composer content", status=400, code="invalid_tool_selection")
    known = set(TOOL_IDS) | {"demo_image", "mindart"}
    allowed = set(selected) | ({model} if model in {"demo_image", "mindart"} else set())
    found = []

    def strip_marker(match):
        tool_id = match.group(1)
        if tool_id not in known:
            return match.group(0)
        if tool_id not in allowed:
            raise ApiError("Invalid composer content", status=400, code="invalid_tool_selection")
        found.append(tool_id)
        return ""

    plain = re.sub(r"@\{([a-z_]+)\}", strip_marker, value)
    if plain.strip() != message.strip():
        raise ApiError("Invalid composer content", status=400, code="invalid_tool_selection")
    return value.strip() if found else None
