from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from backend.services.chat.cancellation import GenerationStopped
from backend.services.tools.model_runtime import IMPORTED_SKILL_TOOLS, ModelRuntime, tool_call_key
from backend.services.tools.tool_protocol import (
    ModelToolResult,
)

logger = logging.getLogger(__name__)
VOLATILE_TOOLS = {"list_subagent_models", "chat_reference_read"}
TOOL_BATCH_ARGUMENT = {
    "web_search_batch": "queries",
    "github_read_files": "paths",
    "github_search_code": "paths",
    "delegate_tasks": "tasks",
}


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: Any
    provider_id: str | None = None


@dataclass
class ToolExecution:
    runtime: ModelRuntime
    attempted: int = 0
    completed: dict[str, ModelToolResult] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)

    @property
    def exhausted(self) -> bool:
        return (
            self.attempted >= self.runtime.agent_settings["maxToolCalls"]
            or time.monotonic() - self.started_at >= self.runtime.agent_settings["toolTimeSeconds"]
        )

    def execute(self, call: ToolCall, index: int) -> ModelToolResult:
        if self.runtime.generation_control is not None:
            self.runtime.generation_control.check()
        if time.monotonic() - self.started_at >= self.runtime.agent_settings["toolTimeSeconds"]:
            return ModelToolResult(
                {"ok": False, "error": "tool_time_limit_reached", "executed": False}
            )
        if index >= self.runtime.agent_settings["maxToolCallsPerStep"] or self.exhausted:
            return ModelToolResult(
                {"ok": False, "error": "tool_call_limit_reached", "executed": False}
            )
        arguments = call.arguments if isinstance(call.arguments, dict) else {}
        batch = arguments.get(TOOL_BATCH_ARGUMENT.get(call.name, ""))
        cost = max(1, min(5, len(batch))) if isinstance(batch, list) else 1
        if self.attempted + cost > self.runtime.agent_settings["maxToolCalls"]:
            self.attempted = self.runtime.agent_settings["maxToolCalls"]
            return ModelToolResult(
                {"ok": False, "error": "tool_call_limit_reached", "executed": False}
            )
        self.attempted += cost
        try:
            state: Any = (
                self.runtime.canvas if call.name in {"canvas_read", "canvas_export"} else None
            )
            if call.name in {"file_list", "file_glob", "file_search_all", "shell_execute", "shell_pipeline"}:
                state = [item.get("path") for item in self.runtime.files]
            key = tool_call_key(call.name, {"arguments": call.arguments, "canvas": state})
            previous = self.completed.get(key)
            if self.failures.get(key, 0) >= 2:
                return ModelToolResult(
                    {"ok": False, "error": "repeated_tool_failure", "executed": False}
                )
            if previous is not None:
                return ModelToolResult(
                    {**previous.output, "reused": True},
                    sources=previous.sources,
                    model_artifacts=previous.model_artifacts,
                )
            result = self.runtime.execute(call.name, call.arguments)
            if (
                result.output.get("ok") is True
                and call.name != "plan_update"
                and call.name not in VOLATILE_TOOLS
                and call.name not in IMPORTED_SKILL_TOOLS
            ):
                self.completed[key] = result
            elif (
                result.output.get("ok") is not True
                and result.output.get("error") != "skill_required"
                and call.name not in VOLATILE_TOOLS
            ):
                self.failures[key] = self.failures.get(key, 0) + 1
            known = {item.get("path") for item in self.runtime.files}
            for item in result.reusable_files:
                if item.get("path") and item["path"] not in known:
                    self.runtime.files.append(item)
                    known.add(item["path"])
            return result
        except GenerationStopped:
            raise
        except Exception:
            logger.exception("Tool execution failed: %s", call.name)
            return ModelToolResult({"ok": False, "error": "tool_execution_failed"})
