from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ai_engine.personalization import (
    build_interaction_metadata,
    render_active_mind_prompt,
    render_beatbox_state_prompt,
    render_current_canvas_textdoc,
    render_telegram_context_prompt,
    render_user_md_with_settings,
)
from ai_engine.prompt_templates import render_prompt, require_prompt
from ai_engine.skills import SKILL_BY_ID, SKILLS
from services.skill_access import SkillAccess, resolve_skill_access


def web_enabled(data: dict[str, Any]) -> bool:
    return any(
        str(data.get(key) or "").strip().lower() in {"1", "true", "yes", "on"}
        for key in ("webSearch", "autoWebSearch")
    )


@dataclass
class PromptBundle:
    sections: tuple[str, ...]
    access: SkillAccess
    selected: tuple[str, ...]
    instructions: dict[str, str]
    initial_canvas: Any = None

    def load(self, skill_id: str) -> str:
        if skill_id not in self.access.available:
            raise ValueError("skill_unavailable")
        if skill_id not in self.instructions:
            self.instructions[skill_id] = SKILL_BY_ID[skill_id].instructions()
        return self.instructions[skill_id]

    def render(self, canvas: Any = None) -> str:
        skills = [self.instructions[skill.id] for skill in SKILLS if skill.id in self.instructions]
        context = (
            render_current_canvas_textdoc(
                {"canvas_textdoc": canvas if canvas is not None else self.initial_canvas}
            )
            if "canvas" in self.access.available
            else ""
        )
        return "\n\n".join(part for part in (*self.sections, *skills, context) if part)


def build_prompt_bundle(
    user_id: int | None, data: dict[str, Any], *, access: SkillAccess | None = None
) -> PromptBundle:
    access = access or resolve_skill_access(
        user_id,
        enabled=data.get("toolsEnabled", True) is not False,
        web_client=not isinstance(data.get("telegram_context"), dict),
        enable_web=web_enabled(data),
    )
    raw_selected = data.get("selected_tools")
    selected = (
        tuple(
            dict.fromkeys(
                skill
                for skill in raw_selected
                if isinstance(skill, str) and skill in access.available
            )
        )
        if isinstance(raw_selected, list)
        else ()
    )
    catalog = [
        {
            "id": skill.id,
            "summary": skill.summary(),
            "available": skill.id in access.available,
            "functions": list(skill.functions) if skill.id in access.available else [],
            **({"reason": access.reasons[skill.id]} if skill.id not in access.available else {}),
        }
        for skill in SKILLS
    ]
    require_prompt("prompt.md")
    require_prompt("user.md")
    require_prompt("context/capabilities.md")
    metadata = build_interaction_metadata(data, data.get("history") or [])
    sections = (
        render_prompt(
            "prompt.md",
            {"currentDateTime": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        ),
        render_user_md_with_settings(user_id, metadata, data.get("telegram_context")),
        render_prompt(
            "context/capabilities.md",
            {
                "CAPABILITIES_JSON": json.dumps(catalog, ensure_ascii=False),
                "SELECTED_SKILLS": json.dumps(selected, ensure_ascii=False),
            },
        ),
        render_active_mind_prompt(data.get("active_mind")),
        render_telegram_context_prompt(data),
        render_beatbox_state_prompt(data) if "beatbox" in access.available else "",
    )
    bundle = PromptBundle(sections, access, selected, {}, data.get("canvas_textdoc"))
    preload = set(selected)
    if "web" in access.available:
        preload.add("web")
    if data.get("canvas_textdoc") and "canvas" in access.available:
        preload.add("canvas")
    if data.get("beatbox_state") and "beatbox" in access.available:
        preload.add("beatbox")
    for skill in SKILLS:
        if skill.id in preload:
            bundle.load(skill.id)
    return bundle


def build_system_prompt(user_id: int | None, data: dict[str, Any]) -> str:
    return build_prompt_bundle(user_id, data).render()
