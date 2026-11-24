from __future__ import annotations

import codecs
import csv
import json
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from pathlib import PurePosixPath
from uuid import uuid4

from backend.db.models import ReMindWorkspaceFile, UserChatHistory, WorkspacePatchProposal, db
from backend.errors import ApiError
from backend.services import project_resources as resources
from backend.services.automation_timing import iso_utc, utc_now
from backend.services.project_patch_format import (
    MAX_COMPARISONS,
    PatchError,
    apply_hunks,
    parse_patch,
)
from backend.services.tools.artifact_workspace import TEXT_EXTENSIONS, spreadsheet_safe_csv

MAX_TEXT_BYTES = 512 * 1024
MAX_READ_BYTES = 4 * 1024 * 1024
MAX_PENDING = 24
PROPOSAL_LIFETIME = timedelta(days=2)


@dataclass(slots=True)
class FileState:
    name: str
    row: ReMindWorkspaceFile | None
    size: int
    mime: str
    raw: bytes | None = None


@dataclass(slots=True)
class PatchPlan:
    files: list[FileState]
    changes: list[dict]
    revision: str


def _key(path):
    return unicodedata.normalize("NFC", path).casefold()


def _path(value):
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 240
        or unicodedata.normalize("NFC", value) != value
    ):
        raise PatchError("workspace_patch_path_invalid")
    if any(character in value for character in ("\\", ":", "\0")) or any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value
    ):
        raise PatchError("workspace_patch_path_invalid")
    parts = value.split("/")
    if len(parts) > 10 or any(
        not part or part in (".", "..") or part != part.strip() or part.endswith(".")
        for part in parts
    ):
        raise PatchError("workspace_patch_path_invalid")
    return value


def _mime(path):
    suffix = PurePosixPath(path).suffix.lower()
    if suffix not in TEXT_EXTENSIONS:
        raise PatchError("workspace_patch_text_required")
    return {".csv": "text/csv", ".json": "application/json", ".md": "text/markdown"}.get(
        suffix, "text/plain"
    )


def _updated_content(path, text, *, bom=False):
    suffix = PurePosixPath(path).suffix.lower()
    escaped = False
    if "\0" in text:
        raise PatchError("workspace_patch_text_required")
    try:
        if suffix == ".json":
            json.loads(text)
        if suffix == ".csv" and text:
            sanitized, escaped = spreadsheet_safe_csv(text)
            if escaped:
                text = sanitized
        encoded = text.encode("utf-8-sig" if bom else "utf-8")
    except (ValueError, UnicodeError, csv.Error, RecursionError):
        raise PatchError("workspace_patch_content_invalid") from None
    if len(encoded) > MAX_TEXT_BYTES:
        raise PatchError("workspace_patch_too_large")
    return encoded, escaped


def _read(current, originals):
    if current.raw is not None:
        return current.raw
    row = current.row
    if row is None:
        raise PatchError("workspace_patch_conflict")
    if row.id not in originals:
        if sum(len(raw) for raw in originals.values()) + current.size > MAX_READ_BYTES:
            raise PatchError("workspace_patch_too_large")
        originals[row.id] = resources.read_workspace_bytes(
            resources.resource_path(row.storage_name), MAX_TEXT_BYTES
        )
        if sum(len(raw) for raw in originals.values()) > MAX_READ_BYTES:
            raise PatchError("workspace_patch_too_large")
    return originals[row.id]


def build_plan(current, patch):
    state = {
        _key(row.original_name): FileState(row.original_name, row, row.size, row.mime_type)
        for row in current
    }
    if len(state) != len(current):
        raise PatchError("workspace_patch_conflict")
    originals = {}
    changes = []
    budget = [MAX_COMPARISONS]
    for operation in parse_patch(patch):
        try:
            escaped = False
            name = _path(operation.path)
            key = _key(name)
            destination = (
                _path(operation.destination) if operation.destination is not None else None
            )
            entry = state.get(key)
            if operation.kind == "add":
                if entry is not None:
                    raise PatchError("workspace_patch_destination_exists")
                mime = _mime(name)
                content, escaped = _updated_content(
                    name, "".join(line + "\n" for line in operation.added)
                )
                state[key] = FileState(name, None, len(content), mime, content)
            elif entry is None:
                raise PatchError("workspace_patch_source_unavailable")
            elif operation.kind == "delete":
                del state[key]
            else:
                target = destination or entry.name
                mime = _mime(target)
                target_key = _key(target)
                if destination is not None and target_key in state:
                    raise PatchError("workspace_patch_destination_exists")
                before = _read(entry, originals)
                if b"\0" in before:
                    raise PatchError("workspace_patch_text_required")
                try:
                    text = before.decode("utf-8-sig")
                except UnicodeError:
                    raise PatchError("workspace_patch_text_required") from None
                text = apply_hunks(text, operation.hunks, budget)
                content, escaped = _updated_content(
                    target, text, bom=before.startswith(codecs.BOM_UTF8)
                )
                del state[key]
                state[target_key] = FileState(target, entry.row, len(content), mime, content)
                name = entry.name
                if destination is None and content == before:
                    continue
            changes.append(
                {
                    "kind": "move" if destination is not None else operation.kind,
                    "path": name,
                    **({"destination": destination} if destination is not None else {}),
                    **({"spreadsheet_formulas_escaped": True} if escaped else {}),
                }
            )
        except PatchError as error:
            if error.line is None:
                raise PatchError(error.code, operation.line) from None
            raise
    final_files = list(state.values())
    for entry in final_files:
        if entry.row is not None and entry.raw == originals.get(entry.row.id):
            entry.raw = None
    if len(current) == len(final_files) and all(
        entry.row is not None and entry.name == entry.row.original_name and entry.raw is None
        for entry in final_files
    ):
        raise PatchError("workspace_patch_no_changes")
    revision = sha256(
        json.dumps(
            [
                [
                    row.id,
                    row.original_name,
                    row.storage_name,
                    row.size,
                    row.mime_type,
                    sha256(originals[row.id]).hexdigest() if row.id in originals else None,
                ]
                for row in sorted(current, key=lambda item: item.id)
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return PatchPlan(final_files, changes, revision)


def _plan(current, patch):
    try:
        return build_plan(current, patch)
    except PatchError as error:
        raise ApiError(
            error.code,
            status=422,
            code=error.code,
            extra={"line": error.line} if error.line is not None else None,
        ) from None


def _check_quota(owner, current, plan):
    resources.validate_storage_limits(
        owner, current, len(plan.files), sum(item.size for item in plan.files)
    )


def propose(owner, workspace_id, session_id, request_id, patch):
    workspace = resources.lock_files_workspace(owner, workspace_id)
    chat = resources.private_workspace_chat(owner, workspace.id, session_id, lock=True)
    now = utc_now()
    proposals = WorkspacePatchProposal.query.filter_by(user_id=owner)
    existing = proposals.filter_by(chat_id=chat.id, request_id=request_id).one_or_none()
    if existing is not None:
        if (
            existing.workspace_id == workspace.id
            and existing.patch == patch
            and existing.expires_at > now
        ):
            db.session.commit()
            return existing
        raise resources.resource_error("workspace_patch_already_proposed", 409)
    proposals.filter(WorkspacePatchProposal.expires_at <= now).delete(synchronize_session=False)
    if proposals.filter(WorkspacePatchProposal.applied_at.is_(None)).count() >= MAX_PENDING:
        raise resources.resource_error("workspace_patch_limit", 409)
    current = resources.workspace_files(workspace.id)
    plan = _plan(current, patch)
    _check_quota(owner, current, plan)
    proposal = WorkspacePatchProposal(
        id=uuid4().hex,
        user_id=owner,
        workspace_id=workspace.id,
        chat_id=chat.id,
        request_id=request_id,
        patch=patch,
        base_revision=plan.revision,
        changes=plan.changes,
        expires_at=now + PROPOSAL_LIFETIME,
    )
    db.session.add(proposal)
    db.session.commit()
    return proposal


def _find(owner, workspace_id, proposal_id, *, lock=False):
    query = WorkspacePatchProposal.query.filter_by(
        id=proposal_id, user_id=owner, workspace_id=workspace_id
    )
    row = (query.with_for_update() if lock else query).one_or_none()
    if row is None:
        raise resources.resource_error("workspace_patch_not_found", 404)
    if row.expires_at <= utc_now():
        raise resources.resource_error("workspace_patch_expired", 410)
    origin = db.session.get(UserChatHistory, row.chat_id)
    if origin is None:
        raise resources.resource_error("workspace_patch_not_found", 404)
    resources.private_workspace_chat(owner, workspace_id, origin.session_id, lock=lock)
    return row


def _summary(row):
    return {
        "id": row.id,
        "changes": row.changes,
        "patch": row.patch,
        "applied_at": iso_utc(row.applied_at),
    }


def inspect(owner, workspace_id, proposal_id):
    resources.owned_workspace(owner, workspace_id)
    return _summary(_find(owner, workspace_id, proposal_id))


def apply(owner, workspace_id, proposal_id):
    workspace = resources.lock_files_workspace(owner, workspace_id)
    proposal = _find(owner, workspace.id, proposal_id, lock=True)
    if proposal.applied_at is not None:
        return _summary(proposal)
    current = resources.workspace_files(workspace.id)
    try:
        plan = _plan(current, proposal.patch)
    except ApiError as error:
        if error.status in (404, 422):
            raise resources.resource_error("workspace_patch_stale", 409) from None
        raise
    if plan.revision != proposal.base_revision or plan.changes != proposal.changes:
        raise resources.resource_error("workspace_patch_stale", 409)
    _check_quota(owner, current, plan)
    live = {entry.row.id for entry in plan.files if entry.row is not None}
    staged = []
    retired = []
    try:
        for row in current:
            if row.id not in live:
                retired.append(row.storage_name)
                db.session.delete(row)
        for entry in plan.files:
            row = entry.row
            if row is not None and entry.name != row.original_name:
                row.name_key = uuid4().hex
        db.session.flush()
        for entry in plan.files:
            row = entry.row
            if entry.raw is None and row is not None and row.original_name == entry.name:
                continue
            if entry.raw is not None:
                storage = resources.stage_workspace_bytes(
                    entry.raw, PurePosixPath(entry.name).suffix.lower()
                )
                staged.append(storage)
                if row is not None:
                    retired.append(row.storage_name)
            elif row is not None:
                storage = row.storage_name
            else:
                raise resources.resource_error("workspace_patch_conflict", 409)
            if row is None:
                row = ReMindWorkspaceFile(id=uuid4().hex, workspace_id=workspace.id)
                db.session.add(row)
            row.original_name = entry.name
            row.name_key = sha256(_key(entry.name).encode()).hexdigest()
            row.storage_name = storage
            row.mime_type = entry.mime
            row.size = entry.size
        proposal.applied_at = utc_now()
        db.session.commit()
    except Exception:
        db.session.rollback()
        resources.remove_uploads(staged)
        raise
    resources.remove_uploads(retired)
    return _summary(proposal)
