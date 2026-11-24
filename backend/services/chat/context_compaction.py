import hashlib
import json
import re

from sqlalchemy.exc import SQLAlchemyError

from backend.db.models import ChatContextCheckpoint, ChatShare, UserChatHistory, db
from backend.errors import ApiError
from backend.responses import logger
from backend.services.agent_runtime_settings import load_agent_runtime
from backend.services.chat.compaction_summary import (
    model_capacity,
    summarize_context,
    summary_lease,
    summary_pressure,
)
from backend.services.chat.conversation import materialize_conversation_history
from backend.services.chat.model_selection import selection_view

AUTO_MAX_MESSAGES = 40
AUTO_MAX_BYTES = 160_000
RETAIN_MESSAGES = 24
RETAIN_BYTES = 96_000
MANUAL_RETAIN_MESSAGES = 8
MANUAL_RETAIN_BYTES = 48_000
MAX_CHECKPOINTS = 8
MAX_EXCERPT_BYTES = 700
MAX_EXCERPTS = 18
HIDDEN = re.compile(
    r"<think(?:\s[^>]*)?>[\s\S]*?</think>|<tool_panel\s[^>]*>[\s\S]*?</tool_panel>",
    re.I,
)


def historical_messages(history):
    visible = []
    for message in history:
        if not isinstance(message, dict):
            continue
        parts = message.get("parts")
        if not isinstance(parts, list):
            parts = []
        text = "\n".join(
            value
            for part in parts
            if isinstance(part, dict) and isinstance(value := part.get("text"), str)
        )
        visible.append(
            {
                "id": message.get("id") if isinstance(message.get("id"), str) else "",
                "role": message.get("role")
                if message.get("role") in ("user", "model")
                else "model",
                "text": HIDDEN.sub("", text).strip(),
            }
        )
    return visible


def prefix_digests(records, boundaries):
    result = {}
    digest = hashlib.sha256(b"remind-chat-context-v1")
    last = max(boundaries, default=0)
    for position, record in enumerate(records[:last], 1):
        digest.update(json.dumps(record, ensure_ascii=True, separators=(",", ":")).encode())
        digest.update(b"\n")
        if position in boundaries:
            result[position] = digest.hexdigest()
    return result


def turn_boundary(records, max_messages, max_bytes):
    total = 0
    first = len(records)
    for index in range(len(records) - 1, -1, -1):
        total += len(records[index]["text"].encode("utf-8", errors="replace"))
        first = index
        if total >= max_bytes or len(records) - index >= max_messages:
            break
    while first > 0 and records[first]["role"] != "user":
        first -= 1
    return first


def _fits(records, byte_limit=AUTO_MAX_BYTES):
    return (
        len(records) <= AUTO_MAX_MESSAGES
        and sum(len(record["text"].encode("utf-8", errors="replace")) for record in records)
        <= byte_limit
    )


def _excerpt(text):
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= MAX_EXCERPT_BYTES:
        return text, False
    half = MAX_EXCERPT_BYTES // 2
    return raw[:half].decode("utf-8", errors="ignore") + "\n…\n" + raw[-half:].decode(
        "utf-8", errors="ignore"
    ), True


def checkpoint_excerpts(prefix):
    nonempty = [(number, entry) for number, entry in enumerate(prefix, 1) if entry["text"]]
    users = [item for item in nonempty if item[1]["role"] == "user"]
    leading = (users or nonempty)[:3]
    trailing = nonempty[-6:]
    chosen = {number: entry for number, entry in leading + trailing}
    candidates = [item for item in users if item[0] not in chosen]
    remaining = MAX_EXCERPTS - len(chosen)
    take = min(remaining, len(candidates))
    for offset in range(take):
        index = offset * len(candidates) // take
        number, entry = candidates[index]
        chosen[number] = entry
    result = []
    for number, entry in sorted(chosen.items()):
        content, trimmed = _excerpt(entry["text"])
        result.append(
            {"message": number, "role": entry["role"], "quote": content, "excerpt": trimmed}
        )
    return result


def _find_chat(owner, session_id, *, lock=False):
    if owner is None or not isinstance(session_id, str):
        return None
    public_shares = db.select(ChatShare.id).where(
        ChatShare.user_id == owner,
        ChatShare.session_id == session_id,
        ChatShare.is_public.is_(True),
    )
    query = (
        UserChatHistory.query.filter_by(user_id=owner, session_id=session_id, source="web")
        .filter(~public_shares.exists())
        .populate_existing()
    )
    return (query.with_for_update() if lock else query).one_or_none()


def _checkpoint_data(row):
    if row is None:
        return [], None
    stored = row.excerpts
    if isinstance(stored, dict):
        return stored.get("excerpts", []), stored.get("summary")
    return stored, None


def _checkpoint_view(covered, excerpts, summary):
    return {
        "covered_messages": covered,
        "excerpts": excerpts if summary is None else [],
        **({"summary": summary} if summary is not None else {}),
    }


def _cached_checkpoints(chat_id, size):
    return (
        ChatContextCheckpoint.query.filter_by(chat_id=chat_id)
        .filter(
            ChatContextCheckpoint.covered_count > 0,
            ChatContextCheckpoint.covered_count < size,
        )
        .order_by(ChatContextCheckpoint.covered_count.desc(), ChatContextCheckpoint.id.desc())
        .limit(MAX_CHECKPOINTS)
        .all()
    )


def _prefix_matches(chat, covered, digest):
    records = historical_messages(materialize_conversation_history(chat.get_messages()))
    return (
        covered < len(records)
        and records[covered]["role"] == "user"
        and prefix_digests(records, {covered}).get(covered) == digest
    )


def _save_checkpoint(owner, session_id, covered, digest, excerpts, summary):
    try:
        chat = _find_chat(owner, session_id, lock=True)
        if chat is None or not _prefix_matches(chat, covered, digest):
            db.session.rollback()
            return False
        existing = ChatContextCheckpoint.query.filter_by(
            chat_id=chat.id, prefix_digest=digest
        ).one_or_none()
        payload = excerpts if summary is None else {"excerpts": excerpts, "summary": summary}
        if existing is None:
            db.session.add(
                ChatContextCheckpoint(
                    chat_id=chat.id,
                    covered_count=covered,
                    prefix_digest=digest,
                    excerpts=payload,
                )
            )
            db.session.flush()
            stale = (
                db.select(ChatContextCheckpoint.id)
                .where(ChatContextCheckpoint.chat_id == chat.id)
                .order_by(ChatContextCheckpoint.id.desc())
                .offset(MAX_CHECKPOINTS)
            )
            db.session.execute(
                db.delete(ChatContextCheckpoint).where(ChatContextCheckpoint.id.in_(stale))
            )
        elif summary is not None and _checkpoint_data(existing)[1] is None:
            existing.excerpts = payload
        db.session.commit()
        return True
    except SQLAlchemyError:
        db.session.rollback()
        logger.warning("Could not cache conversation context checkpoint")
        return False


def _save_model_summary(chat, records, covered, digest, excerpts, prior, options, model, control):
    with summary_lease(chat.id) as acquired:
        if not acquired:
            raise ApiError("context_summary_busy", status=409, code="context_summary_busy")
        current = _find_chat(chat.user_id, chat.session_id)
        if current is None or not _prefix_matches(current, covered, digest):
            raise ApiError(
                "context_checkpoint_unavailable", status=409, code="context_checkpoint_unavailable"
            )
        existing = (
            ChatContextCheckpoint.query.filter_by(chat_id=chat.id, prefix_digest=digest)
            .populate_existing()
            .one_or_none()
        )
        summary = _checkpoint_data(existing)[1]
        if summary is not None:
            return summary
        older = _checkpoint_data(prior)[1]
        start = prior.covered_count if older else 0
        summary = summarize_context(
            chat.user_id, model, records[start:covered], older, excerpts, options, parent=control
        )
        replaced = sum(
            12 + len(record["text"].encode("utf-8", errors="replace"))
            for record in records[start:covered]
        ) + (len(json.dumps(older, ensure_ascii=False).encode()) if older else 0)
        if len(json.dumps(summary, ensure_ascii=False).encode()) >= replaced:
            raise ApiError(
                "context_summary_not_smaller", status=422, code="context_summary_not_smaller"
            )
        if older and older.get("partial_history"):
            summary["partial_history"] = True
        if control is not None:
            control.check()
        if not _save_checkpoint(chat.user_id, chat.session_id, covered, digest, excerpts, summary):
            raise ApiError(
                "context_checkpoint_unavailable", status=409, code="context_checkpoint_unavailable"
            )
        return summary


def compact_context(
    history, owner=None, session_id=None, *, force=False, settings=None, model=None, control=None
):
    chat = _find_chat(owner, session_id)
    if force and chat is None:
        raise ApiError("not_found", status=404, code="not_found")
    records = historical_messages(history)
    if not records or len(records) != len(history):
        return history, [], None
    options = settings if settings is not None else load_agent_runtime(owner)
    model_summary = chat is not None and options["contextSummaryMode"] == "model"
    selected = (
        selection_view(chat)
        if model_summary and (force or not options["contextSummaryModel"])
        else {}
    )
    answered = (selected.get("lastUsed") or {}).get("model")
    if model_summary and not answered:
        answered = next(
            (
                message["model_id"]
                for message in reversed(history)
                if message.get("role") == "model" and isinstance(message.get("model_id"), str)
            ),
            None,
        )
    active = model or (selected.get("next") or {}).get("model") or answered
    capacity, reserved = model_capacity(owner, active)
    byte_limit = AUTO_MAX_BYTES
    if model_summary:
        byte_limit, retention = summary_pressure(options, capacity, reserved, AUTO_MAX_BYTES)
    else:
        if capacity is not None and isinstance(active, str) and active.startswith("key/"):
            byte_limit = max(256, min(AUTO_MAX_BYTES, (capacity - (reserved or 0)) * 2))
        retention = min(RETAIN_BYTES, byte_limit * 3 // 5)
    cached = _cached_checkpoints(chat.id, len(history)) if chat is not None else []
    within_budget = _fits(records, byte_limit)
    if not cached and not force and within_budget:
        return history, [], None
    automatic = options["contextCompaction"] != "manual" and not within_budget
    manual_retention = min(MANUAL_RETAIN_BYTES, retention) if model_summary else MANUAL_RETAIN_BYTES
    target = (
        turn_boundary(records, MANUAL_RETAIN_MESSAGES, manual_retention)
        if force
        else turn_boundary(records, RETAIN_MESSAGES, retention)
        if automatic
        else 0
    )
    boundaries = {row.covered_count for row in cached if row.covered_count > 0}
    if target:
        boundaries.add(target)
    digests = prefix_digests(records, boundaries)
    valid = [
        row
        for row in cached
        if records[row.covered_count]["role"] == "user"
        and digests.get(row.covered_count) == row.prefix_digest
    ]
    checkpoint = next(
        (
            row
            for row in valid
            if _fits(records[row.covered_count :], byte_limit)
            and (not force or row.covered_count >= target)
            and (not (force and model_summary) or _checkpoint_data(row)[1] is not None)
        ),
        None,
    )
    if checkpoint is not None:
        covered = checkpoint.covered_count
        excerpts, summary = _checkpoint_data(checkpoint)
        if not model_summary:
            summary = None
    elif target:
        covered, excerpts = target, checkpoint_excerpts(records[:target])
        summary = None
        if model_summary:
            prior = next(
                (row for row in valid if row.covered_count < covered and _checkpoint_data(row)[1]),
                None,
            )
            summary_model = options["contextSummaryModel"] or answered or active
            try:
                summary = _save_model_summary(
                    chat,
                    records,
                    covered,
                    digests[covered],
                    excerpts,
                    prior,
                    options,
                    summary_model,
                    control,
                )
            except ApiError as error:
                if force:
                    raise
                logger.info("Using a local conversation checkpoint: %s", error.code)
        if chat is not None and summary is None:
            saved = _save_checkpoint(owner, session_id, covered, digests[covered], excerpts, None)
            if force and not saved:
                raise ApiError(
                    "context_checkpoint_unavailable",
                    status=409,
                    code="context_checkpoint_unavailable",
                )
    else:
        return history, [], None
    return history[covered:], records[:covered], _checkpoint_view(covered, excerpts, summary)


def prepare_generation_context(data, owner):
    history = data.get("history")
    if not isinstance(history, list):
        return
    private = data.get("_context_is_private_web") is True and owner is not None
    recent, previous, checkpoint = compact_context(
        history,
        owner if private else None,
        data.get("session_id"),
        settings=load_agent_runtime(owner),
        model=data.get("model"),
        control=data.get("_generation_control"),
    )
    if checkpoint is not None:
        data["_model_history"] = recent
        data["_context_checkpoint"] = checkpoint
        if private:
            data["_context_archive"] = previous


def session_checkpoint(owner, session_id):
    chat = _find_chat(owner, session_id)
    if chat is None:
        raise ApiError("not_found", status=404, code="not_found")
    records = historical_messages(materialize_conversation_history(chat.get_messages()))
    cached = _cached_checkpoints(chat.id, len(records))
    digests = prefix_digests(records, {row.covered_count for row in cached})
    return next(
        (
            _checkpoint_view(row.covered_count, *_checkpoint_data(row))
            for row in cached
            if records[row.covered_count]["role"] == "user"
            and digests.get(row.covered_count) == row.prefix_digest
        ),
        None,
    )


def delete_owner_checkpoints(owner):
    chats = db.select(UserChatHistory.id).where(UserChatHistory.user_id == owner)
    db.session.execute(
        db.delete(ChatContextCheckpoint).where(ChatContextCheckpoint.chat_id.in_(chats))
    )
