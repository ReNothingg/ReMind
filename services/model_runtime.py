from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_engine.prompt_builder import PromptBundle, build_prompt_bundle
from ai_engine.skills import SKILLS, WIDGET_SKILLS, function_skill
from services.canvas_tools import normalize_canvas_textdoc
from services.model_tools import execute_model_tool
from services.presentation_tools import render_visualization, render_widget, write_canvas
from services.python_runner import available_input_files, resolve_input_files
from services.tool_protocol import ModelToolResult

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

    @classmethod
    def create(cls, user_id: int | None, data: dict[str, Any]) -> ModelRuntime:
        bundle = build_prompt_bundle(user_id, data)
        raw_schemas = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        schemas = {schema["name"]: schema for schema in raw_schemas}
        expected = {name for skill in SKILLS for name in skill.functions} | {"read_skill"}
        if len(schemas) != len(raw_schemas) or set(schemas) != expected:
            raise ValueError("invalid_tool_schema_registry")
        return cls(
            user_id,
            bundle,
            [dict(item) for item in (data.get("files") or []) if isinstance(item, dict)],
            not bool(data.get("temporary_chat")),
            normalize_canvas_textdoc(data.get("canvas_textdoc")),
            schemas,
        )

    def declarations(self) -> list[dict[str, Any]]:
        available = self.prompts.access.available
        if not available:
            return []
        names = {
            function for skill in SKILLS if skill.id in available for function in skill.functions
        } | {"read_skill"}
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
        if name not in {declaration["name"] for declaration in self.declarations()}:
            return ModelToolResult({"ok": False, "error": "tool_not_available"})
        if (
            not isinstance(arguments, dict)
            or len(json.dumps(arguments, ensure_ascii=False, default=str).encode()) > 1_100_000
        ):
            return ModelToolResult({"ok": False, "error": "invalid_tool_arguments"})
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
        if name == "generate_demo_image":
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
                allow_artifacts=self.allow_artifacts,
            )
        for event in result.events:
            if "canvas_textdoc" in event:
                self.canvas = event["canvas_textdoc"]
        return result
