from __future__ import annotations

import ast
import base64
import fcntl
import json
import logging
import os
import re
import shutil
import time
import unicodedata
import uuid
import zipfile
from xml.etree import ElementTree
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image
from werkzeug.utils import secure_filename

from config import PYTHON_RUNNER_ENABLED, PYTHON_RUNNER_QUEUE, UPLOAD_FOLDER
from utils.rate_limiting import RateLimiter
from utils.secure_upload import detect_mime_from_content

logger = logging.getLogger(__name__)

MAX_CODE_CHARS = 24_000
MAX_INPUT_FILES = 8
MAX_INPUT_TOTAL_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 64 * 1024
MAX_ARTIFACT_FILES = 10
MAX_ARTIFACT_TOTAL_BYTES = 12 * 1024 * 1024
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_INLINE_ARTIFACT_BYTES = 4 * 1024 * 1024
MAX_INLINE_ARTIFACT_TOTAL_BYTES = 8 * 1024 * 1024
WAIT_TIMEOUT_SECONDS = 22.0
POLL_SECONDS = 0.05
JOB_ID_RE = re.compile(r"^[a-f0-9]{32}$")
STORED_NAME_RE = re.compile(r"^[a-f0-9]{32}\.[a-z0-9]{1,12}$")
ALLOWED_ARTIFACT_MIMES = {
    ".csv": {"text/csv", "text/plain"},
    ".jpeg": {"image/jpeg"},
    ".jpg": {"image/jpeg"},
    ".json": {"application/json", "text/plain"},
    ".md": {"text/markdown", "text/plain"},
    ".pdf": {"application/pdf"},
    ".png": {"image/png"},
    ".txt": {"text/plain"},
    ".webp": {"image/webp"},
    ".xlsx": {
        "application/zip",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
}
CANONICAL_MIMES = {
    ".csv": "text/csv",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".json": "application/json",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".txt": "text/plain",
    ".webp": "image/webp",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
python_tool_limiter = RateLimiter(max_requests=150, time_window=3600, namespace="python_tool")
SUCCESS_FLAG_RE = re.compile(
    r"^(?:ok|success|successful|valid|passed|audit_passed|checks_passed|validation_passed|.+_ok)$",
    re.IGNORECASE,
)
PLACEHOLDER_COMMENT_RE = re.compile(
    r"(?:\bTODO\b|\bFIXME\b|\bplaceholder\b|\bomitted\b|\bfill\b|"
    r"\bimplement(?:ation)?\s+(?:here|required)\b)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class PythonExecutionResult:
    output: dict[str, Any]
    artifacts: list[dict[str, Any]] = field(default_factory=list)


def python_runner_available(user_id: int | None) -> bool:
    return bool(PYTHON_RUNNER_ENABLED and user_id is not None)


def available_input_files(files: Any) -> list[str]:
    return [item[0] for item in _resolve_input_files(files)]


def execute_python(
    code: Any,
    *,
    user_id: int | None,
    input_files: Any = None,
    allow_artifacts: bool = True,
    inline_artifacts: bool = False,
) -> PythonExecutionResult:
    if not python_runner_available(user_id):
        return PythonExecutionResult({"ok": False, "error": "python_runner_unavailable"})
    if not isinstance(code, str) or not code.strip() or len(code) > MAX_CODE_CHARS:
        return PythonExecutionResult({"ok": False, "error": "invalid_code"})
    quality_issues = _code_quality_issues(code)
    if quality_issues:
        return PythonExecutionResult(
            {
                "ok": False,
                "error": "incomplete_code",
                "quality_issues": quality_issues,
            }
        )

    rate_state = python_tool_limiter.evaluate(f"python_tool:user_{int(user_id)}")
    if not rate_state.allowed:
        return PythonExecutionResult(
            {
                "ok": False,
                "error": "python_rate_limit_exceeded",
                "retry_after_seconds": max(1, rate_state.reset_at - int(time.time())),
            }
        )

    job_id = uuid.uuid4().hex
    request_root = Path(PYTHON_RUNNER_QUEUE) / "requests"
    response_root = Path(PYTHON_RUNNER_QUEUE) / "responses"
    input_root = request_root / job_id / "inputs"
    response_manifest = response_root / f"{job_id}.json"
    request_manifest = request_root / f"{job_id}.json"
    processing_manifest = request_root / f"{job_id}.processing"
    submission_lock = Path(PYTHON_RUNNER_QUEUE) / ".submission.lock"

    try:
        request_root.mkdir(parents=True, mode=0o2770, exist_ok=True)
        response_root.mkdir(parents=True, mode=0o2770, exist_ok=True)
        with submission_lock.open("a+b") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            pending = any(request_root.glob("*.json")) or any(request_root.glob("*.processing"))
            if pending:
                return PythonExecutionResult({"ok": False, "error": "python_runner_busy"})
            input_root.mkdir(parents=True, mode=0o750)
            copied_names = _stage_input_files(input_files, input_root)
            _atomic_json(
                request_manifest,
                {"version": 1, "code": code, "input_files": copied_names},
            )
        response = _wait_for_response(response_manifest)
        artifacts = _persist_artifacts(job_id, response) if allow_artifacts else []
        if inline_artifacts:
            artifacts = _read_inline_artifacts(job_id, response)
        public_artifacts = [
            artifact for artifact in artifacts
            if artifact.get("url_path") or artifact.get("data_url")
        ]
        return PythonExecutionResult(
            {
                "ok": bool(response.get("ok")),
                "error": response.get("error"),
                "exit_code": response.get("exit_code"),
                "timed_out": bool(response.get("timed_out")),
                "duration_ms": _safe_int(response.get("duration_ms"), maximum=60_000),
                "stdout": str(response.get("stdout") or "")[:24_000],
                "stderr": str(response.get("stderr") or "")[:24_000],
                "stdout_truncated": bool(response.get("stdout_truncated")),
                "stderr_truncated": bool(response.get("stderr_truncated")),
                "input_files": [
                    str(name)[:180]
                    for name in response.get("input_files", [])
                    if isinstance(name, str)
                ][:MAX_INPUT_FILES],
                "artifacts": public_artifacts,
            },
            artifacts=public_artifacts,
        )
    except TimeoutError:
        logger.warning("Python runner timed out waiting for job %s", job_id)
        return PythonExecutionResult({"ok": False, "error": "python_runner_timeout"})
    except Exception:
        logger.exception("Python runner request failed")
        return PythonExecutionResult({"ok": False, "error": "python_runner_failed"})
    finally:
        request_manifest.unlink(missing_ok=True)
        processing_manifest.unlink(missing_ok=True)
        response_manifest.unlink(missing_ok=True)
        shutil.rmtree(request_root / job_id, ignore_errors=True)
        shutil.rmtree(response_root / job_id, ignore_errors=True)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o640)
    os.replace(temporary, path)


def _wait_for_response(path: Path) -> dict[str, Any]:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            time.sleep(POLL_SECONDS)
            continue
        if size <= 0 or size > MAX_RESPONSE_BYTES:
            raise ValueError("invalid_runner_response")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("invalid_runner_response")
        return payload
    raise TimeoutError("python_runner_timeout")


def _resolve_input_files(files: Any) -> list[tuple[str, Path]]:
    if not isinstance(files, list):
        return []
    upload_root = Path(UPLOAD_FOLDER).resolve()
    resolved: list[tuple[str, Path]] = []
    seen_names: set[str] = set()
    total_bytes = 0

    for item in files[:MAX_INPUT_FILES]:
        if not isinstance(item, dict):
            continue
        raw_path = item.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            continue
        source_path = Path(raw_path)
        try:
            source_path.lstat()
            if source_path.is_symlink():
                continue
            path = source_path.resolve(strict=True)
            path.relative_to(upload_root)
            stat = path.lstat()
        except (OSError, ValueError):
            continue
        if path.is_symlink() or not path.is_file() or stat.st_size <= 0:
            continue
        total_bytes += stat.st_size
        if total_bytes > MAX_INPUT_TOTAL_BYTES:
            break

        raw_name = unicodedata.normalize("NFC", str(item.get("original_name") or path.name))
        safe_name = secure_filename(raw_name)[:160] or f"input-{len(resolved) + 1}"
        if safe_name in seen_names:
            stem, suffix = os.path.splitext(safe_name)
            safe_name = f"{stem[:140]}-{len(resolved) + 1}{suffix[:12]}"
        seen_names.add(safe_name)
        resolved.append((safe_name, path))
    return resolved


def _stage_input_files(files: Any, destination: Path) -> list[str]:
    names: list[str] = []
    for name, source in _resolve_input_files(files):
        target = destination / name
        with source.open("rb") as source_handle, target.open("xb") as target_handle:
            shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
        os.chmod(target, 0o440)
        names.append(name)
    return names


def _safe_int(value: Any, *, maximum: int) -> int:
    try:
        return max(0, min(maximum, int(value)))
    except (TypeError, ValueError):
        return 0


def _code_quality_issues(code: str) -> list[str]:
    issues: list[str] = []
    for line_number, line in enumerate(code.splitlines(), start=1):
        comment = line.split("#", 1)[1] if "#" in line else ""
        if comment and PLACEHOLDER_COMMENT_RE.search(comment):
            issues.append(f"placeholder_comment:{line_number}")

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return issues

    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            if node.value.value is Ellipsis:
                issues.append(f"ellipsis_placeholder:{node.lineno}")
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and SUCCESS_FLAG_RE.fullmatch(key.value.strip())
                    and isinstance(value, ast.Constant)
                    and value.value is True
                ):
                    issues.append(f"hardcoded_success_flag:{key.value}:{value.lineno}")

    return list(dict.fromkeys(issues))[:20]


def _persist_artifacts(job_id: str, response: dict[str, Any]) -> list[dict[str, Any]]:
    if not JOB_ID_RE.fullmatch(job_id):
        return []
    raw_artifacts = response.get("artifacts")
    if not isinstance(raw_artifacts, list):
        return []
    source_root = (Path(PYTHON_RUNNER_QUEUE) / "responses" / job_id / "artifacts").resolve()
    upload_root = Path(UPLOAD_FOLDER).resolve()
    upload_root.mkdir(parents=True, exist_ok=True)
    persisted: list[dict[str, Any]] = []
    total_bytes = 0

    for raw_artifact in raw_artifacts[:MAX_ARTIFACT_FILES]:
        if not isinstance(raw_artifact, dict):
            continue
        stored_name = str(raw_artifact.get("stored_name") or "")
        original_name = secure_filename(str(raw_artifact.get("original_name") or ""))[:180]
        if not stored_name or not original_name or "/" in stored_name or "\\" in stored_name:
            continue
        source = (source_root / stored_name).resolve()
        try:
            source.relative_to(source_root)
            stat = source.lstat()
        except (OSError, ValueError):
            continue
        if source.is_symlink() or not source.is_file():
            continue
        size = stat.st_size
        total_bytes += size
        if size <= 0 or size > MAX_ARTIFACT_BYTES or total_bytes > MAX_ARTIFACT_TOTAL_BYTES:
            break

        extension = Path(original_name).suffix.lower()
        if extension not in ALLOWED_ARTIFACT_MIMES:
            continue
        target_name = f"{uuid.uuid4().hex}{extension}"
        if not STORED_NAME_RE.fullmatch(target_name):
            continue
        target = upload_root / target_name
        try:
            with source.open("rb") as source_handle, target.open("xb") as target_handle:
                shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
            os.chmod(target, 0o600)
            mime_type = _validate_artifact(target, extension)
            if not mime_type:
                target.unlink(missing_ok=True)
                continue
        except Exception:
            target.unlink(missing_ok=True)
            continue

        persisted.append(
            {
                "url_path": f"/uploads/{target_name}",
                "original_name": original_name,
                "mime_type": mime_type,
                "size": size,
                "metadata": _artifact_metadata(target, extension),
            }
        )
    return persisted


def _read_inline_artifacts(job_id: str, response: dict[str, Any]) -> list[dict[str, Any]]:
    if not JOB_ID_RE.fullmatch(job_id):
        return []
    raw_artifacts = response.get("artifacts")
    if not isinstance(raw_artifacts, list):
        return []

    source_root = (Path(PYTHON_RUNNER_QUEUE) / "responses" / job_id / "artifacts").resolve()
    inline: list[dict[str, Any]] = []
    total_bytes = 0
    for raw_artifact in raw_artifacts[:MAX_ARTIFACT_FILES]:
        if not isinstance(raw_artifact, dict):
            continue
        stored_name = str(raw_artifact.get("stored_name") or "")
        original_name = secure_filename(str(raw_artifact.get("original_name") or ""))[:180]
        if not stored_name or not original_name or "/" in stored_name or "\\" in stored_name:
            continue
        source = (source_root / stored_name).resolve()
        try:
            source.relative_to(source_root)
            stat = source.lstat()
        except (OSError, ValueError):
            continue
        if source.is_symlink() or not source.is_file():
            continue
        size = stat.st_size
        if size <= 0 or size > MAX_INLINE_ARTIFACT_BYTES:
            continue
        if total_bytes + size > MAX_INLINE_ARTIFACT_TOTAL_BYTES:
            break
        extension = Path(original_name).suffix.lower()
        if extension not in {".jpeg", ".jpg", ".png", ".webp"}:
            continue
        mime_type = _validate_artifact(source, extension)
        if not mime_type or not mime_type.startswith("image/"):
            continue
        try:
            encoded = base64.b64encode(source.read_bytes()).decode("ascii")
        except OSError:
            continue
        total_bytes += size
        inline.append(
            {
                "original_name": original_name,
                "mime_type": mime_type,
                "size": size,
                "metadata": _artifact_metadata(source, extension),
                "data_url": f"data:{mime_type};base64,{encoded}",
            }
        )
    return inline


def _validate_artifact(path: Path, extension: str) -> str | None:
    detected = detect_mime_from_content(path)
    if detected not in ALLOWED_ARTIFACT_MIMES.get(extension, set()):
        return None
    if extension in {".jpeg", ".jpg", ".png", ".webp"}:
        try:
            with Image.open(path) as image:
                if image.width > 20_000 or image.height > 20_000:
                    return None
                image.verify()
        except Exception:
            return None
    elif extension == ".json":
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
    elif extension in {".csv", ".md", ".txt"}:
        try:
            sample = path.read_bytes()[: 64 * 1024]
            sample.decode("utf-8-sig")
        except (OSError, UnicodeError):
            return None
    elif extension == ".pdf":
        try:
            with path.open("rb") as handle:
                handle.seek(max(0, path.stat().st_size - 4096))
                if b"%%EOF" not in handle.read():
                    return None
        except OSError:
            return None
    elif extension == ".xlsx":
        try:
            with zipfile.ZipFile(path) as workbook:
                members = workbook.infolist()
                names = {member.filename for member in members}
                if len(members) > 2000 or not {
                    "[Content_Types].xml",
                    "xl/workbook.xml",
                }.issubset(names):
                    return None
                if sum(member.file_size for member in members) > 32 * 1024 * 1024:
                    return None
                for member in members:
                    member_path = Path(member.filename)
                    if (
                        member.flag_bits & 0x1
                        or member_path.is_absolute()
                        or ".." in member_path.parts
                    ):
                        return None
        except (OSError, zipfile.BadZipFile):
            return None
    return CANONICAL_MIMES[extension]


def _artifact_metadata(path: Path, extension: str) -> dict[str, Any]:
    try:
        if extension in {".jpeg", ".jpg", ".png", ".webp"}:
            with Image.open(path) as image:
                return {
                    "kind": "image",
                    "width": max(0, min(20_000, int(image.width))),
                    "height": max(0, min(20_000, int(image.height))),
                }
        if extension == ".xlsx":
            with zipfile.ZipFile(path) as workbook:
                workbook_xml = workbook.read("xl/workbook.xml")
            root = ElementTree.fromstring(workbook_xml)
            sheet_names = [
                str(element.attrib.get("name") or "")[:120]
                for element in root.iter()
                if element.tag.rsplit("}", 1)[-1] == "sheet"
                and element.attrib.get("name")
            ][:100]
            return {
                "kind": "workbook",
                "sheet_count": len(sheet_names),
                "sheet_names": sheet_names,
            }
        if extension == ".pdf":
            data = path.read_bytes()
            return {
                "kind": "pdf",
                "page_count": min(10_000, len(re.findall(rb"/Type\s*/Page\b", data))),
            }
    except (OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError):
        return {}
    return {}
