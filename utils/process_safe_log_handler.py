from __future__ import annotations

import logging
import logging.handlers
import os
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - production images are Linux
    fcntl = None  # type: ignore[assignment]


class ProcessSafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Size-bounded rotation serialized across Gunicorn/Celery processes."""

    def __init__(
        self,
        filename: str,
        *,
        max_bytes: int,
        backup_count: int,
        retention_days: int,
    ) -> None:
        self.lock_path = f"{filename}.lock"
        super().__init__(
            filename,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
            delay=True,
        )
        self._prune_expired_backups(retention_days)

    def _prune_expired_backups(self, retention_days: int) -> None:
        cutoff = time.time() - max(1, retention_days) * 24 * 60 * 60
        base_path = Path(self.baseFilename)
        for candidate in base_path.parent.glob(f"{base_path.name}.*"):
            if candidate == Path(self.lock_path):
                continue
            try:
                if candidate.stat().st_mtime < cutoff:
                    candidate.unlink()
            except OSError:
                continue

    def emit(self, record: logging.LogRecord) -> None:
        Path(self.lock_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "a", encoding="utf-8") as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                if self.stream is not None:
                    self.stream.close()
                    self.stream = None  # type: ignore[assignment]
                super().emit(record)
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def doRollover(self) -> None:
        # Parent implementation is safe because emit holds the process lock.
        super().doRollover()
        try:
            os.chmod(self.baseFilename, 0o600)
        except OSError:
            pass
