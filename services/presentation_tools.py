from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from services.beatbox_tools import normalize_beatbox_state
from services.canvas_tools import MAX_TEXTDOC_CONTENT_LENGTH, apply_canmore_call
from services.python_runner import resolve_input_files
from services.tool_protocol import ModelToolResult

MAX_VISUALIZATION_BYTES = 768 * 1024
MAX_WIDGET_BYTES = 240_000


def _content(arguments: dict[str, Any], files: list[dict], key: str, maximum: int) -> str:
    value = arguments.get(key)
    filename = arguments.get("filename")
    if bool(value) == bool(filename):
        raise ValueError("provide_content_or_filename")
    if filename:
        if not isinstance(filename, str):
            raise ValueError("invalid_filename")
        matches = [path for name, path in resolve_input_files(files) if name == filename]
        if len(matches) != 1 or matches[0].suffix.lower() not in {
            ".html",
            ".htm",
            ".txt",
            ".md",
            ".py",
            ".js",
            ".ts",
            ".css",
            ".json",
        }:
            raise ValueError("file_not_available")
        with matches[0].open("rb") as handle:
            raw = handle.read(maximum + 1)
        if len(raw) > maximum:
            raise ValueError("content_too_large")
        value = raw.decode("utf-8-sig")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("empty_content")
    if len(value.encode("utf-8")) > maximum:
        raise ValueError("content_too_large")
    return value


def render_visualization(arguments: dict[str, Any], files: list[dict]) -> ModelToolResult:
    try:
        content = _content(arguments, files, "html", MAX_VISUALIZATION_BYTES)
        title = arguments.get("title")
        mode = arguments.get("mode", "normal")
        if (
            not isinstance(title, str)
            or not title.strip()
            or len(title) > 120
            or any(char in title for char in "\r\n`<>")
        ):
            raise ValueError("invalid_title")
        if not isinstance(mode, str) or mode not in {"normal", "wide"}:
            raise ValueError("invalid_visualization_mode")
        if re.search(r"(?im)^\s*`{3,}\s*$", content):
            raise ValueError("bare_markdown_fence_in_fragment")
        if re.search(r"<\s*canmore\b|canmore\.(?:create|update|comment)_textdoc", content, re.I):
            raise ValueError("reserved_protocol_marker_in_fragment")
        if not re.search(r"<[a-zA-Z][^>]*>", content) or re.search(
            r"(?i)<\s*(?:!doctype|html\b|head\b|body\b|iframe\b|object\b|embed\b|base\b)", content
        ):
            raise ValueError("html_fragment_required")
    except (OSError, UnicodeError, ValueError) as exc:
        return ModelToolResult(
            {"ok": False, "error": str(exc) if isinstance(exc, ValueError) else "file_read_failed"}
        )
    language = "visualize-wide" if mode == "wide" else "visualize"
    wire = f"\n\n```{language}:{title.strip()}\n{content}\n```\n\n"
    return ModelToolResult(
        {
            "ok": True,
            "published": True,
            "title": title.strip(),
            "validation": "structure_only",
            "runtime_tested": False,
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
        },
        events=[{"reply_part": wire}],
    )


def write_canvas(
    arguments: dict[str, Any], files: list[dict], current: dict | None
) -> ModelToolResult:
    try:
        content = _content(arguments, files, "content", MAX_TEXTDOC_CONTENT_LENGTH)
        action = arguments.get("action", "create")
        if not isinstance(action, str) or action not in {"create", "replace"}:
            raise ValueError("invalid_canvas_action")
        if action == "replace" and not current:
            raise ValueError("canvas_not_open")
        name = arguments.get("name")
        kind = arguments.get("type")
        if not isinstance(name, str) or not name.strip() or len(name) > 140:
            raise ValueError("invalid_canvas_name")
        if not isinstance(kind, str) or not re.fullmatch(r"document|code/[a-z0-9_+-]{1,32}", kind):
            raise ValueError("invalid_canvas_type")
        update = apply_canmore_call(
            {
                "function": "create_textdoc",
                "arguments": {"name": name, "type": kind, "content": content},
            },
            current,
        )
        if not update:
            raise ValueError("invalid_canvas_document")
        if action == "replace":
            if current is None:
                raise ValueError("canvas_not_open")
            update["textdoc"]["id"] = current["id"]
            update["action"] = "update_textdoc"
    except (OSError, UnicodeError, ValueError) as exc:
        return ModelToolResult(
            {"ok": False, "error": str(exc) if isinstance(exc, ValueError) else "file_read_failed"}
        )
    document = update["textdoc"]
    return ModelToolResult(
        {
            "ok": True,
            "published": True,
            "id": document["id"],
            "name": document["name"],
            "type": document["type"],
            "characters": len(content),
            "runtime_tested": False,
        },
        events=[{"canvas_update": update, "canvas_textdoc": document}],
    )


def render_widget(arguments: dict[str, Any]) -> ModelToolResult:
    kind = arguments.get("format")
    content = arguments.get("content")
    if (
        not isinstance(kind, str)
        or kind not in {"chartjs", "d3js", "mermaid", "nomnoml", "beatbox", "quiz"}
        or not isinstance(content, str)
    ):
        return ModelToolResult({"ok": False, "error": "invalid_widget"})
    if (
        not content.strip()
        or len(content.encode("utf-8")) > MAX_WIDGET_BYTES
        or re.search(r"(?m)^\s*`{3,}\s*$", content)
    ):
        return ModelToolResult({"ok": False, "error": "invalid_widget_content"})
    if kind in {"chartjs", "d3js", "beatbox", "quiz"}:
        try:
            value = json.loads(content)
        except (ValueError, TypeError, RecursionError):
            return ModelToolResult({"ok": False, "error": "invalid_widget_json"})
        if not isinstance(value, dict):
            return ModelToolResult({"ok": False, "error": "widget_object_required"})
        pending = [value]
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                if any(key in {"__proto__", "constructor", "prototype"} for key in item):
                    return ModelToolResult({"ok": False, "error": "unsafe_widget_property"})
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
            elif isinstance(item, float) and not math.isfinite(item):
                return ModelToolResult({"ok": False, "error": "non_finite_widget_value"})
        if kind == "chartjs":
            if not isinstance(value.get("type"), str) or value.get("type") not in {
                "bar",
                "line",
                "pie",
                "doughnut",
                "radar",
                "polarArea",
                "bubble",
                "scatter",
            }:
                return ModelToolResult({"ok": False, "error": "unsupported_chart_type"})
            data = value.get("data")
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("datasets"), list)
                or not data["datasets"]
            ):
                return ModelToolResult({"ok": False, "error": "chart_datasets_required"})
        if kind == "d3js":
            if (
                not isinstance(value.get("type"), str)
                or value.get("type") not in {"bar", "line", "pie", "scatter"}
                or not isinstance(value.get("data"), list)
                or not value["data"]
            ):
                return ModelToolResult({"ok": False, "error": "invalid_d3_chart"})

        if kind in {"chartjs", "d3js"} and (
            not value.get("type") or not isinstance(value.get("data"), (dict, list))
        ):
            return ModelToolResult({"ok": False, "error": "chart_type_and_data_required"})
        if kind == "beatbox":
            value = normalize_beatbox_state(value)
            if value is None:
                return ModelToolResult({"ok": False, "error": "beatbox_tracks_required"})
        if kind == "quiz" and (
            not isinstance(value.get("cards"), list)
            or not value["cards"]
            or len(value["cards"]) > 100
        ):
            return ModelToolResult({"ok": False, "error": "quiz_cards_required"})
        if kind == "quiz":
            for card in value["cards"]:
                if (
                    not isinstance(card, dict)
                    or not isinstance(card.get("question"), str)
                    or not card["question"].strip()
                    or not isinstance(card.get("choices"), list)
                    or not 2 <= len(card["choices"]) <= 12
                    or any(
                        not isinstance(choice, str) or not choice.strip()
                        for choice in card["choices"]
                    )
                    or type(card.get("correct_index")) is not int
                    or not 0 <= card["correct_index"] < len(card["choices"])
                ):
                    return ModelToolResult({"ok": False, "error": "invalid_quiz_card"})
        content = (
            json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
        )
    wire = (
        f"\n\n<{kind}>{content}</{kind}>\n\n"
        if kind in {"beatbox", "quiz"}
        else f"\n\n```{kind}\n{content}\n```\n\n"
    )
    return ModelToolResult(
        {"ok": True, "published": True, "format": kind, "runtime_tested": False},
        events=[{"reply_part": wire}],
    )
