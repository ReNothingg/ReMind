from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ReplyPreview:
    length: int = 0
    blocked: bool = False

    def append(self, text):
        if self.blocked or not isinstance(text, str):
            return None
        visible = text[: 32_000 - self.length]
        if not visible:
            return None
        self.length += len(visible)
        return {"reply_preview": visible}

    def clear(self, *, block=False):
        self.blocked = self.blocked or block
        if not self.length:
            return None
        self.length = 0
        return {"reply_preview": None}


def output_contract_errors(text: str) -> tuple[str, ...]:
    errors = []
    if re.search(r"<\s*(?:think\b|tool_panel\b|\w+_activity\b)", text, re.I):
        errors.append("reserved_activity_marker")
    if re.search(r"[\ue200\ue201\ue202]visualize\b", text) or re.search(
        r"\[.*?\]\((?:/tmp/|/private/tmp/|sandbox:/).*?\.html\)", text
    ):
        errors.append("unpublished_visualization_reference")
    if re.search(
        r"```\s*(?:visualize(?:-wide)?|canmore)\b|<\s*(?:visualize|canmore)\b|canmore\.(?:create|update|comment)_textdoc",
        text,
        re.I,
    ):
        errors.append("native_publishing_call_required")
    return tuple(errors)
