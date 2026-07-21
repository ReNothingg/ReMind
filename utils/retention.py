from __future__ import annotations

import json
import time
from pathlib import Path

from config import CHATS_FOLDER, TEMPORARY_CHAT_RETENTION_DAYS
from services.attachment_lifecycle import (
    collect_managed_references,
    delete_unreferenced_managed_files,
    merge_managed_references,
)


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
    deleted_references = collect_managed_references({})

    for path in chats_folder.glob("guest_*.json"):
        scanned += 1
        try:
            if path.stat().st_mtime <= cutoff:
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    deleted_references = merge_managed_references(
                        deleted_references, collect_managed_references(payload)
                    )
                except (OSError, UnicodeError, json.JSONDecodeError):
                    pass
                path.unlink()
                deleted += 1
        except OSError:
            continue

    if deleted:
        delete_unreferenced_managed_files(
            deleted_references,
            chats_folder=chats_folder,
        )

    return {"scanned": scanned, "deleted": deleted}
