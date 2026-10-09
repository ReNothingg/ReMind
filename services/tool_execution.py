from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from services.model_runtime import ModelRuntime, tool_call_key
from services.tool_protocol import (
    MAX_TOOL_CALLS_PER_ROUND,
    MAX_TOOL_CALLS_TOTAL,
    MAX_TOOL_EXECUTION_SECONDS,
    ModelToolResult,
)

logger = logging.getLogger(__name__)


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
            self.attempted >= MAX_TOOL_CALLS_TOTAL
            or time.monotonic() - self.started_at >= MAX_TOOL_EXECUTION_SECONDS
        )

    def execute(self, call: ToolCall, index: int) -> ModelToolResult:
        if time.monotonic() - self.started_at >= MAX_TOOL_EXECUTION_SECONDS:
            return ModelToolResult(
                {"ok": False, "error": "tool_time_limit_reached", "executed": False}
            )
        if index >= MAX_TOOL_CALLS_PER_ROUND or self.exhausted:
            return ModelToolResult(
                {"ok": False, "error": "tool_call_limit_reached", "executed": False}
            )
        arguments = call.arguments if isinstance(call.arguments, dict) else {}
        cost = max(
            1,
            min(
                5,
                (
                    len(arguments.get("queries", []))
                    if call.name == "web_search_batch"
                    and isinstance(arguments.get("queries"), list)
                    else (
                        len(arguments.get("paths", []))
                        if call.name in {"github_read_files", "github_search_code"}
                        and isinstance(arguments.get("paths"), list)
                        else 1
                    )
                ),
            ),
        )
        if self.attempted + cost > MAX_TOOL_CALLS_TOTAL:
            self.attempted = MAX_TOOL_CALLS_TOTAL
            return ModelToolResult(
                {"ok": False, "error": "tool_call_limit_reached", "executed": False}
            )
        self.attempted += cost
        try:
            state: Any = (
                self.runtime.canvas if call.name in {"canvas_read", "canvas_export"} else None
            )
            if call.name in {"file_list", "file_glob", "file_search_all"}:
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
            if result.output.get("ok") is True and call.name != "plan_update":
                self.completed[key] = result
            elif (
                result.output.get("ok") is not True
                and result.output.get("error") != "skill_required"
            ):
                self.failures[key] = self.failures.get(key, 0) + 1
            known = {item.get("path") for item in self.runtime.files}
            for item in result.reusable_files:
                if item.get("path") and item["path"] not in known:
                    self.runtime.files.append(item)
                    known.add(item["path"])
            return result
        except Exception:
            logger.exception("Tool execution failed: %s", call.name)
            return ModelToolResult({"ok": False, "error": "tool_execution_failed"})
