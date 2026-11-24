from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from backend.config import UPLOAD_FOLDER
from backend.db.models import ReMindWorkspaceFile, db
from backend.errors import ApiError
from backend.services import project_resources as resources
from backend.services.files import _validate_chat_filename

ARTIFACT_PATH = re.compile(r"/uploads/([a-f0-9]{32}\.[a-z0-9]{1,12})")
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


def _reference(chat, url):
    for message in chat.get_messages() or []:
        if not isinstance(message, dict) or message.get("role") != "model":
            continue
        parts = message.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            payload = part.get("file") or part.get("image")
            if (
                isinstance(payload, dict)
                and payload.get("url_path") == url
                and payload.get("source") in ("tool", "python")
            ):
                return payload
    raise resources.resource_error("workspace_artifact_not_found", 404)


def _available_name(attachment, suffix, current):
    valid, _, name = _validate_chat_filename(str(attachment.get("original_name") or ""))
    if not valid or Path(name).suffix.lower() != suffix:
        name = "artifact" + suffix
    taken = {item.original_name.casefold() for item in current}
    title = Path(name).stem[:220]
    count = 2
    while name.casefold() in taken:
        name = f"{title}-{count}{suffix}"
        count += 1
    return name


def publish(owner, workspace_id, payload):
    if (
        not isinstance(payload, dict)
        or set(payload) != {"session_id", "artifact_path"}
        or not isinstance(url := payload["artifact_path"], str)
        or (match := ARTIFACT_PATH.fullmatch(url)) is None
    ):
        raise resources.resource_error("workspace_artifact_invalid")
    workspace = resources.lock_files_workspace(owner, workspace_id)
    chat = resources.private_workspace_chat(owner, workspace.id, payload["session_id"], lock=True)
    attachment = _reference(chat, url)
    identifier = uuid5(NAMESPACE_URL, f"remind:{workspace.id}:{url}").hex
    row = ReMindWorkspaceFile.query.filter_by(
        workspace_id=workspace.id, id=identifier
    ).one_or_none()
    if row is not None:
        return resources.file_metadata(row), False

    filename = match[1]
    suffix = Path(filename).suffix
    try:
        raw = resources.read_workspace_bytes(
            Path(UPLOAD_FOLDER).resolve() / filename, MAX_ARTIFACT_BYTES
        )
    except ApiError as error:
        if error.status == 404:
            raise resources.resource_error("workspace_artifact_not_found", 404) from None
        raise
    expected = attachment.get("size")
    if type(expected) is int and expected > 0 and expected != len(raw):
        raise resources.resource_error("workspace_artifact_changed", 409)
    metadata = attachment.get("metadata")
    if isinstance(metadata, dict) and (checksum := metadata.get("sha256")):
        if checksum != sha256(raw).hexdigest():
            raise resources.resource_error("workspace_artifact_changed", 409)
    mime = attachment.get("mime_type")
    if (
        not isinstance(mime, str)
        or not re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", mime, re.I)
        or len(mime) > 120
    ):
        mime = "application/octet-stream"
    current = resources.workspace_files(workspace.id)
    resources.validate_storage_limits(
        owner, current, len(current) + 1, sum(item.size for item in current) + len(raw)
    )
    name = _available_name(attachment, suffix, current)
    storage = resources.stage_workspace_bytes(raw, suffix)
    try:
        row = ReMindWorkspaceFile(
            id=identifier,
            workspace_id=workspace.id,
            storage_name=storage,
            original_name=name,
            name_key=sha256(name.casefold().encode()).hexdigest(),
            mime_type=mime,
            size=len(raw),
        )
        db.session.add(row)
        db.session.commit()
    except Exception:
        db.session.rollback()
        resources.remove_uploads([storage])
        raise
    return resources.file_metadata(row), True
