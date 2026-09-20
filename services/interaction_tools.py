from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field

from services.tool_protocol import ModelToolResult


def panel_event(kind: str, state: dict) -> list[dict]:
    encoded = base64.b64encode(json.dumps(state, ensure_ascii=False).encode()).decode()
    return [
        {
            "reply_part": f'\n\n<tool_panel data-kind="{kind}" data-b64="{encoded}"></tool_panel>\n\n'
        },
        {"widget_update": {"tag": kind, "state": state}},
    ]


def readable_panel_history(text: str) -> str:
    def replace(match: re.Match) -> str:
        try:
            state = json.loads(base64.b64decode(match[2], validate=True).decode())
            return json.dumps({"chat_panel": match[1], "content": state}, ensure_ascii=False)
        except (ValueError, UnicodeError):
            return ""

    return re.sub(
        r'<tool_panel data-kind="(plan|questions)" data-b64="([A-Za-z0-9+/=]{1,32000})"></tool_panel>',
        replace,
        text,
    )


@dataclass
class InteractionState:
    plan: list[dict] = field(default_factory=list)
    question_asked: bool = False

    def execute(self, name: str, arguments: dict) -> ModelToolResult:
        if name == "plan_update":
            steps = arguments["steps"]
            ids = [step["id"] for step in steps]
            if (
                len(ids) != len(set(ids))
                or sum(step["status"] == "in_progress" for step in steps) > 1
            ):
                return ModelToolResult({"ok": False, "error": "invalid_plan"})
            self.plan = [dict(step) for step in steps]
            state = {"id": "response-plan", "title": arguments["title"], "steps": self.plan}
            return ModelToolResult(
                {"ok": True, "steps": len(steps)}, events=panel_event("plan", state)
            )
        questions = arguments["questions"]
        ids = [question["id"] for question in questions]
        if (
            self.question_asked
            or len(ids) != len(set(ids))
            or any(
                len(question["options"]) != len(set(question["options"])) for question in questions
            )
        ):
            return ModelToolResult({"ok": False, "error": "invalid_questions"})
        self.question_asked = True
        state = {"id": "response-questions", "title": arguments["title"], "questions": questions}
        return ModelToolResult(
            {"ok": True, "awaiting_user": True}, events=panel_event("questions", state)
        )
