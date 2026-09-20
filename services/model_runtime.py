from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai_engine.prompt_builder import PromptBundle, build_prompt_bundle
from ai_engine.skills import SKILLS, WIDGET_SKILLS, function_skill
from services.artifact_workspace import ArtifactWorkspace
from services.canvas_tools import normalize_canvas_textdoc
from services.data_tools import execute_data_tool
from services.document_tools import execute_document_tool
from services.files import restore_stored_file_for_model
from services.interaction_tools import InteractionState
from services.model_tools import execute_model_tool
from services.presentation_tools import render_visualization, render_widget, write_canvas
from services.python_runner import available_input_files, resolve_input_files
from services.research_tools import ResearchSession, navigation_url_key
from services.tool_protocol import ModelToolResult
from services.tool_validation import argument_errors

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "ai_engine" / "tool_schemas.json"


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

    def __post_init__(self):
        self.workspace = ArtifactWorkspace(self.user_id, self.allow_artifacts)

    @classmethod
    def create(cls, user_id: int | None, data: dict[str, Any]) -> ModelRuntime:
        bundle = build_prompt_bundle(user_id, data)
        raw_schemas = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        schemas = {schema["name"]: schema for schema in raw_schemas}
        expected = {name for skill in SKILLS for name in skill.functions} | {"read_skill"}
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
            files,
            not bool(data.get("temporary_chat")),
            normalize_canvas_textdoc(data.get("canvas_textdoc")),
            schemas,
        )
        runtime.research.rate_key = str(data.get("tool_rate_key") or f"user_{user_id}")[:180]
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
        if not available:
            return []
        names = {
            function for skill in SKILLS if skill.id in available for function in skill.functions
        } | {"read_skill"}
        if self.user_id is None or not self.allow_artifacts:
            names -= {"file_write", "file_edit", "canvas_export"}
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
            elif name in {"image_crop", "image_tile"}:
                properties["filename"]["enum"] = image_names
            elif name == "render_widget":
                properties["format"]["enum"] = [
                    kind for kind, skill in WIDGET_SKILLS.items() if skill in available
                ]
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
        artifact_slots = max(0, 20 - self.artifact_count)
        if not artifact_slots and (
            name in {"file_write", "file_edit", "canvas_export"}
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
            from ai_engine.demo_image import demo_image_stream

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
        self.artifact_count += sum(
            len(event.get("python_artifacts") or []) for event in result.events
        )
        for event in result.events:
            if "canvas_textdoc" in event:
                self.canvas = event["canvas_textdoc"]
        return result
