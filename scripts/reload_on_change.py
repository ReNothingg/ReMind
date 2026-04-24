#!/usr/bin/env python3
import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "database",
    "dist",
    "logs",
    "node_modules",
}
WATCHED_SUFFIXES = {".py"}


def iter_watched_files(root: Path):
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in IGNORED_DIRS]
        for name in files:
            path = Path(current_root) / name
            if path.suffix in WATCHED_SUFFIXES:
                yield path


def snapshot(root: Path):
    state = {}
    for path in iter_watched_files(root):
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        state[str(path)] = (stat.st_mtime_ns, stat.st_size)
    return state


def terminate(process: subprocess.Popen):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description="Restart a command when Python files change.")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--root", default=".")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("command is required")

    root = Path(args.root).resolve()
    last_state = snapshot(root)
    stopping = False
    process: subprocess.Popen | None = None

    def handle_stop(signum, frame):
        nonlocal stopping
        stopping = True
        if process is not None:
            terminate(process)

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    while not stopping:
        print(f"[reload] starting: {' '.join(command)}", flush=True)
        process = subprocess.Popen(command)

        while not stopping:
            exit_code = process.poll()
            if exit_code is not None:
                return exit_code

            time.sleep(args.interval)
            current_state = snapshot(root)
            if current_state != last_state:
                print("[reload] Python files changed, restarting worker", flush=True)
                last_state = current_state
                terminate(process)
                break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
