from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.agent_profile import (
    SUBAGENT_MODEL_ID_LIMIT,
    normalize_agent_runtime,
    supports_delegation,
)
from backend.ai_engine.compaction import compaction_turn
from backend.ai_engine.prompt_builder import PromptBundle, build_prompt_bundle
from backend.ai_engine.prompt_templates import render_prompt, require_prompt
from backend.ai_engine.skills import SKILLS, WIDGET_SKILLS, function_skill
from backend.db.models import db
from backend.errors import ApiError
from backend.services import project_patches
from backend.services.agent_models import EFFORTS
from backend.services.agent_runtime_settings import load_agent_runtime
from backend.services.agent_skills import skill_content, skill_script_source
from backend.services.chat.session_references import read_reference
from backend.services.files import restore_stored_file_for_model
from backend.services.python_runner import (
    available_input_files,
    execute_workspace_pipeline,
    execute_workspace_shell,
    python_runner_available,
    resolve_input_files,
)
from backend.services.tools.artifact_workspace import ArtifactWorkspace
from backend.services.tools.automation_tools import SCHEDULE_TOOLS, execute_schedule_tool
from backend.services.tools.canvas_tools import normalize_canvas_textdoc
from backend.services.tools.chat_memory_tools import CHAT_MEMORY_TOOLS, execute_chat_memory
from backend.services.tools.data_tools import execute_data_tool
from backend.services.tools.delegation import DelegationChild, DelegationRoute, DelegationTree
from backend.services.tools.document_tools import execute_document_tool
from backend.services.tools.interaction_tools import InteractionState, panel_event
from backend.services.tools.model_tools import execute_model_tool
from backend.services.tools.presentation_tools import (
    render_visualization,
    render_widget,
    write_canvas,
)
from backend.services.tools.research_tools import ResearchSession, navigation_url_key
from backend.services.tools.skill_access import SkillAccess
from backend.services.tools.slide_deck import create_presentation
from backend.services.tools.tool_protocol import ModelToolResult
from backend.services.tools.tool_validation import argument_errors
from backend.services.web_research_settings import load_web_research

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "ai_engine" / "tool_schemas.json"
IMPORTED_SKILL_TOOLS = {"skill", "skill_resource", "skill_script"}


def tool_call_key(name: str, arguments: dict[str, Any]) -> str:
    encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str).encode()
    return f"{name}:{hashlib.sha256(encoded).hexdigest()}"


@dataclass
class ModelRuntime:
    user_id: int | None
    prompts: PromptBundle
    files: list[dict[str, Any]]
    allow_artifacts: bool
    canvas: dict | None
    schemas: dict[str, dict]
    research: ResearchSession = field(default_factory=ResearchSession)
    interaction: InteractionState = field(default_factory=InteractionState)
    workspace: ArtifactWorkspace = field(init=False)
    artifact_count: int = 0
    agent_settings: dict[str, Any] = field(default_factory=lambda: normalize_agent_runtime(None))
    schedule_context: dict[str, str] | None = None
    generation_control: Any = None
    context_archive: tuple[dict, ...] = ()
    reference_destination: str | None = None
    delegation: DelegationTree | None = None
    delegation_depth: int = 0
    delegation_route: DelegationRoute | None = None
    loaded_skills: set[str] = field(default_factory=set)
    patch_origin: tuple[str, str] | None = None

    def __post_init__(self):
        self.workspace = ArtifactWorkspace(self.user_id, self.allow_artifacts)

    @property
    def step_limit(self):
        return self.agent_settings["maxSteps"]

    @classmethod
    def create(cls, user_id: int | None, data: dict[str, Any]) -> ModelRuntime:
        if compaction_turn(data):
            bundle = PromptBundle(
                (require_prompt("context/summarize_checkpoint_system.md"),),
                SkillAccess(frozenset(), {}),
                (),
                {},
            )
            runtime = cls(user_id, bundle, [], False, None, {})
            runtime.agent_settings.update(maxSteps=0, maxToolCalls=0)
            runtime.generation_control = data.get("_generation_control")
            return runtime
        data.pop("_invoked_skill_context", None)
        options = load_agent_runtime(user_id)
        child = data.get("_delegation")
        route = DelegationRoute(
            data.get("model") or "", data.get("thinkingLevel") or data.get("thinking_level")
        )
        model = options["subagentModel"] or route.model
        enabled = set()
        if isinstance(child, DelegationChild) and child.tree.owner == user_id:
            tree = child.tree
            depth = child.depth
            if depth < min(tree.max_depth, options["subagentMaxDepth"]):
                enabled.add("subagents")
            bundle = PromptBundle(
                (require_prompt("context/delegated_task.md"),),
                SkillAccess(frozenset(enabled), {}),
                (),
                {},
            )
            if enabled:
                bundle.load("subagents")
            options.update(maxSteps=2, maxToolCallsPerStep=1, maxToolCalls=3, toolTimeSeconds=35)
        else:
            depth, tree = 0, None
            if user_id and data.get("_context_is_private_web") is True:
                if options["shellEnabled"] and python_runner_available(user_id):
                    enabled.add("shell")
                if options["subagentMaxDepth"] and (
                    supports_delegation(model)
                    or (options["subagentModelSelection"] and options["subagentAllowedModels"])
                ):
                    enabled.add("subagents")
                    tree = DelegationTree(
                        user_id, options["subagentMaxDepth"], options["subagentMaxActive"]
                    )
            bundle = build_prompt_bundle(user_id, data, execution_skills=frozenset(enabled))
        raw_schemas = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        schemas = {schema["name"]: schema for schema in raw_schemas}
        expected = {name for skill in SKILLS for name in skill.functions} | {"read_skill"} | IMPORTED_SKILL_TOOLS
        if len(schemas) != len(raw_schemas) or set(schemas) != expected:
            raise ValueError("invalid_tool_schema_registry")
        files = [dict(item) for item in (data.get("files") or []) if isinstance(item, dict)]
        known = {item.get("url_path") for item in files}
        if data.get("history_is_canonical"):
            remaining = 8 * 1024 * 1024
            for message in reversed(data.get("history") or []):
                for part in message.get("parts", []) if isinstance(message, dict) else []:
                    attachment = (
                        (part.get("file") or part.get("image")) if isinstance(part, dict) else None
                    )
                    if (
                        not isinstance(attachment, dict)
                        or attachment.get("url_path") in known
                        or len(files) >= 24
                    ):
                        continue
                    restored = restore_stored_file_for_model(attachment, max_bytes=remaining)
                    if restored:
                        files.append(restored)
                        known.add(attachment.get("url_path"))
                        remaining -= int(restored.get("size") or 0)
        runtime = cls(
            user_id,
            bundle,
            [*files, *bundle.project_files],
            not bool(data.get("temporary_chat")),
            normalize_canvas_textdoc(data.get("canvas_textdoc")),
            schemas,
        )
        runtime.agent_settings = options
        if bundle.invoked_skill is not None:
            runtime.loaded_skills.add(bundle.invoked_skill["name"])
            rendered = json.dumps(bundle.invoked_skill, ensure_ascii=False).replace("<", r"\u003c")
            data["_invoked_skill_context"] = render_prompt("context/invoked_skill.md", {"SKILL": rendered})
        runtime.delegation = tree
        runtime.delegation_depth = depth
        runtime.delegation_route = route if tree is not None else None
        runtime.schedule_context = data.get("_schedule_origin")
        if (
            bundle.project_id
            and data.get("_context_is_private_web") is True
            and not data.get("_automation")
            and not data.get("telegram_agent")
            and runtime.allow_artifacts
            and isinstance(data.get("session_id"), str)
            and isinstance(data.get("request_id"), str)
        ):
            runtime.patch_origin = (data["session_id"], data["request_id"])
        runtime.generation_control = data.get("_generation_control")
        runtime.context_archive = tuple(data.get("_context_archive") or ())
        if bundle.chat_references:
            runtime.reference_destination = data.get("session_id")
        runtime.research.rate_key = str(data.get("tool_rate_key") or f"user_{user_id}")[:180]
        if "web" in bundle.access.available:
            runtime.research.settings = load_web_research(user_id)
            runtime.research.control = runtime.generation_control
        user_text = str(data.get("message") or "")
        if data.get("history_is_canonical"):
            for message in (data.get("history") or [])[-40:]:
                if not isinstance(message, dict):
                    continue
                if message.get("role") == "user":
                    user_text += "\n" + "\n".join(
                        str(part.get("text") or "")
                        for part in message.get("parts", [])
                        if isinstance(part, dict)
                    )
                for source in message.get("sources") or []:
                    if isinstance(source, dict) and isinstance(source.get("url"), str):
                        runtime.research.allowed_urls.add(navigation_url_key(source["url"]))
        for match in re.findall(r'https?://[^\s<>"\']+', user_text):
            runtime.research.allowed_urls.add(navigation_url_key(match.rstrip(".,;!")))
        return runtime

    def declarations(self) -> list[dict[str, Any]]:
        available = self.prompts.access.available
        imported = {
            name for name, item in self.prompts.imported_skills.items()
            if item["modelInvocable"] or name in self.loaded_skills
        }
        if not available and not imported:
            return []
        names = {
            function for skill in SKILLS if skill.id in available for function in skill.functions
        }
        if available:
            names.add("read_skill")
        if imported:
            names.update({"skill", "skill_resource"})
        script_paths = {
            name: self.prompts.imported_skills[name]["scriptPaths"]
            for name in imported & self.loaded_skills
            if self.prompts.imported_skills[name].get("scriptPaths")
        }
        if "shell" in available and script_paths:
            names.add("skill_script")
        if self.patch_origin is None:
            names.discard("apply_patch")
        if not self.agent_settings["subagentModelSelection"]:
            names.discard("list_subagent_models")
        if not self.context_archive:
            names.difference_update(CHAT_MEMORY_TOOLS)
        if not self.prompts.chat_references:
            names.discard("chat_reference_read")
        if self.user_id is None or not self.allow_artifacts:
            names -= {"file_write", "file_edit", "canvas_export", "create_presentation"}
        image_names = [
            name
            for name, path in resolve_input_files(self.files)
            if path.suffix.lower() in {".jpeg", ".jpg", ".png", ".webp"}
        ]
        if not image_names:
            names -= {"image_crop", "image_tile"}
        declarations = []
        for name, schema in self.schemas.items():
            if name not in names:
                continue
            declaration = deepcopy(schema)
            properties = declaration["parameters"]["properties"]
            if name == "read_skill":
                properties["skill_id"]["enum"] = sorted(available)
            elif name == "chat_reference_read":
                properties["session_id"]["enum"] = [item["session_id"] for item in self.prompts.chat_references]
            elif name == "skill_script":
                properties["name"]["enum"] = sorted(script_paths)
                properties["path"]["enum"] = sorted(
                    {path for paths in script_paths.values() for path in paths}
                )
            elif name in IMPORTED_SKILL_TOOLS:
                properties["name"]["enum"] = sorted(imported)
            elif name in {"image_crop", "image_tile"}:
                properties["filename"]["enum"] = image_names
            elif name == "render_widget":
                properties["format"]["enum"] = [
                    kind for kind, skill in WIDGET_SKILLS.items() if skill in available
                ]
            elif name == "shell_execute":
                input_names = available_input_files(self.files)
                if input_names:
                    properties["files"]["items"]["enum"] = input_names
                else:
                    properties["command"]["enum"] = ["ls"]
            elif name == "delegate_tasks" and self.agent_settings["subagentModelSelection"]:
                task = properties["tasks"]["items"]["properties"]
                task["model"] = {
                    "type": "string",
                    "maxLength": SUBAGENT_MODEL_ID_LIMIT,
                    "description": "Exact route id returned by list_subagent_models. Omit to use the configured model.",
                }
                task["reasoning_effort"] = {
                    "type": "string",
                    "enum": ["", *EFFORTS],
                    "description": "Optional supported reasoning effort. Requires an explicit model route.",
                }
            elif name == "python_execute":
                declaration["description"] = declaration["description"].replace(
                    "{{availableInputFiles}}",
                    json.dumps(available_input_files(self.files), ensure_ascii=False),
                )
            declarations.append(declaration)
        return declarations

    def execute(self, name: str, arguments: dict[str, Any]) -> ModelToolResult:
        declarations = {declaration["name"]: declaration for declaration in self.declarations()}
        if name not in declarations:
            return ModelToolResult({"ok": False, "error": "tool_not_available"})
        if (
            not isinstance(arguments, dict)
            or len(json.dumps(arguments, ensure_ascii=False, default=str).encode()) > 1_100_000
        ):
            return ModelToolResult({"ok": False, "error": "invalid_tool_arguments"})
        violations = argument_errors(arguments, declarations[name]["parameters"])
        if violations:
            return ModelToolResult(
                {"ok": False, "error": "invalid_tool_arguments", "details": violations}
            )
        if name == "read_skill":
            skill_id = arguments.get("skill_id")
            if not isinstance(skill_id, str) or skill_id not in self.prompts.access.available:
                return ModelToolResult({"ok": False, "error": "skill_unavailable"})
            self.prompts.load(skill_id)
            return ModelToolResult({"ok": True, "skill_id": skill_id, "instructions_loaded": True})
        if name == "skill_script":
            invoked = self.prompts.invoked_skill or {}
            script = skill_script_source(
                self.user_id,
                self.prompts.project_id,
                self.prompts.imported_skills[arguments["name"]],
                arguments["path"],
                user_invoked=invoked.get("name") == arguments["name"],
            )
            if script is None:
                return ModelToolResult({"ok": False, "error": "skill_script_not_found"})
            result = self._run_workspace_command(script, script_arguments=arguments.get("arguments", []))
            return self._record_result(result)
        if name in IMPORTED_SKILL_TOOLS:
            skill_name = arguments["name"]
            if name == "skill_resource" and skill_name not in self.loaded_skills:
                return ModelToolResult({"ok": False, "error": "skill_required", "name": skill_name})
            result = skill_content(
                self.user_id,
                self.prompts.project_id,
                self.prompts.imported_skills[skill_name],
                path=arguments.get("path") if name == "skill_resource" else None,
                offset=arguments.get("offset", 0),
            )
            if result["ok"] and name == "skill":
                self.loaded_skills.add(skill_name)
            return ModelToolResult(result)
        skill_id = function_skill(name, arguments)
        if skill_id not in self.prompts.access.available:
            return ModelToolResult({"ok": False, "error": "tool_not_available"})
        if skill_id not in self.prompts.instructions:
            return ModelToolResult(
                {
                    "ok": False,
                    "error": "skill_required",
                    "skill_id": skill_id,
                    "required_function": "read_skill",
                }
            )
        if name == "apply_patch" and self.patch_origin is not None:
            try:
                session_id, request_id = self.patch_origin
                proposal = project_patches.propose(
                    self.user_id, self.prompts.project_id, session_id, request_id, arguments["input"]
                )
                return ModelToolResult(
                    {"ok": True, "awaiting_user": True},
                    events=panel_event("workspace_patch", {"proposal_id": proposal.id, "workspace_id": proposal.workspace_id}),
                )
            except ApiError as error:
                db.session.rollback()
                return ModelToolResult({"ok": False, "error": error.code, **(error.extra or {})})
        artifact_slots = max(0, 20 - self.artifact_count)
        if not artifact_slots and (
            name in {"file_write", "file_edit", "canvas_export", "create_presentation"}
            or (name == "table_query" and arguments.get("export_filename"))
        ):
            return ModelToolResult({"ok": False, "error": "artifact_limit_reached"})
        if name in {"web_search", "web_search_batch", "web_fetch", "web_find", "web_links"}:
            result = self.research.execute(name, arguments)
        elif name in {"file_write", "file_edit", "canvas_export"}:
            result = self.workspace.execute(name, arguments, self.files, self.canvas)
        elif name in {"table_inspect", "table_query"}:
            result = execute_data_tool(name, arguments, self.files, self.workspace)
        elif name in {"plan_update", "ask_user"}:
            result = self.interaction.execute(name, arguments)
        elif name in SCHEDULE_TOOLS:
            result = execute_schedule_tool(self.user_id, self.schedule_context, name, arguments)
        elif name in CHAT_MEMORY_TOOLS:
            result = execute_chat_memory(self.context_archive, name, arguments)
        elif name == "chat_reference_read":
            result = ModelToolResult(read_reference(
                self.user_id, self.reference_destination, self.prompts.chat_references, arguments
            ))
        elif name == "list_subagent_models" and self.delegation is not None:
            result = self.delegation.models(self.delegation_depth)
        elif (
            name == "delegate_tasks"
            and self.delegation is not None
            and self.delegation_route is not None
        ):
            result = self.delegation.run(
                arguments["tasks"],
                self.delegation_depth,
                self.delegation_route,
                self.generation_control,
            )
        elif name == "shell_execute":
            result = ModelToolResult(
                execute_workspace_shell(
                    arguments,
                    user_id=self.user_id,
                    input_files=self.files,
                    timeout_ms=self.agent_settings["shellTimeoutMs"],
                    max_output_bytes=self.agent_settings["shellMaxOutputBytes"],
                ).output
            )
        elif name == "shell_pipeline":
            result = self._run_workspace_command(arguments["line"])
        elif name == "create_presentation":
            result = create_presentation(arguments, self.files, self.workspace)
        elif name in {
            "file_list",
            "file_read",
            "file_search",
            "file_search_all",
            "file_glob",
            "file_diff",
            "canvas_read",
            "canvas_edit",
        }:
            result = execute_document_tool(name, arguments, self.files, self.canvas)
        elif name == "generate_demo_image":
            if not self.allow_artifacts:
                return ModelToolResult(
                    {"ok": False, "error": "demo_image_requires_persistent_chat"}
                )
            prompt = arguments.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16000:
                return ModelToolResult({"ok": False, "error": "invalid_image_prompt"})
            from backend.ai_engine.demo_image import demo_image_stream

            events = [
                event
                for event in demo_image_stream(None, {"message": prompt})
                if "reply_part" not in event
            ]
            images = [
                image
                for event in events
                if isinstance(event, dict)
                for image in event.get("images", [])
            ]
            result = ModelToolResult(
                {"ok": bool(images), "demo": True, "images": images}, events=events
            )
        elif name == "render_visualization":
            result = render_visualization(arguments, self.files)
        elif name == "canvas_write":
            result = write_canvas(arguments, self.files, self.canvas)
        elif name == "render_widget":
            result = render_widget(arguments)
        else:
            result = execute_model_tool(
                name,
                arguments,
                user_id=self.user_id,
                input_files=self.files,
                allow_artifacts=self.allow_artifacts and artifact_slots > 0,
                artifact_limit=artifact_slots,
            )
        return self._record_result(result)

    def _run_workspace_command(self, source, *, script_arguments=None):
        settings = self.agent_settings if script_arguments is None else load_agent_runtime(self.user_id)
        if not settings["shellEnabled"]:
            return ModelToolResult({"ok": False, "error": "tool_not_available"})
        run = execute_workspace_pipeline(
            source,
            user_id=self.user_id,
            input_files=self.files,
            timeout_ms=settings["shellTimeoutMs"],
            max_output_bytes=settings["shellMaxOutputBytes"],
            allow_artifacts=self.allow_artifacts and self.artifact_count < 20,
            generation_control=self.generation_control,
            script_arguments=script_arguments,
        )
        return ModelToolResult(
            run.output,
            events=[{"python_artifacts": run.artifacts}] if run.artifacts else [],
            reusable_files=run.reusable_files,
        )

    def _record_result(self, result):
        self.artifact_count += sum(
            len(event.get("python_artifacts") or []) for event in result.events
        )
        for event in result.events:
            if "canvas_textdoc" in event:
                self.canvas = event["canvas_textdoc"]
        return result
