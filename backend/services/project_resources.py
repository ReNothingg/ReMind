import os
import re
import stat
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from backend.config import UPLOAD_FOLDER
from backend.db.models import (
    ChatShare,
    ReMindWorkspace,
    ReMindWorkspaceFile,
    User,
    UserChatHistory,
    db,
)
from backend.errors import ApiError
from backend.responses import logger
from backend.services.files import (
    STORED_UPLOAD_NAME_RE,
    store_validated_upload,
    validate_chat_uploads,
)

MAX_INSTRUCTION_BYTES = 65_536
MAX_PROJECT_FILES = 24
MAX_PROJECT_BYTES = 64 * 1024 * 1024
MAX_ACCOUNT_BYTES = 256 * 1024 * 1024
SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")


def resource_error(code, status=400):
    return ApiError(code, status=status, code=code)


def owned_workspace(owner, workspace_id, *, lock=False):
    query = ReMindWorkspace.query.filter_by(user_id=owner, id=workspace_id)
    row = (query.with_for_update() if lock else query).one_or_none()
    if row is None:
        raise resource_error("workspace_not_found", 404)
    return row


def validate_instructions(value):
    if not isinstance(value, str) or "\x00" in value:
        raise resource_error("invalid_workspace_instructions")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise resource_error("invalid_workspace_instructions") from error
    instructions = value.strip()
    if len(instructions.encode()) > MAX_INSTRUCTION_BYTES:
        raise resource_error("invalid_workspace_instructions")
    return instructions


def uploads_root():
    root = Path(UPLOAD_FOLDER).resolve() / "workspace-files"
    if root.is_symlink():
        raise resource_error("workspace_runtime_unavailable", 503)
    return root


def resource_path(storage_name):
    if not isinstance(storage_name, str) or not STORED_UPLOAD_NAME_RE.fullmatch(storage_name):
        return None
    target = uploads_root() / storage_name
    return target if target.is_file() and not target.is_symlink() else None


def workspace_files(workspace_id):
    return (
        ReMindWorkspaceFile.query.filter_by(workspace_id=workspace_id)
        .order_by(ReMindWorkspaceFile.created_at, ReMindWorkspaceFile.id)
        .all()
    )


def owner_files(owner):
    return ReMindWorkspaceFile.query.join(ReMindWorkspace).filter(ReMindWorkspace.user_id == owner)


def lock_files_workspace(owner, workspace_id):
    if User.query.filter_by(id=owner).with_for_update().one_or_none() is None:
        raise resource_error("auth_required", 401)
    return owned_workspace(owner, workspace_id, lock=True)


def private_workspace_chat(owner, workspace_id, session_id, *, lock=False):
    if not isinstance(session_id, str) or SESSION_ID.fullmatch(session_id) is None:
        raise resource_error("workspace_chat_not_found", 404)
    query = UserChatHistory.query.filter_by(
        user_id=owner, workspace_id=workspace_id, session_id=session_id, source="web"
    )
    chat = (query.with_for_update().populate_existing() if lock else query).one_or_none()
    public = ChatShare.query.filter_by(user_id=owner, session_id=session_id, is_public=True).first()
    if chat is None or public is not None:
        raise resource_error("workspace_chat_not_found", 404)
    return chat


def validate_storage_limits(owner, current, final_count, final_size):
    if final_count > MAX_PROJECT_FILES:
        raise resource_error("workspace_file_limit", 409)
    account_size = owner_files(owner).with_entities(
        db.func.coalesce(db.func.sum(ReMindWorkspaceFile.size), 0)
    ).scalar()
    if (
        final_size > MAX_PROJECT_BYTES
        or account_size - sum(row.size for row in current) + final_size > MAX_ACCOUNT_BYTES
    ):
        raise resource_error("workspace_storage_limit", 409)


def read_workspace_bytes(path, max_bytes):
    if path is None:
        raise resource_error("workspace_file_not_found", 404)
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as handle:
            content = os.fstat(handle.fileno())
            if not stat.S_ISREG(content.st_mode):
                raise resource_error("workspace_file_not_found", 404)
            if content.st_size > max_bytes:
                raise resource_error("workspace_file_too_large", 413)
            raw = handle.read(max_bytes + 1)
    except OSError:
        raise resource_error("workspace_file_not_found", 404) from None
    if len(raw) > max_bytes:
        raise resource_error("workspace_file_too_large", 413)
    return raw


def stage_workspace_bytes(raw, suffix):
    root = uploads_root()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    name = uuid4().hex + suffix
    target = root / name
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        target.unlink(missing_ok=True)
        raise
    return name


def delete_owner_files(owner):
    ids = db.select(ReMindWorkspace.id).where(ReMindWorkspace.user_id == owner)
    rows = ReMindWorkspaceFile.query.filter(ReMindWorkspaceFile.workspace_id.in_(ids))
    storage = [row.storage_name for row in rows]
    rows.delete(synchronize_session=False)
    return storage


def file_metadata(row):
    return {
        "id": row.id,
        "name": row.original_name,
        "mime_type": row.mime_type,
        "size": row.size,
        "created_at": row.created_at.isoformat(),
        "download_url": f"/api/workspaces/{row.workspace_id}/files/{row.id}",
    }


def workspace_document(workspace):
    return {
        "id": workspace.id,
        "name": workspace.name,
        "instructions": workspace.instructions or "",
        "files": [file_metadata(row) for row in workspace_files(workspace.id)],
    }


def owned_file(owner, workspace_id, file_id):
    row = (
        owner_files(owner)
        .filter(ReMindWorkspaceFile.workspace_id == workspace_id, ReMindWorkspaceFile.id == file_id)
        .one_or_none()
    )
    if row is None:
        raise resource_error("workspace_file_not_found", 404)
    return row


def remove_uploads(storage_names):
    for storage_name in storage_names:
        try:
            if path := resource_path(storage_name):
                path.unlink(missing_ok=True)
        except (OSError, ApiError):
            logger.warning("Could not remove a project upload")


def upload_files(owner, workspace_id, files):
    if not files:
        raise resource_error("empty_file")
    valid, code, _ = validate_chat_uploads(files)
    if not valid:
        raise resource_error(code)
    workspace = lock_files_workspace(owner, workspace_id)
    current = workspace_files(workspace.id)
    if len(files) + len(current) > MAX_PROJECT_FILES:
        raise resource_error("workspace_file_limit", 409)
    project_size = sum(row.size for row in current)
    account_size = (
        owner_files(owner)
        .with_entities(db.func.coalesce(db.func.sum(ReMindWorkspaceFile.size), 0))
        .scalar()
    )
    names = {row.name_key for row in current}
    upload_root = uploads_root()
    upload_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    stored = []
    rows = []
    try:
        for file in files:
            item = store_validated_upload(file, upload_root)
            if item is None:
                raise resource_error("attachment_processing_failed")
            path = Path(item["path"])
            stored.append(path.name)
            size = path.stat().st_size
            project_size += size
            account_size += size
            if project_size > MAX_PROJECT_BYTES or account_size > MAX_ACCOUNT_BYTES:
                raise resource_error("workspace_storage_limit", 409)
            name = item["original_name"]
            key = sha256(name.casefold().encode()).hexdigest()
            if key in names:
                raise resource_error("workspace_file_duplicate", 409)
            names.add(key)
            row = ReMindWorkspaceFile(
                id=uuid4().hex,
                workspace_id=workspace.id,
                storage_name=path.name,
                original_name=name,
                name_key=key,
                mime_type=item["mime_type"],
                size=size,
            )
            db.session.add(row)
            rows.append(row)
        db.session.commit()
    except Exception:
        db.session.rollback()
        remove_uploads(stored)
        raise
    return [file_metadata(row) for row in rows]
