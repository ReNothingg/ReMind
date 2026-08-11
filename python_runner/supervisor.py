from __future__ import annotations

import ctypes
import json
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

QUEUE_ROOT = Path(os.getenv("PYTHON_RUNNER_QUEUE", "/jobs")).resolve()
REQUESTS_DIR = QUEUE_ROOT / "requests"
RESPONSES_DIR = QUEUE_ROOT / "responses"
HEARTBEAT_PATH = QUEUE_ROOT / ".heartbeat"
JOB_ID_RE = re.compile(r"^[a-f0-9]{32}$")
MAX_CODE_CHARS = 24_000
MAX_INPUT_FILES = 8
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_FILES = 10
MAX_ARTIFACT_BYTES = 12 * 1024 * 1024
MAX_SINGLE_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_STDIO_CHARS = 24_000
RUN_TIMEOUT_SECONDS = 15
SANDBOX_UID = 65532
SANDBOX_GID = 65532
POLL_SECONDS = 0.1
STALE_SECONDS = 3600
ALLOWED_ARTIFACT_EXTENSIONS = {
    ".csv",
    ".jpeg",
    ".jpg",
    ".json",
    ".md",
    ".pdf",
    ".png",
    ".txt",
    ".webp",
    ".xlsx",
}


def _become_subreaper() -> None:
    try:
        ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0)
    except Exception:
        pass


def _kill_sandbox_processes() -> None:
    for status_path in Path("/proc").glob("[0-9]*/status"):
        try:
            status = status_path.read_text(encoding="utf-8", errors="replace")
            uid_line = next(line for line in status.splitlines() if line.startswith("Uid:"))
            real_uid = int(uid_line.split()[1])
            if real_uid == SANDBOX_UID:
                os.kill(int(status_path.parent.name), signal.SIGKILL)
        except (OSError, StopIteration, ValueError):
            continue
    deadline = time.monotonic() + 0.5
    while True:
        reaped = False
        while True:
            try:
                waited_pid, _status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return
            if waited_pid <= 0:
                break
            reaped = True
        if time.monotonic() >= deadline:
            return
        if not reaped:
            time.sleep(0.01)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.chmod(0o640)
    os.chown(temporary, 1001, 0)
    os.replace(temporary, path)


def _touch_heartbeat() -> None:
    temporary = HEARTBEAT_PATH.with_suffix(".tmp")
    temporary.write_text(str(int(time.time())), encoding="ascii")
    os.replace(temporary, HEARTBEAT_PATH)


def _bounded_text(value: Any, limit: int = MAX_STDIO_CHARS) -> tuple[str, bool]:
    text = str(value or "")
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _safe_child_name(value: Any) -> str | None:
    name = str(value or "").strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        return None
    if len(name) > 180 or any(ord(character) < 32 for character in name):
        return None
    return name


def _prepare_limits() -> None:
    os.setsid()
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (10, 11))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    os.setgroups([])
    os.setgid(SANDBOX_GID)
    os.setuid(SANDBOX_UID)


def _copy_inputs(job_id: str, destination: Path, requested: list[Any]) -> list[str]:
    source_root = REQUESTS_DIR / job_id / "inputs"
    input_root = destination / "input"
    input_root.mkdir(mode=0o700)
    os.chown(input_root, SANDBOX_UID, SANDBOX_GID)
    copied: list[str] = []
    total_bytes = 0

    for raw_name in requested[:MAX_INPUT_FILES]:
        name = _safe_child_name(raw_name)
        if not name:
            continue
        source = source_root / name
        try:
            source_stat = source.lstat()
        except OSError:
            continue
        if not source.is_file() or source.is_symlink():
            continue
        total_bytes += source_stat.st_size
        if source_stat.st_size <= 0 or total_bytes > MAX_INPUT_BYTES:
            break
        target = input_root / name
        shutil.copyfile(source, target, follow_symlinks=False)
        target.chmod(0o400)
        os.chown(target, SANDBOX_UID, SANDBOX_GID)
        copied.append(name)
    return copied


def _collect_artifacts(output_root: Path, response_root: Path) -> list[dict[str, Any]]:
    artifact_root = response_root / "artifacts"
    artifact_root.mkdir(mode=0o770)
    artifact_root.chmod(0o770)
    os.chown(artifact_root, 1001, 0)
    artifacts: list[dict[str, Any]] = []
    total_bytes = 0

    candidates = sorted(output_root.iterdir(), key=lambda path: path.name.casefold())
    for source in candidates:
        if len(artifacts) >= MAX_ARTIFACT_FILES:
            break
        if source.is_symlink() or not source.is_file():
            continue
        safe_name = _safe_child_name(source.name)
        if not safe_name or source.suffix.lower() not in ALLOWED_ARTIFACT_EXTENSIONS:
            continue
        size = source.stat().st_size
        if size <= 0 or size > MAX_SINGLE_ARTIFACT_BYTES:
            continue
        if total_bytes + size > MAX_ARTIFACT_BYTES:
            break
        stored_name = f"{len(artifacts):02d}-{safe_name}"
        target = artifact_root / stored_name
        shutil.copyfile(source, target, follow_symlinks=False)
        target.chmod(0o640)
        os.chown(target, 1001, 0)
        total_bytes += size
        artifacts.append(
            {
                "stored_name": stored_name,
                "original_name": safe_name,
                "size": size,
            }
        )
    return artifacts


def _execute_job(job_id: str, request_path: Path) -> dict[str, Any]:
    started = time.monotonic()
    response_root = RESPONSES_DIR / job_id
    work_root = Path("/tmp") / f"remind-python-{job_id}"
    response_root.mkdir(mode=0o770)
    response_root.chmod(0o770)
    os.chown(response_root, 1001, 0)
    work_root.mkdir(mode=0o711)
    work_root.chmod(0o711)

    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        code = request.get("code")
        if not isinstance(code, str) or not code.strip() or len(code) > MAX_CODE_CHARS:
            return {"ok": False, "error": "invalid_code"}

        output_root = work_root / "output"
        output_root.mkdir(mode=0o700)
        os.chown(output_root, SANDBOX_UID, SANDBOX_GID)
        home_root = work_root / "home"
        home_root.mkdir(mode=0o700)
        os.chown(home_root, SANDBOX_UID, SANDBOX_GID)
        matplotlib_root = work_root / "mplconfig"
        matplotlib_root.mkdir(mode=0o700)
        os.chown(matplotlib_root, SANDBOX_UID, SANDBOX_GID)
        temporary_root = work_root / "temp"
        temporary_root.mkdir(mode=0o700)
        os.chown(temporary_root, SANDBOX_UID, SANDBOX_GID)
        input_names = _copy_inputs(job_id, work_root, request.get("input_files") or [])

        script_path = work_root / "main.py"
        capture_figures = """
import os as _remind_os
try:
    import matplotlib.pyplot as _remind_plt
    _remind_output_dir = _remind_os.environ.get("REMIND_OUTPUT_DIR", "")
    for _remind_index, _remind_number in enumerate(_remind_plt.get_fignums(), start=1):
        _remind_figure = _remind_plt.figure(_remind_number)
        _remind_figure.savefig(
            _remind_os.path.join(_remind_output_dir, f"figure-{_remind_index}.png"),
            dpi=144,
            bbox_inches="tight",
        )
except Exception:
    pass
"""
        script_path.write_text(f"{code}\n\n{capture_figures}", encoding="utf-8")
        script_path.chmod(0o400)
        os.chown(script_path, SANDBOX_UID, SANDBOX_GID)

        environment = {
            "HOME": str(home_root),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "MPLBACKEND": "Agg",
            "MPLCONFIGDIR": str(matplotlib_root),
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONNOUSERSITE": "1",
            "PYTHONUNBUFFERED": "1",
            "REMIND_INPUT_DIR": str(work_root / "input"),
            "REMIND_OUTPUT_DIR": str(output_root),
            "TMPDIR": str(temporary_root),
        }

        timed_out = False
        process = subprocess.Popen(
            [sys.executable, "-I", "-B", str(script_path)],
            cwd=work_root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            preexec_fn=_prepare_limits,
        )
        try:
            raw_stdout, raw_stderr = process.communicate(timeout=RUN_TIMEOUT_SECONDS)
            stdout, stdout_truncated = _bounded_text(raw_stdout)
            stderr, stderr_truncated = _bounded_text(raw_stderr)
            exit_code = process.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                process.kill()
            raw_stdout, raw_stderr = process.communicate()
            stdout, stdout_truncated = _bounded_text(raw_stdout or exc.stdout)
            stderr, stderr_truncated = _bounded_text(raw_stderr or exc.stderr)
            exit_code = None
        finally:
            _kill_sandbox_processes()

        artifacts = (
            _collect_artifacts(output_root, response_root)
            if exit_code == 0 and not timed_out
            else []
        )
        return {
            "ok": exit_code == 0 and not timed_out,
            "error": (
                "execution_timed_out"
                if timed_out
                else (None if exit_code == 0 else "execution_failed")
            ),
            "exit_code": exit_code,
            "timed_out": timed_out,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "input_files": input_names,
            "artifacts": artifacts,
        }
    except Exception:
        traceback.print_exc()
        return {"ok": False, "error": "runner_internal_error"}
    finally:
        shutil.rmtree(work_root, ignore_errors=True)


def _remove_stale_entries(now: float) -> None:
    for root in (REQUESTS_DIR, RESPONSES_DIR):
        for path in root.iterdir():
            try:
                if now - path.stat().st_mtime <= STALE_SECONDS:
                    continue
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path, ignore_errors=True)
                elif path.is_file() or path.is_symlink():
                    path.unlink(missing_ok=True)
            except OSError:
                continue


def _recover_interrupted_requests() -> None:
    for processing_path in REQUESTS_DIR.glob("*.processing"):
        job_id = processing_path.stem
        if not JOB_ID_RE.fullmatch(job_id):
            processing_path.unlink(missing_ok=True)
            continue
        response_path = RESPONSES_DIR / f"{job_id}.json"
        request_path = REQUESTS_DIR / f"{job_id}.json"
        try:
            if response_path.exists():
                processing_path.unlink(missing_ok=True)
            elif not request_path.exists():
                os.replace(processing_path, request_path)
        except OSError:
            continue


def main() -> None:
    os.umask(0o077)
    _become_subreaper()
    _kill_sandbox_processes()
    REQUESTS_DIR.mkdir(parents=True, mode=0o2770, exist_ok=True)
    RESPONSES_DIR.mkdir(parents=True, mode=0o2770, exist_ok=True)
    _recover_interrupted_requests()
    last_maintenance = 0.0

    while True:
        now = time.time()
        if now - last_maintenance >= 5:
            _touch_heartbeat()
            if now - last_maintenance >= 60:
                _remove_stale_entries(now)
            last_maintenance = now

        request_paths = sorted(REQUESTS_DIR.glob("*.json"), key=lambda path: path.stat().st_mtime)
        if not request_paths:
            time.sleep(POLL_SECONDS)
            continue

        request_path = request_paths[0]
        job_id = request_path.stem
        if not JOB_ID_RE.fullmatch(job_id):
            request_path.unlink(missing_ok=True)
            continue
        processing_path = request_path.with_suffix(".processing")
        try:
            os.replace(request_path, processing_path)
        except OSError:
            continue

        result = _execute_job(job_id, processing_path)
        _atomic_json(RESPONSES_DIR / f"{job_id}.json", result)
        processing_path.unlink(missing_ok=True)
        shutil.rmtree(REQUESTS_DIR / job_id, ignore_errors=True)


if __name__ == "__main__":
    main()
