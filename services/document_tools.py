from __future__ import annotations

import difflib
import fnmatch
import hashlib
import time
from typing import Any

from services.canvas_tools import MAX_TEXTDOC_CONTENT_LENGTH
from services.python_runner import resolve_input_files
from services.tool_protocol import ModelToolResult

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 24_000


def _page(text: str, start: int, limit: int) -> dict[str, Any]:
    lines = text.splitlines()
    selected: list[dict[str, Any]] = []
    remaining = MAX_TEXT_CHARS
    for number, line in enumerate(lines[start - 1 : start - 1 + limit], start):
        if len(line) > remaining:
            selected.append({"line": number, "text": line[:remaining], "truncated": True})
            return {
                "lines": selected,
                "total_lines": len(lines),
                "next_line": number,
                "truncated": True,
            }
        selected.append({"line": number, "text": line})
        remaining -= len(line) + 1
        if remaining <= 0:
            break
    next_line = start + len(selected)
    return {
        "lines": selected,
        "total_lines": len(lines),
        "next_line": next_line if next_line <= len(lines) else None,
        "truncated": next_line <= len(lines),
    }


def _read_file(filename: str, files: list[dict]) -> str:
    matches = [path for name, path in resolve_input_files(files) if name == filename]
    if len(matches) != 1:
        raise ValueError("file_not_available")
    with matches[0].open("rb") as handle:
        raw = handle.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("file_too_large")
    if b"\x00" in raw:
        raise ValueError("text_file_required")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("utf8_text_required") from exc


def execute_document_tool(
    name: str, arguments: dict, files: list[dict], canvas: dict | None
) -> ModelToolResult:
    try:
        if name == "file_glob":
            names = [
                filename
                for filename, _ in resolve_input_files(files)
                if fnmatch.fnmatchcase(filename, arguments["pattern"])
            ]
            return ModelToolResult({"ok": True, "filenames": names, "count": len(names)})
        if name == "file_search_all":
            needle = arguments["query"].casefold()
            matches = []
            skipped = []
            for filename, _ in resolve_input_files(files):
                if not fnmatch.fnmatchcase(filename, arguments.get("pattern", "*")):
                    continue
                try:
                    content = _read_file(filename, files)
                except ValueError:
                    skipped.append(filename)
                    continue
                for line_number, line in enumerate(content.splitlines(), 1):
                    if needle in line.casefold():
                        matches.append(
                            {"filename": filename, "line": line_number, "text": line[:500]}
                        )
                        if len(matches) >= 40:
                            return ModelToolResult(
                                {
                                    "ok": True,
                                    "matches": matches,
                                    "truncated": True,
                                    "skipped": skipped,
                                }
                            )
            return ModelToolResult(
                {"ok": True, "matches": matches, "truncated": False, "skipped": skipped}
            )
        if name == "file_diff":
            before = _read_file(arguments["before"], files)
            after = _read_file(arguments["after"], files)
            if len(before) + len(after) > 200_000:
                raise ValueError("diff_input_too_large")
            lines = difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=arguments["before"],
                tofile=arguments["after"],
                n=3,
            )
            preview = []
            size = 0
            truncated = False
            for line in lines:
                size += len(line)
                if size > MAX_TEXT_CHARS:
                    truncated = True
                    break
                preview.append(line)
            return ModelToolResult(
                {
                    "ok": True,
                    "identical": before == after,
                    "diff": "".join(preview),
                    "truncated": truncated,
                }
            )
        if name == "file_list":
            return ModelToolResult(
                {
                    "ok": True,
                    "files": [
                        {"filename": filename, "bytes": path.stat().st_size}
                        for filename, path in resolve_input_files(files)
                    ],
                }
            )
        if name in {"file_read", "file_search"}:
            text = _read_file(arguments["filename"], files)
            if name == "file_read":
                revision = hashlib.sha256(text.encode()).hexdigest()
                if "offset" in arguments:
                    offset = arguments["offset"]
                    if offset > len(text):
                        raise ValueError("offset_out_of_range")
                    end = min(len(text), offset + arguments.get("max_characters", 12000))
                    return ModelToolResult(
                        {
                            "ok": True,
                            "filename": arguments["filename"],
                            "revision": revision,
                            "text": text[offset:end],
                            "offset": offset,
                            "next_offset": end if end < len(text) else None,
                            "total_characters": len(text),
                        }
                    )
                return ModelToolResult(
                    {
                        "ok": True,
                        "filename": arguments["filename"],
                        "revision": revision,
                        **_page(
                            text, arguments.get("start_line", 1), arguments.get("line_count", 100)
                        ),
                    }
                )
            needle = arguments["query"]
            sensitive = arguments.get("case_sensitive", False)
            if not sensitive:
                needle = needle.casefold()
            matches = []
            truncated = False
            for number, line in enumerate(text.splitlines(), 1):
                if needle in (line if sensitive else line.casefold()):
                    if len(matches) >= 40:
                        truncated = True
                        break
                    matches.append(
                        {"line": number, "text": line[:500], "truncated": len(line) > 500}
                    )
            return ModelToolResult(
                {
                    "ok": True,
                    "filename": arguments["filename"],
                    "matches": matches,
                    "truncated": truncated,
                }
            )
        if not canvas:
            raise ValueError("canvas_not_open")
        text = str(canvas.get("content") or "")
        revision = hashlib.sha256(text.encode()).hexdigest()
        if name == "canvas_read":
            return ModelToolResult(
                {
                    "ok": True,
                    "id": canvas["id"],
                    "revision": revision,
                    **_page(text, arguments.get("start_line", 1), arguments.get("line_count", 100)),
                }
            )
        if name != "canvas_edit":
            raise ValueError("unknown_tool")
        if arguments["expected_revision"] != revision:
            raise ValueError("canvas_revision_changed")
        old = arguments["old_text"]
        first = text.find(old)
        if first < 0:
            raise ValueError("edit_text_not_found")
        if text.find(old, first + 1) >= 0:
            raise ValueError("ambiguous_edit")
        content = text[:first] + arguments["new_text"] + text[first + len(old) :]
        if len(content) > MAX_TEXTDOC_CONTENT_LENGTH:
            raise ValueError("content_too_large")
        document = {**canvas, "content": content, "updated_at": int(time.time())}
        update = {"action": "update_textdoc", "textdoc": document}
        return ModelToolResult(
            {
                "ok": True,
                "published": True,
                "id": canvas["id"],
                "revision": hashlib.sha256(content.encode()).hexdigest(),
                "runtime_tested": False,
            },
            events=[{"canvas_update": update, "canvas_textdoc": document}],
        )
    except (ValueError, OSError) as exc:
        return ModelToolResult(
            {"ok": False, "error": str(exc) if isinstance(exc, ValueError) else "file_read_failed"}
        )
