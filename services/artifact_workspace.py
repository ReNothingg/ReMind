from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from werkzeug.utils import secure_filename

from config import UPLOAD_FOLDER
from services.document_tools import _read_file
from services.python_runner import MAX_INPUT_TOTAL_BYTES, resolve_input_files
from services.tool_protocol import ModelToolResult
from utils.rate_limiting import RateLimiter

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".sql",
    ".sh",
    ".yaml",
    ".yml",
    ".toml",
    ".xml",
}
MAX_ARTIFACT_BYTES = 512 * 1024
artifact_limiter = RateLimiter(max_requests=60, time_window=3600, namespace="chat_artifacts")


def spreadsheet_safe_csv(content: str) -> tuple[str, bool]:
    result = io.StringIO(newline="")
    writer = csv.writer(result)
    changed = False
    for index, row in enumerate(csv.reader(io.StringIO(content, newline=""), strict=True)):
        if index > 20_000 or len(row) > 128:
            raise ValueError("table_too_large")
        safe = []
        for cell in row:
            if cell.lstrip().startswith(("=", "+", "-", "@")):
                try:
                    float(cell)
                    numeric = True
                except ValueError:
                    numeric = False
                if not numeric:
                    cell = "'" + cell
                    changed = True
            safe.append(cell)
        writer.writerow(safe)
    return result.getvalue(), changed


@dataclass
class ArtifactWorkspace:
    user_id: int | None
    allow_artifacts: bool
    created: int = 0
    written_bytes: int = 0

    def save(self, filename: str, content: str, files: list[dict]) -> ModelToolResult:
        if self.user_id is None or not self.allow_artifacts:
            raise ValueError("persistent_account_required")
        if (
            len(filename) > 120
            or secure_filename(filename) != filename
            or filename.startswith(".")
            or Path(filename).suffix.lower() not in TEXT_EXTENSIONS
        ):
            raise ValueError("invalid_artifact_filename")
        if self.created >= 8:
            raise ValueError("artifact_limit_reached")
        if not content or "\x00" in content:
            raise ValueError("invalid_text_content")
        escaped = False
        suffix = Path(filename).suffix.lower()
        if suffix == ".json":
            try:
                json.loads(content, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            except (ValueError, RecursionError) as exc:
                raise ValueError("invalid_json") from exc
        if suffix == ".csv":
            try:
                content, escaped = spreadsheet_safe_csv(content)
            except csv.Error as exc:
                raise ValueError("invalid_csv") from exc
        raw = content.encode("utf-8")
        if len(raw) > MAX_ARTIFACT_BYTES or self.written_bytes + len(raw) > 2 * 1024 * 1024:
            raise ValueError("artifact_too_large")
        available = resolve_input_files(files)
        if (
            len(available) >= 24
            or sum(path.stat().st_size for _, path in available) + len(raw) > MAX_INPUT_TOTAL_BYTES
        ):
            raise ValueError("workspace_limit_reached")
        used = {name for name, _ in available}
        actual_name = filename
        version = 2
        while actual_name in used:
            actual_name = f"{Path(filename).stem[:105]}-{version}{suffix}"
            version += 1
        if not artifact_limiter.evaluate(f"chat_artifacts:user_{self.user_id}").allowed:
            raise ValueError("artifact_rate_limit")
        root = Path(UPLOAD_FOLDER).resolve()
        root.mkdir(parents=True, exist_ok=True)
        target = root / f"{uuid.uuid4().hex}{suffix}"
        created = False
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
        except OSError:
            if created:
                target.unlink(missing_ok=True)
            raise
        self.created += 1
        self.written_bytes += len(raw)
        mime = {".json": "application/json", ".csv": "text/csv", ".md": "text/markdown"}.get(
            suffix, "text/plain"
        )
        artifact: dict[str, Any] = {
            "url_path": f"/uploads/{target.name}",
            "original_name": actual_name,
            "mime_type": mime,
            "size": len(raw),
            "source": "tool",
            "metadata": {"sha256": hashlib.sha256(raw).hexdigest()},
        }
        return ModelToolResult(
            {
                "ok": True,
                "artifact": artifact,
                "filename": actual_name,
                "revision": artifact["metadata"]["sha256"],
                "spreadsheet_formulas_escaped": escaped,
            },
            events=[{"python_artifacts": [artifact]}],
            reusable_files=[{**artifact, "path": str(target)}],
        )

    def execute(
        self, name: str, arguments: dict, files: list[dict], canvas: dict | None
    ) -> ModelToolResult:
        try:
            if name == "canvas_export":
                if not canvas:
                    raise ValueError("canvas_not_open")
                return self.save(arguments["filename"], canvas["content"], files)
            if name == "file_write":
                return self.save(arguments["filename"], arguments["content"], files)
            content = _read_file(arguments["filename"], files)
            revision = hashlib.sha256(content.encode()).hexdigest()
            if revision != arguments["expected_revision"]:
                raise ValueError("file_revision_changed")
            old = arguments["old_text"]
            position = content.find(old)
            if position < 0:
                raise ValueError("edit_text_not_found")
            if content.find(old, position + 1) >= 0:
                raise ValueError("ambiguous_edit")
            content = content[:position] + arguments["new_text"] + content[position + len(old) :]
            return self.save(
                arguments.get("output_filename") or arguments["filename"], content, files
            )
        except (ValueError, OSError) as exc:
            return ModelToolResult(
                {
                    "ok": False,
                    "error": str(exc) if isinstance(exc, ValueError) else "artifact_write_failed",
                }
            )
