import hashlib
import json
from itertools import islice
from unicodedata import normalize

from sqlalchemy import and_, case, func

from backend.db.models import ChatShare, ReMindWorkspace, UserChatHistory, db
from backend.errors import ApiError
from backend.services.chat.conversation import (
    CHAT_REFERENCE_ID,
    CHAT_REFERENCE_WORKSPACE,
    MAX_CHAT_REFERENCES,
    materialize_conversation_history,
    normalize_chat_references,
)

REFERENCE_CANDIDATES = 30
MAX_SOURCE_CHARACTERS = 8_000_000
MAX_REFERENCE_BYTES = 65_536
DEFAULT_REFERENCE_BYTES = 16_384


def reference_error(code="chat_reference_unavailable", status=404):
    return ApiError(code, status=status, code=code)


def parse_reference_ids(value):
    if value is None:
        return []
    if isinstance(value, str) and len(value) <= 512:
        try:
            value = json.loads(value)
        except ValueError:
            value = None
    if (
        not isinstance(value, list)
        or len(value) > MAX_CHAT_REFERENCES
        or any(not isinstance(item, str) or not CHAT_REFERENCE_ID.fullmatch(item) for item in value)
        or len(set(value)) != len(value)
    ):
        raise reference_error("chat_reference_invalid", 400)
    return value


def _public_share(owner, session_id):
    return (
        db.select(ChatShare.id)
        .where(
            ChatShare.user_id == owner,
            ChatShare.session_id == session_id,
            ChatShare.is_public.is_(True),
        )
        .exists()
    )


def _owned_project(owner, workspace_id):
    return (
        ReMindWorkspace.query.filter_by(id=workspace_id, user_id=owner)
        .with_entities(ReMindWorkspace.id)
        .first()
        is not None
    )


def reference_target_scope(owner, session_id, workspace_id=None):
    if not owner or (session_id is not None and not CHAT_REFERENCE_ID.fullmatch(session_id)):
        raise reference_error()
    if workspace_id is not None and (
        not CHAT_REFERENCE_WORKSPACE.fullmatch(workspace_id)
        or not _owned_project(owner, workspace_id)
    ):
        raise reference_error()
    if session_id is None:
        return workspace_id
    row = db.session.execute(
        db.select(
            UserChatHistory.workspace_id, UserChatHistory.source, _public_share(owner, session_id)
        ).where(UserChatHistory.user_id == owner, UserChatHistory.session_id == session_id)
    ).one_or_none()
    if row is None:
        return workspace_id
    scope, source, shared = row
    if (
        source != "web"
        or shared
        or (workspace_id is not None and scope != workspace_id)
        or (scope is not None and workspace_id is None and not _owned_project(owner, scope))
    ):
        raise reference_error()
    return scope


def _private_web_chats(owner):
    return UserChatHistory.query.filter_by(user_id=owner, source="web").filter(
        ~_public_share(owner, UserChatHistory.session_id),
        UserChatHistory.messages_data != "[]",
    )


def reference_candidates(owner, current, workspace, query):
    scope = reference_target_scope(owner, current, workspace)
    query = query.strip()
    if len(query) > 120:
        raise reference_error("chat_reference_invalid", 400)
    rows = (
        _private_web_chats(owner)
        .outerjoin(
            ReMindWorkspace,
            and_(
                ReMindWorkspace.id == UserChatHistory.workspace_id, ReMindWorkspace.user_id == owner
            ),
        )
        .filter((UserChatHistory.workspace_id.is_(None) | ReMindWorkspace.id.is_not(None)))
    )
    if current:
        rows = rows.filter(UserChatHistory.session_id != current)
    ordered = rows.with_entities(
        UserChatHistory.session_id, UserChatHistory.title, ReMindWorkspace.name
    ).order_by(
        case((UserChatHistory.workspace_id == scope, 0), else_=1),
        UserChatHistory.updated_at.desc(),
        UserChatHistory.id.desc(),
    )
    if query:
        term = normalize("NFKC", query).casefold()
        matches = (
            row
            for row in ordered.yield_per(100)
            if term in normalize("NFKC", row.title or "").casefold()
        )
        selected = list(islice(matches, REFERENCE_CANDIDATES))
    else:
        selected = ordered.limit(REFERENCE_CANDIDATES).all()
    return [
        {"session_id": session, "title": title or "", "workspace_name": project}
        for session, title, project in selected
    ]


def _projected_history(chat):
    from backend.services.chat.context_compaction import historical_messages
    from backend.services.tools.interaction_tools import strip_private_panels

    path = materialize_conversation_history(chat.get_messages())
    records = historical_messages(
        record for record in path if record.get("role") in {"user", "model"}
    )
    for record in records:
        record["text"] = strip_private_panels(record["text"]).strip()
    return records


def _digest(records):
    payload = json.dumps(records, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _source(owner, session_id):
    row = (
        _private_web_chats(owner)
        .filter_by(session_id=session_id)
        .filter(func.length(UserChatHistory.messages_data) <= MAX_SOURCE_CHARACTERS)
        .populate_existing()
        .one_or_none()
    )
    if row and row.workspace_id and not _owned_project(owner, row.workspace_id):
        return None
    return row


def capture_references(owner, session_id, workspace, source_ids):
    captured = []
    for source in source_ids:
        if source == session_id or not (row := _source(owner, source)):
            raise reference_error()
        records = _projected_history(row)
        if not any(record["text"] for record in records):
            raise reference_error()
        captured.append(
            {
                "session_id": source,
                "title": row.title or "",
                "message_id": records[-1]["id"],
                "digest": _digest(records),
                "workspace_id": row.workspace_id,
                "target_workspace_id": workspace,
            }
        )
    if len(normalize_chat_references(captured)) != len(source_ids):
        raise reference_error()
    return captured


def latest_references(current, history):
    collected = {}
    for message in [{"chat_references": current}, *reversed(history)]:
        for item in message.get("chat_references", []):
            collected.setdefault(item["session_id"], item)
            if len(collected) >= MAX_CHAT_REFERENCES:
                return list(collected.values())
    return list(collected.values())


def _records_through(owner, reference):
    row = _source(owner, reference["session_id"])
    if not row or row.workspace_id != reference["workspace_id"]:
        return []
    records = _projected_history(row)
    end = next(
        (index for index, item in enumerate(records, 1) if item["id"] == reference["message_id"]), 0
    )
    prefix = records[:end]
    return prefix if end and _digest(prefix) == reference["digest"] else []


def tag_safe_json(value):
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("<", r"\u003c")
        .replace(">", r"\u003e")
        .replace("&", r"\u0026")
    )


def _byte_size(value):
    return len(tag_safe_json(value).encode("utf-8", errors="replace"))


def _retained_reference(reference, records, maximum):
    items = [
        {
            "number": index,
            "role": "assistant" if row["role"] == "model" else "user",
            "text": row["text"],
        }
        for index, row in enumerate(records, 1)
        if row["text"]
    ]
    frame = {
        "session_id": reference["session_id"],
        "label": reference["title"],
        "conversation": [],
        "omitted_messages": 0,
        "truncated": False,
    }
    selected = frame["conversation"]
    for item in reversed(items):
        selected.append(item)
        if _byte_size(frame) <= maximum - 24:
            continue
        selected.pop()
        if not selected:
            raw = item["text"].encode("utf-8", errors="replace")
            lo, hi = 0, min(maximum, len(raw) // 2)
            shortened = {**item, "text": ""}
            selected.append(shortened)
            while lo < hi:
                middle = (lo + hi + 1) // 2
                shortened["text"] = _excerpt(raw, middle)
                if _byte_size(frame) <= maximum - 24:
                    lo = middle
                else:
                    hi = middle - 1
            shortened["text"] = _excerpt(raw, lo)
            frame["truncated"] = True
        break
    selected.reverse()
    frame["omitted_messages"] = len(items) - len(selected)
    return frame


def _excerpt(raw, length):
    if not length:
        return ""
    return (
        raw[:length].decode("utf-8", errors="ignore")
        + "\n…\n"
        + raw[-length:].decode("utf-8", errors="ignore")
    )


def resolve_references(owner, session_id, workspace, model, references):
    if not references:
        return (), []
    from backend.services.chat.compaction_summary import model_capacity

    try:
        scope = reference_target_scope(owner, session_id, workspace)
    except ApiError:
        return (), []
    capacity, reserved = model_capacity(owner, model)
    budget = (
        DEFAULT_REFERENCE_BYTES
        if not capacity
        else max(
            2048,
            min(MAX_REFERENCE_BYTES, (capacity - (reserved or 0)) * 2 // (5 * len(references))),
        )
    )
    active, frames = [], []
    for reference in references:
        if reference["target_workspace_id"] != scope or reference["session_id"] == session_id:
            continue
        if records := _records_through(owner, reference):
            active.append(reference)
            frames.append(_retained_reference(reference, records, budget))
    return tuple(active), frames


def read_reference(owner, destination, references, arguments):
    reference = next(
        (item for item in references if item["session_id"] == arguments["session_id"]), None
    )
    if reference is None:
        return {"ok": False, "error": "chat_reference_unavailable"}
    try:
        scope = reference_target_scope(owner, destination)
    except ApiError:
        return {"ok": False, "error": "chat_reference_unavailable"}
    records = (
        _records_through(owner, reference) if scope == reference["target_workspace_id"] else []
    )
    number, offset = arguments["message"], arguments.get("offset", 0)
    if not 1 <= number <= len(records):
        return {"ok": False, "error": "chat_reference_unavailable"}
    item = records[number - 1]
    if offset > len(item["text"]):
        return {"ok": False, "error": "offset_out_of_range"}
    end = min(len(item["text"]), offset + arguments.get("max_characters", 6000))
    return {
        "ok": True,
        "label": reference["title"],
        "message": number,
        "role": item["role"],
        "text": item["text"][offset:end],
        "next_offset": end if end < len(item["text"]) else None,
    }
