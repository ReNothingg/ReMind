from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field

from cryptography.fernet import InvalidToken
from sqlalchemy.exc import SQLAlchemyError

from backend.db.models import ChatProviderReplay, ChatShare, UserChatHistory, db
from backend.security.provider_secrets import (
    decrypt_provider_data,
    encrypt_provider_data,
    provider_master_key,
)
from backend.services.chat.cancellation import SESSION_ID
from backend.services.chat.conversation import materialize_conversation_history

MAX_TURNS = 8
MAX_TURN_BYTES = 384_000
MAX_RESTORE_BYTES = 768_000
MAX_FRAMES = 96
VERSION = 1
MEDIA_KEYS = {"inline_data", "inlineData", "input_image", "image_url", "file_data", "input_file"}
REPLAY_KEYS = {
    "signature",
    "thinking_signature",
    "thought_signature",
    "thoughtSignature",
    "encrypted_content",
    "reasoning",
    "reasoning_content",
    "reasoning_details",
    "tool_calls",
    "function_call",
    "functionCall",
}


def _encode(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _chain(previous, value):
    return hashlib.sha256(previous + b"\0" + _encode(value)).digest()


def wire_prefix(head, messages):
    digest = _chain(b"remind-provider-wire-prefix-v1", head)
    for message in messages:
        digest = _chain(digest, message)
    return digest.hex()


def history_digests(history):
    digest = hashlib.sha256(b"remind-provider-visible-history-v1").digest()
    for message in history:
        digest = _chain(
            digest,
            [
                message.get("id"),
                message.get("role"),
                message.get("parts"),
                message.get("model_id"),
                message.get("delivery_status"),
            ],
        )
        yield message.get("id"), digest.hex()


def history_digest(history):
    last = hashlib.sha256(b"remind-provider-visible-history-v1").hexdigest()
    for _, digest in history_digests(history):
        last = digest
    return last


def _private_chat_query(owner, session_id):
    public = (
        db.select(ChatShare.id)
        .where(
            ChatShare.user_id == owner,
            ChatShare.session_id == session_id,
            ChatShare.is_public.is_(True),
        )
        .exists()
    )
    return UserChatHistory.query.filter_by(
        user_id=owner, session_id=session_id, source="web"
    ).filter(~public)


def _visible_digest_map(history):
    return dict(history_digests(history))


def _properties(frames):
    stack = list(frames)
    useful = False
    while stack:
        part = stack.pop()
        if isinstance(part, dict):
            if MEDIA_KEYS.intersection(part) or part.get("type") in (
                "image",
                "document",
                "input_image",
                "input_file",
            ):
                return False, False
            useful |= bool(
                REPLAY_KEYS.intersection(part)
                or part.get("type") in ("function_call", "tool_use", "redacted_thinking")
            )
            stack.extend(part.values())
        elif isinstance(part, list):
            stack.extend(part)
    return True, useful


def _without_signed_thinking(item):
    parts = item.get("content")
    if item.get("role") != "assistant" or not isinstance(parts, list):
        return item
    content = [
        part
        for part in parts
        if part.get("type") != "redacted_thinking"
        and not (part.get("type") == "thinking" and part.get("signature"))
    ]
    return {**item, "content": content} if content else None


def _read_rows(chat_id, route_key, history):
    visible = _visible_digest_map(history)
    if not visible:
        return {}
    rows = (
        ChatProviderReplay.query.filter_by(chat_id=chat_id, route_key=route_key)
        .order_by(ChatProviderReplay.created_at.desc(), ChatProviderReplay.message_id.desc())
        .limit(MAX_TURNS)
        .all()
    )
    restored = {}
    budget = MAX_RESTORE_BYTES
    for row in rows:
        if visible.get(row.message_id) != row.history_digest or len(row.payload) > (
            MAX_TURN_BYTES * 2
        ):
            continue
        try:
            envelope = decrypt_provider_data(row.payload)
            if not isinstance(envelope, dict) or envelope.get("version") != VERSION:
                continue
            if (
                envelope.get("route_key") != route_key
                or envelope.get("history_digest") != row.history_digest
            ):
                continue
            frames = envelope.get("frames")
            if not isinstance(frames, list) or not 0 < len(frames) <= MAX_FRAMES:
                continue
            if not all(
                isinstance(frame, dict) and isinstance(frame.get("item"), dict) for frame in frames
            ):
                continue
            size = len(_encode(frames))
            if size > MAX_TURN_BYTES or size > budget or not _properties(frames)[0]:
                continue
        except (InvalidToken, TypeError, ValueError, KeyError, RecursionError):
            continue
        budget -= size
        restored[row.message_id] = frames
    return restored


@dataclass(frozen=True, repr=False)
class ReplayDraft:
    route_key: str
    profile_version: str
    workspace_id: str | None
    previous_history: str
    frames: list[dict]


@dataclass(repr=False)
class ReplayTurn:
    route_key: str
    profile_version: str
    workspace_id: str | None
    previous_history: str
    previous_frames: dict
    frames: list[dict] = field(default_factory=list)
    bytes_used: int = 0
    usable: bool = True

    def restore(self, messages, *, bound_head=None):
        result = []
        for message_id, item in messages:
            frames = self.previous_frames.get(message_id)
            if not frames:
                result.append(item)
                continue
            for frame in frames:
                replayed = frame["item"]
                if bound_head is not None and replayed.get("role") == "assistant":
                    if frame.get("prefix") != wire_prefix(bound_head, result):
                        replayed = _without_signed_thinking(replayed)
                if replayed is not None:
                    result.append(replayed)
        return result

    def append(self, item, *, prefix=None):
        if not self.usable:
            return
        frame = {"item": item, **({"prefix": prefix} if prefix is not None else {})}
        try:
            size = len(_encode(frame))
            self.usable = (
                self.bytes_used + size <= MAX_TURN_BYTES
                and len(self.frames) < MAX_FRAMES
                and _properties([frame])[0]
            )
        except (TypeError, ValueError, RecursionError):
            self.usable = False
        if not self.usable:
            self.frames.clear()
            return
        self.bytes_used += size
        self.frames.append(frame)

    def finish(self):
        if not self.usable or not self.frames or not _properties(self.frames)[1]:
            return None
        return ReplayDraft(
            self.route_key,
            self.profile_version,
            self.workspace_id,
            self.previous_history,
            list(self.frames),
        )


def begin_replay(owner, data, runtime, *, protocol, provider, model, endpoint, authority):
    session_id = data.get("session_id")
    if (
        not owner
        or not runtime.agent_settings.get("modelReplayEnabled")
        or data.get("_context_is_private_web") is not True
        or data.get("history_is_canonical") is not True
        or data.get("_automation")
        or data.get("_delegation")
        or data.get("telegram_agent")
        or not isinstance(session_id, str)
        or not SESSION_ID.fullmatch(session_id)
        or not authority
    ):
        return None
    from backend.services.agent_runtime_settings import replay_profile_version

    try:
        epoch = replay_profile_version(owner)
        if not epoch:
            return None
        workspace_id = runtime.prompts.project_id
        mind = data.get("active_mind") or {}
        resources = sorted(
            (record["workspace_file_id"], str(record.get("path") or ""), record.get("size"))
            for record in runtime.files
            if record.get("workspace_file_id")
        )
        imported = [
            (name, item.get("id"), item.get("modelInvocable"), item.get("userInvocable"))
            for name, item in sorted(runtime.prompts.imported_skills.items())
        ]
        context = [
            owner,
            session_id,
            protocol,
            provider,
            model,
            data.get("model"),
            endpoint,
            authority,
            epoch,
            workspace_id,
            mind.get("public_id"),
            mind.get("skill_ids"),
            sorted(runtime.prompts.access.available),
            resources,
            imported,
            sorted(data.get("selected_tools") or ()),
        ]
        if runtime.prompts.chat_references:
            context.append(
                [(item["session_id"], item["digest"]) for item in runtime.prompts.chat_references]
            )
        key = hmac.new(
            provider_master_key(), b"remind-provider-replay-v1\0" + _encode(context), hashlib.sha256
        ).hexdigest()
        history = data.get("history") or []
        chat = _private_chat_query(owner, session_id).one_or_none()
        if chat is not None and chat.workspace_id != workspace_id:
            return None
        restored = {}
        if chat is not None:
            try:
                with db.session.begin_nested():
                    restored = _read_rows(chat.id, key, history)
            except SQLAlchemyError:
                return None
        return ReplayTurn(key, epoch, workspace_id, history_digest(history), restored)
    except (InvalidToken, OSError, TypeError, ValueError, KeyError, RecursionError):
        return None


def save_replay(chat, graph, message_id, draft):
    from backend.services.agent_runtime_settings import replay_profile_version

    if (
        not isinstance(draft, ReplayDraft)
        or chat.source != "web"
        or chat.workspace_id != draft.workspace_id
    ):
        return
    path = materialize_conversation_history(graph)
    if (
        len(path) < 2
        or path[-1].get("id") != message_id
        or path[-2].get("role") != "user"
        or history_digest(path[:-2]) != draft.previous_history
    ):
        return
    if replay_profile_version(chat.user_id, lock=True) != draft.profile_version:
        return
    if (
        _private_chat_query(chat.user_id, chat.session_id)
        .with_entities(UserChatHistory.id)
        .scalar()
        != chat.id
    ):
        return
    digest = history_digest(path)
    payload = {
        "version": VERSION,
        "route_key": draft.route_key,
        "history_digest": digest,
        "frames": draft.frames,
    }
    try:
        if len(_encode(payload)) > MAX_TURN_BYTES:
            return
        secret = encrypt_provider_data(payload)
    except (OSError, TypeError, ValueError, RecursionError):
        return
    if db.session.get(ChatProviderReplay, (chat.id, message_id)) is not None:
        return
    db.session.add(
        ChatProviderReplay(
            chat_id=chat.id,
            message_id=message_id,
            route_key=draft.route_key,
            history_digest=digest,
            payload=secret,
        )
    )
    db.session.flush()
    old_ids = (
        db.select(ChatProviderReplay.message_id)
        .where(ChatProviderReplay.chat_id == chat.id)
        .order_by(ChatProviderReplay.created_at.desc(), ChatProviderReplay.message_id.desc())
        .offset(MAX_TURNS)
    )
    db.session.execute(
        db.delete(ChatProviderReplay).where(
            ChatProviderReplay.chat_id == chat.id, ChatProviderReplay.message_id.in_(old_ids)
        )
    )


def delete_chat_replays(chat_id):
    db.session.execute(db.delete(ChatProviderReplay).where(ChatProviderReplay.chat_id == chat_id))


def save_replay_cache(chat, graph, message_id, draft):
    if not isinstance(draft, ReplayDraft):
        return
    try:
        with db.session.begin_nested():
            save_replay(chat, graph, message_id, draft)
    except (SQLAlchemyError, InvalidToken, OSError, ValueError, TypeError, RecursionError):
        return


def delete_owner_replays(owner):
    chats = db.select(UserChatHistory.id).where(UserChatHistory.user_id == owner)
    db.session.execute(db.delete(ChatProviderReplay).where(ChatProviderReplay.chat_id.in_(chats)))
