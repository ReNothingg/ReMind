from __future__ import annotations

import json
import re
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

ALLOWED_CANMORE_FUNCTIONS = {
    "create_textdoc",
    "update_textdoc",
    "comment_textdoc",
}

MAX_TEXTDOC_NAME_LENGTH = 140
MAX_TEXTDOC_TYPE_LENGTH = 64
MAX_TEXTDOC_CONTENT_LENGTH = 240_000
MAX_TEXTDOC_COMMENTS = 80


@dataclass
class CanvasProcessingResult:
    reply: str
    textdoc: dict[str, Any] | None
    updates: list[dict[str, Any]]


def normalize_canvas_textdoc(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None

    if not isinstance(value, dict):
        return None

    name = _clean_string(value.get("name"), MAX_TEXTDOC_NAME_LENGTH)
    textdoc_type = _normalize_textdoc_type(value.get("type"))
    content = _clean_string(value.get("content"), MAX_TEXTDOC_CONTENT_LENGTH)
    if not name or not textdoc_type:
        return None

    comments = _normalize_comments(value.get("comments"))
    normalized = {
        "id": _clean_string(value.get("id"), 80) or _new_canvas_id(),
        "name": name,
        "type": textdoc_type,
        "content": content,
        "comments": comments,
        "updated_at": int(value.get("updated_at") or time.time()),
    }
    return normalized


def process_canmore_calls(raw_reply: str, current_textdoc: Any = None) -> CanvasProcessingResult:
    reply = str(raw_reply or "")
    textdoc = normalize_canvas_textdoc(current_textdoc)
    calls, spans = _extract_canmore_calls(reply)
    if not calls:
        return CanvasProcessingResult(
            reply=_strip_canmore_tool_text(reply), textdoc=textdoc, updates=[]
        )

    updates: list[dict[str, Any]] = []
    working_textdoc = deepcopy(textdoc)
    for call in calls:
        applied = _apply_canmore_call(call, working_textdoc)
        if not applied:
            continue
        working_textdoc = applied["textdoc"]
        updates.append(applied)

    clean_reply = _strip_canmore_tool_text(_remove_spans(reply, spans)).strip()
    return CanvasProcessingResult(reply=clean_reply, textdoc=working_textdoc, updates=updates)


def find_canmore_marker(text: str) -> int:
    haystack = str(text or "").lower()
    markers = [
        "```canmore",
        "<canmore",
        "canmore.create_textdoc",
        "canmore.update_textdoc",
        "canmore.comment_textdoc",
    ]
    positions = [haystack.find(marker) for marker in markers]
    valid = [position for position in positions if position >= 0]
    if not valid:
        return -1

    marker_index = min(valid)
    fence_index = haystack.rfind("```", 0, marker_index)
    if fence_index >= 0:
        closing_fence_index = haystack.find("```", fence_index + 3, marker_index)
        if closing_fence_index < 0:
            return fence_index
    return marker_index


def _apply_canmore_call(
    call: dict[str, Any], current_textdoc: dict[str, Any] | None
) -> dict[str, Any] | None:
    function_name = _normalize_function_name(call.get("function") or call.get("name"))
    arguments = _normalize_arguments(
        call.get("arguments")
        if "arguments" in call
        else call.get("args") if "args" in call else call.get("payload")
    )
    if function_name not in ALLOWED_CANMORE_FUNCTIONS or not isinstance(arguments, dict):
        return None

    if function_name == "create_textdoc":
        textdoc = _create_textdoc(arguments)
        if not textdoc:
            return None
        return {"action": function_name, "textdoc": textdoc, "events": []}

    if function_name == "update_textdoc":
        if not current_textdoc:
            return None
        textdoc = _update_textdoc(current_textdoc, arguments)
        if not textdoc:
            return None
        return {
            "action": function_name,
            "textdoc": textdoc,
            "events": _summarize_update_events(arguments),
        }

    if function_name == "comment_textdoc":
        if not current_textdoc:
            return None
        textdoc = _comment_textdoc(current_textdoc, arguments)
        if not textdoc:
            return None
        return {
            "action": function_name,
            "textdoc": textdoc,
            "events": _summarize_comment_events(arguments),
        }

    return None


def _create_textdoc(arguments: dict[str, Any]) -> dict[str, Any] | None:
    name = _clean_string(arguments.get("name"), MAX_TEXTDOC_NAME_LENGTH)
    textdoc_type = _normalize_textdoc_type(arguments.get("type"))
    content = _clean_string(arguments.get("content"), MAX_TEXTDOC_CONTENT_LENGTH)
    if not name or not textdoc_type:
        return None

    return {
        "id": _new_canvas_id(),
        "name": name,
        "type": textdoc_type,
        "content": content,
        "comments": [],
        "updated_at": int(time.time()),
    }


def _update_textdoc(
    current_textdoc: dict[str, Any], arguments: dict[str, Any]
) -> dict[str, Any] | None:
    updates = arguments.get("updates")
    if not isinstance(updates, list) or not updates:
        return None

    content = str(current_textdoc.get("content") or "")
    for item in updates:
        if not isinstance(item, dict):
            continue
        pattern = item.get("pattern")
        replacement = item.get("replacement")
        if not isinstance(pattern, str) or not isinstance(replacement, str):
            continue
        multiple = bool(item.get("multiple"))
        try:
            content = re.sub(
                pattern,
                replacement,
                content,
                count=0 if multiple else 1,
                flags=re.DOTALL,
            )
        except re.error:
            continue

    textdoc = deepcopy(current_textdoc)
    textdoc["content"] = content[:MAX_TEXTDOC_CONTENT_LENGTH]
    textdoc["updated_at"] = int(time.time())
    return normalize_canvas_textdoc(textdoc)


def _comment_textdoc(
    current_textdoc: dict[str, Any], arguments: dict[str, Any]
) -> dict[str, Any] | None:
    comments = arguments.get("comments")
    if not isinstance(comments, list) or not comments:
        return None

    textdoc = deepcopy(current_textdoc)
    existing = _normalize_comments(textdoc.get("comments"))
    for item in comments:
        if not isinstance(item, dict):
            continue
        pattern = _clean_string(item.get("pattern"), 1_000)
        comment = _clean_string(item.get("comment"), 2_000)
        if not pattern or not comment:
            continue
        existing.append(
            {
                "id": f"comment_{uuid.uuid4().hex[:10]}",
                "pattern": pattern,
                "comment": comment,
                "created_at": int(time.time()),
            }
        )

    textdoc["comments"] = existing[-MAX_TEXTDOC_COMMENTS:]
    textdoc["updated_at"] = int(time.time())
    return normalize_canvas_textdoc(textdoc)


def _extract_canmore_calls(reply: str) -> tuple[list[dict[str, Any]], list[tuple[int, int]]]:
    calls: list[dict[str, Any]] = []
    spans: list[tuple[int, int]] = []
    occupied: list[tuple[int, int]] = []

    block_patterns = [
        re.compile(r"```canmore\s*([\s\S]*?)```", re.IGNORECASE),
        re.compile(
            r"```[^\n`]*\n([\s\S]*?canmore\.(?:create_textdoc|update_textdoc|comment_textdoc)[\s\S]*?)```",
            re.IGNORECASE,
        ),
        re.compile(r"<canmore(?:\s[^>]*)?>([\s\S]*?)</canmore>", re.IGNORECASE),
    ]
    for pattern in block_patterns:
        for match in pattern.finditer(reply):
            block_calls = _parse_canmore_payload(match.group(1))
            if block_calls:
                span = match.span()
                if _span_overlaps(span, occupied):
                    continue
                calls.extend(block_calls)
                spans.append(span)
                occupied.append(span)

    for function_name in ALLOWED_CANMORE_FUNCTIONS:
        needle = f"canmore.{function_name}"
        start = 0
        while True:
            index = reply.find(needle, start)
            if index < 0:
                break
            parsed = _parse_function_call_at(reply, index, function_name)
            if not parsed:
                start = index + len(needle)
                continue
            call, span = parsed
            start = span[1]
            if _span_overlaps(span, occupied):
                continue
            calls.append(call)
            spans.append(span)
            occupied.append(span)

    return calls, spans


def _parse_canmore_payload(raw_payload: str) -> list[dict[str, Any]]:
    payload = str(raw_payload or "").strip()
    if not payload:
        return []
    parsed = _loads_json(payload)
    if isinstance(parsed, str):
        parsed = _loads_json(parsed)

    if isinstance(parsed, list):
        calls: list[dict[str, Any]] = []
        for item in parsed:
            normalized = _normalize_call_object(item)
            if normalized:
                calls.append(normalized)
        return calls

    normalized = _normalize_call_object(parsed)
    return [normalized] if normalized else []


def _parse_function_call_at(
    source: str, index: int, function_name: str
) -> tuple[dict[str, Any], tuple[int, int]] | None:
    cursor = index + len(f"canmore.{function_name}")
    while cursor < len(source) and source[cursor].isspace():
        cursor += 1
    if cursor >= len(source) or source[cursor] != "(":
        return None

    close_index = _find_balanced_close(source, cursor, "(", ")")
    if close_index < 0:
        return None

    argument_text = source[cursor + 1 : close_index].strip()
    arguments = _normalize_arguments(argument_text)
    if not isinstance(arguments, dict):
        return None
    return {
        "function": function_name,
        "arguments": arguments,
    }, (index, close_index + 1)


def _find_balanced_close(source: str, open_index: int, open_char: str, close_char: str) -> int:
    depth = 0
    quote: str | None = None
    escaped = False
    for offset in range(open_index, len(source)):
        char = source[offset]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue

        if char in {"'", '"'}:
            quote = char
            continue
        if char == open_char:
            depth += 1
            continue
        if char == close_char:
            depth -= 1
            if depth == 0:
                return offset
    return -1


def _normalize_call_object(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    function_name = _normalize_function_name(
        value.get("function") or value.get("name") or value.get("tool")
    )
    if function_name not in ALLOWED_CANMORE_FUNCTIONS:
        if all(key in value for key in ("name", "type", "content")):
            function_name = "create_textdoc"
        elif isinstance(value.get("updates"), list):
            function_name = "update_textdoc"
        elif isinstance(value.get("comments"), list):
            function_name = "comment_textdoc"
    arguments = _normalize_arguments(
        value
        if function_name in ALLOWED_CANMORE_FUNCTIONS
        and "arguments" not in value
        and "args" not in value
        and "payload" not in value
        else (
            value.get("arguments")
            if "arguments" in value
            else (
                value.get("args")
                if "args" in value
                else value.get("payload") if "payload" in value else value
            )
        )
    )
    if function_name not in ALLOWED_CANMORE_FUNCTIONS or not isinstance(arguments, dict):
        return None
    return {"function": function_name, "arguments": arguments}


def _normalize_function_name(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.startswith("canmore."):
        raw = raw.split(".", 1)[1]
    return raw


def _normalize_arguments(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = _loads_json(value.strip())
        if isinstance(parsed, str):
            parsed = _loads_json(parsed)
        if isinstance(parsed, dict):
            return parsed
    return None


def _loads_json(value: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text
    parts: list[str] = []
    cursor = 0
    for start, end in sorted(spans):
        if start < cursor:
            continue
        parts.append(text[cursor:start])
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def _strip_canmore_tool_text(text: str) -> str:
    cleaned = re.sub(
        r"```canmore\s*[\s\S]*?```",
        "",
        str(text or ""),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"```[^\n`]*\n?[\s\S]*?canmore\.(?:create_textdoc|update_textdoc|comment_textdoc)[\s\S]*?```",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"<canmore(?:\s[^>]*)?>[\s\S]*?</canmore>", "", cleaned, flags=re.IGNORECASE)
    paragraphs = re.split(r"(\n\s*\n)", cleaned)
    kept: list[str] = []
    skip_next_separator = False
    for part in paragraphs:
        if not part:
            continue
        is_separator = bool(re.fullmatch(r"\n\s*\n", part))
        if is_separator:
            if kept and not skip_next_separator:
                kept.append(part)
            skip_next_separator = False
            continue
        if "canmore." in part.lower():
            skip_next_separator = True
            continue
        kept.append(part)
    return "".join(kept).strip()


def _span_overlaps(span: tuple[int, int], occupied: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(start < other_end and end > other_start for other_start, other_end in occupied)


def _normalize_textdoc_type(value: Any) -> str:
    textdoc_type = _clean_string(value, MAX_TEXTDOC_TYPE_LENGTH)
    if textdoc_type == "document" or textdoc_type.startswith("code/"):
        return textdoc_type
    return ""


def _normalize_comments(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    comments: list[dict[str, Any]] = []
    for item in value[-MAX_TEXTDOC_COMMENTS:]:
        if not isinstance(item, dict):
            continue
        pattern = _clean_string(item.get("pattern"), 1_000)
        comment = _clean_string(item.get("comment"), 2_000)
        if not pattern or not comment:
            continue
        comments.append(
            {
                "id": _clean_string(item.get("id"), 80) or f"comment_{uuid.uuid4().hex[:10]}",
                "pattern": pattern,
                "comment": comment,
                "created_at": int(item.get("created_at") or time.time()),
            }
        )
    return comments


def _summarize_update_events(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    updates = arguments.get("updates")
    if not isinstance(updates, list):
        return []
    return [
        {
            "pattern": _clean_string(item.get("pattern"), 240),
            "multiple": bool(item.get("multiple")),
        }
        for item in updates
        if isinstance(item, dict) and isinstance(item.get("pattern"), str)
    ][:20]


def _summarize_comment_events(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    comments = arguments.get("comments")
    if not isinstance(comments, list):
        return []
    return [
        {
            "pattern": _clean_string(item.get("pattern"), 240),
        }
        for item in comments
        if isinstance(item, dict) and isinstance(item.get("pattern"), str)
    ][:20]


def _clean_string(value: Any, max_length: int) -> str:
    if value is None:
        return ""
    return str(value)[:max_length]


def _new_canvas_id() -> str:
    return f"textdoc_{uuid.uuid4().hex[:12]}"
