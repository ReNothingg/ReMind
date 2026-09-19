from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ai_engine.prompt_templates import require_prompt

MAX_TOOL_ROUNDS = 10
MAX_TOOL_CALLS_PER_ROUND = 4
MAX_TOOL_CALLS_TOTAL = 16
MAX_TOOL_OUTPUT_CHARS = 48_000


@dataclass(slots=True)
class ModelToolResult:
    output: dict[str, Any]
    events: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    model_artifacts: list[dict[str, Any]] = field(default_factory=list)
    reusable_files: list[dict[str, Any]] = field(default_factory=list)


def serialize_tool_output(output: dict[str, Any]) -> str:
    envelope = {
        **output,
        "security": require_prompt("context/tool_result.md"),
    }
    serialized = json.dumps(envelope, ensure_ascii=False, default=str)
    if len(serialized) <= MAX_TOOL_OUTPUT_CHARS:
        return serialized
    return json.dumps(
        {
            "security": envelope["security"],
            "truncated": True,
            "output_preview": serialized[: MAX_TOOL_OUTPUT_CHARS // 4],
        },
        ensure_ascii=False,
    )
