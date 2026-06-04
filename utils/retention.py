from __future__ import annotations

import time
from pathlib import Path

from config import CHATS_FOLDER, TEMPORARY_CHAT_RETENTION_DAYS


def prune_guest_chat_files(
    *,
    chats_folder: Path = CHATS_FOLDER,
    retention_days: int = TEMPORARY_CHAT_RETENTION_DAYS,
) -> dict[str, int]:
    if retention_days <= 0:
        return {"scanned": 0, "deleted": 0}

    cutoff = time.time() - retention_days * 24 * 60 * 60
    scanned = 0
    deleted = 0

    for path in chats_folder.glob("guest_*.json"):
        scanned += 1
        try:
            if path.stat().st_mtime <= cutoff:
                path.unlink()
                deleted += 1
        except OSError:
            continue

    return {"scanned": scanned, "deleted": deleted}
