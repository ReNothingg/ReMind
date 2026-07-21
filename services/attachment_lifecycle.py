from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from flask import current_app, has_app_context
from werkzeug.utils import secure_filename

from config import CHATS_FOLDER, CREATE_IMAGE_FOLDER, UPLOAD_FOLDER
from utils.responses import logger

UPLOAD_NAME_RE = re.compile(r"^[a-f0-9]{32}(?:\.[a-z0-9]{1,12})?$")
GENERATED_IMAGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

ManagedReferences = dict[str, set[str]]


def _empty_references() -> ManagedReferences:
    return {"uploads": set(), "generated_images": set()}


def merge_managed_references(*references: ManagedReferences) -> ManagedReferences:
    merged = _empty_references()
    for reference_set in references:
        for kind in merged:
            merged[kind].update(reference_set.get(kind, set()))
    return merged


def _record_url_path(url_path: object, references: ManagedReferences) -> None:
    if not isinstance(url_path, str):
        return
    path = url_path.split("?", 1)[0].split("#", 1)[0]
    if path.startswith("/uploads/"):
        filename = path.removeprefix("/uploads/")
        if UPLOAD_NAME_RE.fullmatch(filename):
            references["uploads"].add(filename)
    elif path.startswith("/images/"):
        filename = path.removeprefix("/images/")
        if GENERATED_IMAGE_NAME_RE.fullmatch(filename) and secure_filename(filename) == filename:
            references["generated_images"].add(filename)


def collect_managed_references(value: Any) -> ManagedReferences:
    references = _empty_references()

    def visit(item: Any) -> None:
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        if not isinstance(item, dict):
            return

        _record_url_path(item.get("url_path"), references)
        for attachment_key in ("file", "image"):
            attachment = item.get(attachment_key)
            if isinstance(attachment, dict):
                _record_url_path(attachment.get("url_path"), references)
        for child in item.values():
            visit(child)

    visit(value)
    return references


def _configured_path(key: str, fallback: Path) -> Path:
    if has_app_context():
        configured = current_app.config.get(key)
        if configured:
            return Path(str(configured))
    return Path(fallback)


def _database_references(url_path: str) -> bool:
    if not has_app_context():
        # Without a database context, deletion cannot be proven safe.
        return True
    from utils.auth import UserChatHistory

    return bool(
        UserChatHistory.query.filter(UserChatHistory.messages_data.contains(url_path)).first()
    )


def _guest_file_references(
    kind: str,
    filename: str,
    *,
    chats_folder: Path,
) -> bool:
    for chat_path in chats_folder.glob("*.json"):
        try:
            payload = json.loads(chat_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if filename in collect_managed_references(payload)[kind]:
            return True
    return False


def delete_unreferenced_managed_files(
    references: ManagedReferences,
    *,
    chats_folder: Path | None = None,
) -> dict[str, int]:
    roots = {
        "uploads": _configured_path("UPLOAD_FOLDER", UPLOAD_FOLDER),
        "generated_images": _configured_path("CREATE_IMAGE_FOLDER", CREATE_IMAGE_FOLDER),
    }
    prefixes = {"uploads": "/uploads/", "generated_images": "/images/"}
    guest_root = Path(chats_folder or _configured_path("CHATS_FOLDER", CHATS_FOLDER))
    deleted = {"uploads": 0, "generated_images": 0}

    for kind, filenames in references.items():
        if kind not in roots:
            continue
        root = roots[kind].resolve()
        for filename in filenames:
            url_path = f"{prefixes[kind]}{filename}"
            if _database_references(url_path) or _guest_file_references(
                kind, filename, chats_folder=guest_root
            ):
                continue
            target = (root / filename).resolve()
            if target.parent != root:
                continue
            try:
                if target.is_file():
                    target.unlink()
                    deleted[kind] += 1
            except OSError:
                logger.warning("Could not remove an unreferenced chat asset", exc_info=True)
    return deleted
