from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.ai_engine.personalization import (
    build_interaction_metadata,
    render_active_mind_prompt,
    render_beatbox_state_prompt,
    render_current_canvas_textdoc,
    render_telegram_context_prompt,
    render_user_md_with_settings,
)
from backend.ai_engine.prompt_templates import render_prompt, require_prompt
from backend.ai_engine.skills import SKILL_BY_ID, SKILLS
from backend.errors import ApiError
from backend.services.agent_plugins import active_instructions
from backend.services.agent_skills import (
    SKILL_REF,
    is_skill_reference,
    requested_skill,
    session_skill_catalog,
    skill_content,
)
from backend.services.chat.session_references import resolve_references, tag_safe_json
from backend.services.project_memory import project_memory
from backend.services.project_resources import MAX_INSTRUCTION_BYTES
from backend.services.tools.skill_access import SkillAccess, resolve_skill_access


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
    project_files: tuple[dict, ...] = ()
    imported_skills: dict = field(default_factory=dict)
    project_id: str | None = None
    invoked_skill: dict | None = None
    chat_references: tuple[dict, ...] = ()

    def load(self, skill_id: str) -> str:
        if skill_id not in self.access.available:
            raise ValueError("skill_unavailable")
        if skill_id not in self.instructions:
            self.instructions[skill_id] = SKILL_BY_ID[skill_id].instructions()
        return self.instructions[skill_id]

    def parts(self, canvas: Any = None) -> list[str]:
        skills = [self.instructions[skill.id] for skill in SKILLS if skill.id in self.instructions]
        context = (
            render_current_canvas_textdoc(
                {"canvas_textdoc": canvas if canvas is not None else self.initial_canvas}
            )
            if "canvas" in self.access.available
            else ""
        )
        return [part for part in (*self.sections, *skills, context) if part]

    def render(self, canvas: Any = None) -> str:
        return "\n\n".join(self.parts(canvas))


def build_prompt_bundle(
    user_id: int | None,
    data: dict[str, Any],
    *,
    access: SkillAccess | None = None,
    execution_skills: frozenset[str] = frozenset(),
) -> PromptBundle:
    access = access or resolve_skill_access(
        user_id,
        enabled=data.get("toolsEnabled", True) is not False,
        web_client=not isinstance(data.get("telegram_context"), dict)
        or data.get("telegram_agent") is True,
        enable_web=web_enabled(data),
        execution_skills=execution_skills,
    )
    if data.get("telegram_agent") is True:
        supported = access.available.intersection(
            {"web", "files", "data", "slides", "workflow", "github", "python", "image_analysis"}
        )
        access = SkillAccess(
            supported,
            {
                **access.reasons,
                **dict.fromkeys(access.available - supported, "channel_unavailable"),
            },
        )
    if data.get("_automation") is True:
        supported = access.available.intersection(
            {"web", "files", "data", "slides", "visualize", "charts", "diagrams", "quiz"}
        )
        access = SkillAccess(
            supported,
            {
                **access.reasons,
                **dict.fromkeys(access.available - supported, "channel_unavailable"),
            },
        )
    mind = data.get("active_mind") or {}
    if data.get("temporary_chat") and "slides" in access.available:
        access = SkillAccess(
            access.available - {"slides"},
            {**access.reasons, "slides": "persistent_account_required"},
        )
    mind_skills = mind.get("skill_ids")
    if not data.get("_schedule_origin") and "schedule" in access.available:
        access = SkillAccess(
            access.available - {"schedule"}, {**access.reasons, "schedule": "channel_unavailable"}
        )
    candidates = data.get("_session_references") or ()
    references, reference_frames = resolve_references(
        user_id, data.get("session_id"), data.get("_workspace_scope"), data.get("model"), candidates
    ) if candidates and data.get("_context_is_private_web") is True else ((), [])
    if not (data.get("_context_archive") or references) and "chat_memory" in access.available:
        access = SkillAccess(
            access.available - {"chat_memory"},
            {**access.reasons, "chat_memory": "channel_unavailable"},
        )
    if isinstance(mind_skills, list):
        allowed = access.available.intersection(mind_skills)
        access = SkillAccess(
            allowed,
            {**access.reasons, **dict.fromkeys(access.available - allowed, "mind_skill_disabled")},
        )
    raw_selected = [*(mind_skills or []), *(data.get("selected_tools") or [])]
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
    workspace_scope = data.get("_workspace_scope")
    memory = (
        project_memory(
            user_id,
            data.get("session_id"),
            expected_workspace=workspace_scope,
            exclude_sessions=tuple(item["session_id"] for item in candidates),
        )
        if not any(
            data.get(key) for key in ("temporary_chat", "telegram_context", "external_telegram")
        )
        else None
    )
    if workspace_scope is not None and memory is None:
        raise ApiError(
            "workspace_chat_scope_changed", status=409, code="workspace_chat_scope_changed"
        )
    resource_skills = {
        "files",
        "data",
        "slides",
        "python",
        "image_analysis",
        "visualize",
        "canvas",
        "shell",
    }
    project_files = tuple(memory["files"]) if memory and resource_skills & access.available else ()
    workspace_id = memory["id"] if memory else None
    imported = {}
    if (
        data.get("_context_is_private_web") is True
        and data.get("toolsEnabled", True) is not False
        and not data.get("_automation")
        and not data.get("telegram_context")
        and not data.get("telegram_agent")
        and (not mind or mind.get("owner_id") == user_id)
    ):
        allowed_imports = (
            frozenset(value[len(SKILL_REF):] for value in mind_skills if is_skill_reference(value))
            if isinstance(mind_skills, list)
            else None
        )
        imported = session_skill_catalog(user_id, workspace_id, allowed_imports)
    invoked = None
    if invoked_name := requested_skill(data.get("message"), imported):
        loaded = skill_content(user_id, workspace_id, imported[invoked_name])
        if loaded["ok"]:
            invoked = loaded
    skill_catalog = [
        {key: item[key] for key in ("name", "description", "whenToUse") if key in item}
        for item in imported.values()
        if item["modelInvocable"]
    ]
    project_context = ""
    if memory and (memory["instructions"] or project_files):
        encoded = memory["instructions"].encode("utf-8")
        instructions = encoded[:MAX_INSTRUCTION_BYTES].decode("utf-8", errors="ignore")
        project_context = render_prompt(
            "context/project_resources.md",
            {
                "PROJECT_INSTRUCTIONS": instructions.replace(
                    "</system-reminder>", r"<\/system-reminder>"
                ),
                "PROJECT_FILES": json.dumps(
                    [
                        {"name": item["original_name"], "mime_type": item["mime_type"]}
                        for item in project_files
                    ],
                    ensure_ascii=False,
                ),
            },
        )
    plugins = (
        [] if data.get("external_telegram") else active_instructions(user_id, access.available)
    )
    schedule = ""
    if "schedule" in access.available:
        zone = data["_schedule_origin"]["zone"]
        local = datetime.now(ZoneInfo(zone)).isoformat(timespec="seconds")
        schedule = render_prompt(
            "context/schedule_clock.md", {"SCHEDULE_NOW": local, "SCHEDULE_ZONE": zone}
        )
    checkpoint = data.get("_context_checkpoint")
    checkpoint_prompt = (
        render_prompt(
            "context/context_checkpoint.md",
            {
                "CONTEXT_CHECKPOINT": json.dumps(checkpoint, ensure_ascii=False).replace(
                    "<", r"\u003c"
                )
            },
        )
        if checkpoint
        else ""
    )
    sections = (
        render_prompt(
            "prompt.md",
            {"currentDateTime": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        ),
        render_user_md_with_settings(user_id, metadata, data.get("telegram_context"))
        if not data.get("external_telegram")
        else require_prompt("context/secretary.md"),
        render_prompt(
            "context/capabilities.md",
            {
                "CAPABILITIES_JSON": json.dumps(catalog, ensure_ascii=False),
                "SELECTED_SKILLS": json.dumps(selected, ensure_ascii=False),
            },
        ),
        render_active_mind_prompt(data.get("active_mind")),
        project_context,
        schedule,
        checkpoint_prompt,
        render_prompt(
            "context/referenced_sessions.md", {"SESSIONS": tag_safe_json(reference_frames)}
        ) if reference_frames else "",
        render_prompt(
            "context/agent_plugins.md", {"AGENT_PLUGINS": json.dumps(plugins, ensure_ascii=False)}
        )
        if plugins
        else "",
        render_prompt(
            "context/project_memory.md",
            {
                "PROJECT_MEMORY": json.dumps(
                    {"project": memory["project"], "chats": memory["chats"]}, ensure_ascii=False
                )
            },
        )
        if memory
        else "",
        render_prompt(
            "context/mind_skills.md",
            {
                "MIND_SKILLS": json.dumps(mind["custom_skills"], ensure_ascii=False),
            },
        )
        if mind.get("custom_skills")
        else "",
        render_prompt(
            "context/imported_skill_catalog.md",
            {"SKILLS": json.dumps(skill_catalog, ensure_ascii=False).replace("<", r"\u003c")},
        )
        if skill_catalog
        else "",
        render_telegram_context_prompt(data),
        render_beatbox_state_prompt(data) if "beatbox" in access.available else "",
    )
    bundle = PromptBundle(
        sections,
        access,
        selected,
        {},
        data.get("canvas_textdoc"),
        project_files,
        imported,
        workspace_id,
        invoked,
        references,
    )
    preload = set(selected)
    if "web" in access.available:
        preload.add("web")
    if project_files and "files" in access.available:
        preload.add("files")
    if (checkpoint or references) and "chat_memory" in access.available:
        preload.add("chat_memory")
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
