from __future__ import annotations

from dataclasses import dataclass

from backend.ai_engine.prompt_templates import require_prompt


@dataclass(frozen=True)
class SkillDefinition:
    id: str
    functions: tuple[str, ...]
    access: str = "web_client"
    title_key: str | None = None
    description_key: str | None = None
    hide_unavailable: bool = False

    @property
    def path(self) -> str:
        return f"skills/{self.id}/SKILL.md"

    def instructions(self) -> str:
        return require_prompt(self.path)

    def summary(self) -> str:
        paragraphs = self.instructions().split("\n\n")
        return next(
            (part.strip() for part in paragraphs if part.strip() and not part.startswith("#")), ""
        )


SKILLS = (
    SkillDefinition(
        "demo_image",
        ("generate_demo_image",),
        "demo_image",
        "composer.tools.image",
        "composer.tools.imageDemoDescription",
        True,
    ),
    SkillDefinition(
        "web",
        ("web_search", "web_search_batch", "web_fetch", "web_find", "web_links"),
        "web_search",
    ),
    SkillDefinition(
        "files",
        (
            "file_list",
            "file_read",
            "file_search",
            "file_search_all",
            "file_glob",
            "file_diff",
            "file_write",
            "file_edit",
            "apply_patch",
        ),
    ),
    SkillDefinition("data", ("table_inspect", "table_query")),
    SkillDefinition("workflow", ("plan_update", "ask_user")),
    SkillDefinition(
        "chat_memory",
        ("chat_history_search", "chat_history_read", "chat_reference_read"),
        "account",
        hide_unavailable=True,
    ),
    SkillDefinition(
        "schedule",
        ("schedule_create", "schedule_list", "schedule_view", "schedule_edit"),
        "account",
        hide_unavailable=True,
    ),
    SkillDefinition("slides", ("create_presentation",), "account"),
    SkillDefinition("visualize", ("render_visualization",)),
    SkillDefinition(
        "github",
        (
            "github_list_repositories",
            "github_get_repository_map",
            "github_read_file",
            "github_read_files",
            "github_search_code",
        ),
        "github",
    ),
    SkillDefinition("python", ("python_execute",), "python"),
    SkillDefinition(
        "shell", ("shell_execute", "shell_pipeline"), "account", "agentExecution.shell", "agentExecution.shellHint",
    ),
    SkillDefinition(
        "subagents", ("delegate_tasks", "list_subagent_models"), "account", "agentExecution.subagents", "agentExecution.subagentsDescription",
    ),
    SkillDefinition("image_analysis", ("image_crop", "image_tile"), "python"),
    SkillDefinition("canvas", ("canvas_write", "canvas_read", "canvas_edit", "canvas_export")),
    SkillDefinition("charts", ("render_widget",)),
    SkillDefinition("diagrams", ("render_widget",)),
    SkillDefinition("beatbox", ("render_widget",)),
    SkillDefinition("quiz", ("render_widget",)),
)
SKILL_BY_ID = {skill.id: skill for skill in SKILLS}
SKILL_IDS = tuple(SKILL_BY_ID)
WIDGET_SKILLS = {
    "chartjs": "charts",
    "d3js": "charts",
    "mermaid": "diagrams",
    "nomnoml": "diagrams",
    "beatbox": "beatbox",
    "quiz": "quiz",
}


def function_skill(name: str, arguments: dict) -> str | None:
    if name == "render_widget":
        widget_format = arguments.get("format")
        return WIDGET_SKILLS.get(widget_format) if isinstance(widget_format, str) else None
    return next((skill.id for skill in SKILLS if name in skill.functions), None)
