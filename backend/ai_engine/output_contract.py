from __future__ import annotations

import re


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
