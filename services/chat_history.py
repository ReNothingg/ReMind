import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
import uuid
import weakref
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

from flask import has_request_context, request, session
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from config import (
    ALLOW_GUEST_CHATS_SAVE,
    ALLOWED_HOSTS,
    BACKEND_URL,
    CHAT_MAX_VARIANTS_PER_TURN,
    CHATS_FOLDER,
    SECRET_KEY,
)
from services.canvas_tools import normalize_canvas_textdoc
from utils.auth import ChatShare, UserChatHistory, db
from utils.responses import logger

SESSION_LOCKS: weakref.WeakValueDictionary[str, threading.Lock] = weakref.WeakValueDictionary()
SESSION_LOCKS_GUARD = threading.Lock()


def _is_allowed_hostname(hostname: Optional[str]) -> bool:
    if not hostname:
        return False

    host = hostname.lower()
    for allowed in ALLOWED_HOSTS:
        if not allowed:
            continue

        allowed_host = allowed.lower()
        if allowed_host.startswith("."):
            bare = allowed_host[1:]
            if host == bare or host.endswith(f".{bare}"):
                return True
            continue

        if host == allowed_host:
            return True

    return False


def _get_public_base_url() -> str:
    if BACKEND_URL:
        return BACKEND_URL.rstrip("/")

    parsed = urlparse(request.host_url)
    if _is_allowed_hostname(parsed.hostname):
        return request.host_url.rstrip("/")

    return ""


def _acquire_session_lock(safe_session_id: str) -> threading.Lock:
    with SESSION_LOCKS_GUARD:
        lock = SESSION_LOCKS.get(safe_session_id)
        if lock is None:
            lock = threading.Lock()
            SESSION_LOCKS[safe_session_id] = lock
        return lock


def read_chat_file(safe_session_id: str) -> dict:
    chat_file_path = CHATS_FOLDER / f"{safe_session_id}.json"
    if not chat_file_path.exists():
        return {}

    try:
        with open(chat_file_path, "r", encoding="utf-8") as file_obj:
            return json.load(file_obj)
    except Exception:
        return {}


def chat_file_exists(session_id: str) -> bool:
    safe_session_id = secure_filename(str(session_id))
    return bool(safe_session_id and (CHATS_FOLDER / f"{safe_session_id}.json").is_file())


def delete_guest_chat_file(session_id: str) -> bool:
    safe_session_id = secure_filename(str(session_id))
    if not safe_session_id:
        return False
    path = CHATS_FOLDER / f"{safe_session_id}.json"
    lock = _acquire_session_lock(safe_session_id)
    with lock:
        if not path.exists():
            return False
        path.unlink()
        return True


def _generate_guest_session_token(session_id: str, timestamp: int) -> str:
    message = f"{session_id}:{timestamp}".encode("utf-8")
    secret_key = (SECRET_KEY or "").encode("utf-8")
    signature = hmac.new(secret_key, message, hashlib.sha256).hexdigest()
    token_data = f"{session_id}:{timestamp}:{signature}"
    return base64.b64encode(token_data.encode("utf-8")).decode("utf-8")


def _verify_guest_session_token(token: str, session_id: str, max_age_seconds: int = 604800) -> bool:
    try:
        token_data = base64.b64decode(token.encode("utf-8")).decode("utf-8")
        parts = token_data.split(":")
        if len(parts) != 3:
            return False

        token_session_id, timestamp_str, signature = parts
        if token_session_id != session_id:
            logger.warning("Guest chat token session ID mismatch")
            return False

        timestamp = int(timestamp_str)
        current_time = int(time.time())
        if current_time - timestamp > max_age_seconds:
            logger.warning("Token expired: %s seconds old", current_time - timestamp)
            return False

        message = f"{session_id}:{timestamp}".encode("utf-8")
        secret_key = (SECRET_KEY or "").encode("utf-8")
        expected_signature = hmac.new(secret_key, message, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            logger.warning("Guest chat token signature mismatch")
            return False

        return True
    except Exception as exc:
        logger.warning("Guest chat token verification failed (%s)", type(exc).__name__)
        return False


def _get_chat_access_token_from_request() -> Optional[str]:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return request.args.get("chat_token")


def has_valid_guest_session_token(session_id: str) -> bool:
    safe_session_id = secure_filename(str(session_id))
    if not safe_session_id or not ALLOW_GUEST_CHATS_SAVE or not has_request_context():
        return False

    token = _get_chat_access_token_from_request()
    return bool(token and _verify_guest_session_token(token, safe_session_id))


def read_chat_file_secure(safe_session_id: str, require_auth: bool = False) -> dict:
    if has_request_context() and session.get("user_id") is not None:
        return read_chat_file(safe_session_id)

    if require_auth:
        if not has_request_context():
            return {}
        if not ALLOW_GUEST_CHATS_SAVE:
            logger.warning("Guest chat access denied because guest persistence is disabled")
            return {}

        if not has_valid_guest_session_token(safe_session_id):
            logger.warning("Unauthorized access attempt to guest chat")
            return {}

    return read_chat_file(safe_session_id)


def resolve_session_identifier(session_identifier: str):
    safe_identifier = secure_filename(str(session_identifier))
    share_entry = (
        ChatShare.query.filter(
            (ChatShare.session_id == safe_identifier) | (ChatShare.public_id == safe_identifier)
        ).first()
        if safe_identifier
        else None
    )
    resolved_session_id = share_entry.session_id if share_entry else safe_identifier
    return resolved_session_id, share_entry


def build_share_url(public_id: str) -> str:
    base = _get_public_base_url()
    return f"{base}/c/{public_id}" if base else f"/c/{public_id}"


def write_chat_file(safe_session_id: str, data: dict) -> None:
    CHATS_FOLDER.mkdir(parents=True, exist_ok=True)
    chat_file_path = CHATS_FOLDER / f"{safe_session_id}.json"
    tmp_path = CHATS_FOLDER / f"{safe_session_id}.json.tmp"

    try:
        with open(tmp_path, "w", encoding="utf-8") as file_obj:
            json.dump(data, file_obj, ensure_ascii=False, indent=2)
        os.replace(str(tmp_path), str(chat_file_path))
    finally:
        if tmp_path.exists():
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def replace_canvas_textdoc_in_messages(messages: list, value: Any) -> tuple[list, dict | None]:
    """Replace the newest matching Canvas document without rewriting older versions."""
    textdoc = normalize_canvas_textdoc(value)
    if not textdoc or not isinstance(messages, list):
        return messages, None

    target_id = textdoc.get("id")
    target_name = textdoc.get("name")
    target_type = textdoc.get("type")

    def matches(candidate: Any) -> bool:
        if not isinstance(candidate, dict):
            return False
        candidate_id = candidate.get("id")
        if target_id and candidate_id:
            return candidate_id == target_id
        return candidate.get("name") == target_name and candidate.get("type") == target_type

    updated_messages = list(messages)
    for message_index in range(len(updated_messages) - 1, -1, -1):
        raw_message = updated_messages[message_index]
        if not isinstance(raw_message, dict):
            continue
        message = dict(raw_message)
        changed = False

        direct_key = "canvas_textdoc" if "canvas_textdoc" in message else "canvasTextdoc"
        if matches(message.get(direct_key)):
            message[direct_key] = textdoc
            changed = True

        variants = message.get("variants")
        if isinstance(variants, list):
            next_variants = list(variants)
            for variant_index in range(len(next_variants) - 1, -1, -1):
                raw_variant = next_variants[variant_index]
                if not isinstance(raw_variant, dict):
                    continue
                variant = dict(raw_variant)
                variant_key = "canvas_textdoc" if "canvas_textdoc" in variant else "canvasTextdoc"
                if matches(variant.get(variant_key)):
                    variant[variant_key] = textdoc
                    next_variants[variant_index] = variant
                    changed = True
                    break
            if changed:
                message["variants"] = next_variants

        updates_key = "canvas_updates" if "canvas_updates" in message else "canvasUpdates"
        updates = message.get(updates_key)
        if isinstance(updates, list):
            next_updates = list(updates)
            for update_index in range(len(next_updates) - 1, -1, -1):
                raw_update = next_updates[update_index]
                if not isinstance(raw_update, dict) or not matches(raw_update.get("textdoc")):
                    continue
                update = dict(raw_update)
                update["textdoc"] = textdoc
                next_updates[update_index] = update
                changed = True
                break
            if changed:
                message[updates_key] = next_updates

        if changed:
            updated_messages[message_index] = message
            return updated_messages, textdoc

    return messages, None


def save_canvas_textdoc_to_history(
    session_id: str,
    value: Any,
    *,
    user_id: int | None = None,
    guest_file: bool = False,
) -> dict | None:
    """Persist one Canvas edit after the route has authorized the caller."""
    safe_session_id = secure_filename(str(session_id))
    if not safe_session_id:
        return None

    lock = _acquire_session_lock(safe_session_id)
    with lock:
        if user_id is not None:
            for _attempt in range(3):
                chat = UserChatHistory.query.filter_by(
                    user_id=user_id, session_id=session_id
                ).first()
                if not chat:
                    return None
                previous_messages_data = chat.messages_data
                messages, textdoc = replace_canvas_textdoc_in_messages(chat.get_messages(), value)
                if not textdoc:
                    return None
                updated = (
                    UserChatHistory.query.filter_by(id=chat.id)
                    .filter(UserChatHistory.messages_data == previous_messages_data)
                    .update(
                        {
                            "messages_data": json.dumps(messages, ensure_ascii=False),
                            "updated_at": datetime.utcnow(),
                        },
                        synchronize_session=False,
                    )
                )
                if updated != 1:
                    db.session.rollback()
                    continue
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    raise
                return textdoc
            raise RuntimeError("chat_concurrent_update")

        if not guest_file:
            return None
        data = read_chat_file(safe_session_id)
        if not data:
            return None
        messages, textdoc = replace_canvas_textdoc_in_messages(data.get("history", []), value)
        if not textdoc:
            return None
        next_data = dict(data)
        next_data["history"] = messages
        next_data["last_updated"] = time.time()
        write_chat_file(safe_session_id, next_data)
        return textdoc


def _new_message_id() -> str:
    return f"m_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"


def normalize_message(msg: Any) -> dict:
    try:
        if not isinstance(msg, dict):
            return {
                "id": _new_message_id(),
                "role": "user",
                "parts": [{"text": str(msg)}],
                "timestamp": int(time.time()),
            }

        role = msg.get("role", "user")
        parts = msg.get("parts") or (
            [{"text": msg.get("text")}] if msg.get("text") else [{"text": ""}]
        )
        normalized = {
            "id": msg.get("id") or _new_message_id(),
            "role": role,
            "parts": parts,
            "timestamp": msg.get("timestamp") or int(time.time()),
        }
        sources = msg.get("sources")
        if isinstance(sources, list) and sources:
            normalized["sources"] = sources
        github_tool = msg.get("github_tool")
        if isinstance(github_tool, dict) and github_tool:
            normalized["github_tool"] = github_tool
        canvas_textdoc = msg.get("canvas_textdoc") or msg.get("canvasTextdoc")
        if isinstance(canvas_textdoc, dict) and canvas_textdoc:
            normalized["canvas_textdoc"] = canvas_textdoc
        canvas_updates = msg.get("canvas_updates") or msg.get("canvasUpdates")
        if isinstance(canvas_updates, list) and canvas_updates:
            normalized["canvas_updates"] = canvas_updates
        request_id = msg.get("request_id")
        if isinstance(request_id, str) and request_id:
            normalized["request_id"] = request_id[:100]
        delivery_status = msg.get("delivery_status")
        if delivery_status in {"complete", "interrupted"}:
            normalized["delivery_status"] = delivery_status
        parent_id = msg.get("parent_id")
        if parent_id is None or isinstance(parent_id, str):
            normalized["parent_id"] = parent_id
        normalized["is_active"] = bool(msg.get("is_active", True))
        return normalized
    except Exception:
        return {
            "id": _new_message_id(),
            "role": "user",
            "parts": [{"text": ""}],
            "timestamp": int(time.time()),
        }


def ensure_conversation_graph(messages: list[Any]) -> list[dict]:
    """Normalize legacy flat histories into a branch-aware message graph.

    Consecutive messages with the same role are treated as historical alternatives.
    This repairs the legacy regeneration bug that appended model replies as new turns.
    """
    raw_messages = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        candidate = dict(message)
        if not candidate.get("id"):
            fingerprint = hashlib.sha256(
                f"{index}:{_message_signature(candidate)}".encode("utf-8")
            ).hexdigest()[:20]
            candidate["id"] = f"legacy_{fingerprint}"
        raw_messages.append(candidate)
    graph_already_present = any("parent_id" in message for message in raw_messages)
    normalized = [normalize_message(message) for message in raw_messages]
    if not normalized:
        return []

    if graph_already_present:
        valid_ids = {message["id"] for message in normalized}
        for message in normalized:
            parent_id = message.get("parent_id")
            if parent_id is not None and parent_id not in valid_ids:
                message["parent_id"] = None
        _ensure_single_active_sibling(normalized)
        return normalized

    previous: dict | None = None
    for message in normalized:
        if previous is None:
            message["parent_id"] = None
        elif message.get("role") == previous.get("role"):
            message["parent_id"] = previous.get("parent_id")
            previous["is_active"] = False
        else:
            message["parent_id"] = previous.get("id")
        message["is_active"] = True
        previous = message

    _ensure_single_active_sibling(normalized)
    return normalized


def _ensure_single_active_sibling(messages: list[dict]) -> None:
    sibling_groups: dict[str | None, list[dict]] = {}
    for message in messages:
        sibling_groups.setdefault(message.get("parent_id"), []).append(message)
    for siblings in sibling_groups.values():
        active = [message for message in siblings if message.get("is_active")]
        selected = active[-1] if active else siblings[-1]
        for message in siblings:
            message["is_active"] = message is selected


def _variant_payload(message: dict) -> dict:
    payload = {
        key: value for key, value in message.items() if key not in {"parent_id", "is_active"}
    }
    payload["variant_id"] = message.get("id")
    return payload


def materialize_conversation_history(messages: list[Any]) -> list[dict]:
    graph = ensure_conversation_graph(messages)
    if not graph:
        return []

    sibling_groups: dict[str | None, list[dict]] = {}
    for message in graph:
        sibling_groups.setdefault(message.get("parent_id"), []).append(message)

    history: list[dict] = []
    parent_id: str | None = None
    visited: set[str] = set()
    while parent_id in sibling_groups:
        siblings = sibling_groups[parent_id]
        current_index = next(
            (
                index
                for index in range(len(siblings) - 1, -1, -1)
                if siblings[index].get("is_active")
            ),
            len(siblings) - 1,
        )
        selected = siblings[current_index]
        message_id = str(selected.get("id") or "")
        if not message_id or message_id in visited:
            break
        visited.add(message_id)
        materialized = dict(selected)
        if len(siblings) > 1:
            materialized["variants"] = [_variant_payload(sibling) for sibling in siblings]
            materialized["current_variant_index"] = current_index
        history.append(materialized)
        parent_id = message_id
    return history


def _active_path_graph(messages: list[Any]) -> list[dict]:
    return [dict(message) for message in materialize_conversation_history(messages)]


def conversation_context_for_operation(
    messages: list[Any], operation: str, target_message_id: str | None
) -> tuple[list[dict], str | None]:
    """Return canonical model context and the parent anchor for a chat operation."""
    path = _active_path_graph(messages)
    if operation == "send":
        return [normalize_message(message) for message in path], path[-1]["id"] if path else None

    target_index = next(
        (index for index, message in enumerate(path) if message.get("id") == target_message_id),
        -1,
    )
    if target_index < 0:
        raise ValueError("target_message_not_found")

    target = path[target_index]
    if operation == "regenerate":
        if target.get("role") != "model" or target_index == 0:
            raise ValueError("invalid_regenerate_target")
        user_message = path[target_index - 1]
        if user_message.get("role") != "user":
            raise ValueError("invalid_regenerate_target")
        return [normalize_message(message) for message in path[: target_index - 1]], user_message[
            "id"
        ]

    if operation == "edit":
        if target.get("role") != "user":
            raise ValueError("invalid_edit_target")
        return [normalize_message(message) for message in path[:target_index]], target.get(
            "parent_id"
        )

    raise ValueError("invalid_chat_operation")


def _message_signature(msg: dict) -> str:
    try:
        role = str(msg.get("role") or "").lower()
        parts = msg.get("parts") or []
        pieces = []

        for part in parts:
            if isinstance(part, dict):
                if "text" in part and part["text"] is not None:
                    pieces.append(str(part["text"]))
                elif "url_path" in part:
                    pieces.append(str(part.get("url_path")))
                else:
                    pieces.append(json.dumps(part, sort_keys=True, ensure_ascii=False))
            else:
                pieces.append(str(part))

        body = "||".join(pieces)
        return f"{role}::{hashlib.sha256(body.encode('utf-8')).hexdigest()}"
    except Exception:
        return f"{(msg.get('role') or 'x')}::err"


def _collect_new_messages(
    existing_messages: list[dict], incoming_messages: list[dict]
) -> list[dict]:
    existing_ids = {message.get("id") for message in existing_messages}
    recent_signatures = {
        _message_signature(message)
        for message in existing_messages[-10:]
        if isinstance(message, dict)
    }
    fresh_messages: list[dict] = []

    for message in incoming_messages:
        message_id = message.get("id")
        if message_id in existing_ids:
            continue

        signature = _message_signature(message)
        if signature in recent_signatures:
            continue

        existing_ids.add(message_id)
        recent_signatures.add(signature)
        fresh_messages.append(message)

    return fresh_messages


def _generate_title_from_history(history: list) -> str:
    try:
        for msg in history:
            parts = msg.get("parts") or [{}]
            text = str(parts[0].get("text", "")).strip()
            if msg.get("role") == "user" and text:
                clean = re.sub(r"\s+", " ", text)
                return (clean[:45] + "...") if len(clean) > 48 else clean
    except Exception:
        pass

    return "Новый чат"


def _normalize_history_from_data(data: dict) -> list[dict]:
    history = data.get("history", []) if isinstance(data, dict) else []
    return [normalize_message(message) for message in history]


def load_chat_history(
    session_id: str,
    user_id: int | None = None,
    *,
    allow_file_fallback: bool = False,
    require_guest_token: bool = False,
) -> list:
    return materialize_conversation_history(
        load_chat_graph(
            session_id,
            user_id,
            allow_file_fallback=allow_file_fallback,
            require_guest_token=require_guest_token,
        )
    )


def load_chat_graph(
    session_id: str,
    user_id: int | None = None,
    *,
    allow_file_fallback: bool = False,
    require_guest_token: bool = False,
) -> list[dict]:
    safe_session_id = secure_filename(str(session_id))
    if not safe_session_id:
        return []

    if user_id and isinstance(user_id, int):
        chat = UserChatHistory.query.filter_by(user_id=user_id, session_id=session_id).first()
        if chat:
            return ensure_conversation_graph(chat.get_messages())

    if not allow_file_fallback:
        return []

    data = read_chat_file_secure(safe_session_id, require_auth=require_guest_token)
    return ensure_conversation_graph(data.get("history", []) if isinstance(data, dict) else [])


def _deactivate_siblings(graph: list[dict], parent_id: str | None) -> None:
    for message in graph:
        if message.get("parent_id") == parent_id:
            message["is_active"] = False


def _activate_ancestry(graph: list[dict], message_id: str | None) -> None:
    by_id = {message.get("id"): message for message in graph}
    current = by_id.get(message_id)
    visited: set[str] = set()
    while current and current.get("id") not in visited:
        current_id = str(current.get("id"))
        visited.add(current_id)
        parent_id = current.get("parent_id")
        _deactivate_siblings(graph, parent_id)
        current["is_active"] = True
        current = by_id.get(parent_id)


def _apply_chat_operation(
    messages: list[Any],
    *,
    operation: str,
    target_message_id: str | None,
    parent_message_id: str | None,
    user_message: dict | None,
    model_message: dict,
) -> list[dict]:
    graph = ensure_conversation_graph(messages)
    request_id = model_message.get("request_id")
    if request_id and any(message.get("request_id") == request_id for message in graph):
        return graph

    by_id = {message.get("id"): message for message in graph}
    model_node = normalize_message(model_message)
    user_node = normalize_message(user_message) if user_message else None
    incoming_ids = [model_node.get("id")]
    if user_node:
        incoming_ids.append(user_node.get("id"))
    if len(set(incoming_ids)) != len(incoming_ids) or any(
        message_id in by_id for message_id in incoming_ids
    ):
        raise ValueError("message_id_conflict")

    if operation == "send":
        parent_id = parent_message_id if parent_message_id in by_id else None
        if parent_id is None:
            active_path = materialize_conversation_history(graph)
            parent_id = active_path[-1]["id"] if active_path else None
        _activate_ancestry(graph, parent_id)
        if not user_node:
            raise ValueError("missing_user_message")
        user_node["parent_id"] = parent_id
        user_node["is_active"] = True
        _deactivate_siblings(graph, parent_id)
        graph.append(user_node)
        model_node["parent_id"] = user_node["id"]
        model_node["is_active"] = True
        graph.append(model_node)
        return graph

    target = by_id.get(target_message_id)
    if not target:
        raise ValueError("target_message_not_found")

    if operation == "regenerate":
        if target.get("role") != "model":
            raise ValueError("invalid_regenerate_target")
        parent_id = target.get("parent_id")
        if sum(1 for message in graph if message.get("parent_id") == parent_id) >= (
            CHAT_MAX_VARIANTS_PER_TURN
        ):
            raise ValueError("chat_variant_limit_reached")
        _activate_ancestry(graph, parent_id)
        _deactivate_siblings(graph, parent_id)
        model_node["parent_id"] = parent_id
        model_node["is_active"] = True
        graph.append(model_node)
        return graph

    if operation == "edit":
        if target.get("role") != "user" or not user_node:
            raise ValueError("invalid_edit_target")
        parent_id = target.get("parent_id")
        if sum(1 for message in graph if message.get("parent_id") == parent_id) >= (
            CHAT_MAX_VARIANTS_PER_TURN
        ):
            raise ValueError("chat_variant_limit_reached")
        _activate_ancestry(graph, parent_id)
        _deactivate_siblings(graph, parent_id)
        user_node["parent_id"] = parent_id
        user_node["is_active"] = True
        graph.append(user_node)
        model_node["parent_id"] = user_node["id"]
        model_node["is_active"] = True
        graph.append(model_node)
        return graph

    raise ValueError("invalid_chat_operation")


def persist_chat_operation(
    session_id: str,
    *,
    operation: str,
    target_message_id: str | None,
    parent_message_id: str | None,
    user_message: dict | None,
    model_message: dict,
    model_name: str,
    user_id: int | None = None,
    allow_guest_file_persistence: bool = False,
    mind_id: int | None = None,
) -> list[dict]:
    safe_session_id = secure_filename(str(session_id))
    if not safe_session_id:
        raise ValueError("invalid_session_id")

    lock = _acquire_session_lock(safe_session_id)
    with lock:
        result_graph: list[dict] = []
        if allow_guest_file_persistence:
            current_data = read_chat_file(safe_session_id)
            file_graph = _apply_chat_operation(
                current_data.get("history", []) if isinstance(current_data, dict) else [],
                operation=operation,
                target_message_id=target_message_id,
                parent_message_id=parent_message_id,
                user_message=user_message,
                model_message=model_message,
            )
            write_chat_file(
                safe_session_id,
                {
                    "session_id": session_id,
                    "last_updated": time.time(),
                    "model_used_in_last_message": model_name,
                    "history": file_graph,
                    "title": (current_data.get("title") if isinstance(current_data, dict) else None)
                    or _generate_title_from_history(materialize_conversation_history(file_graph)),
                },
            )
            result_graph = file_graph

        if user_id is not None and isinstance(user_id, int):
            # Compare-and-swap the JSON graph so two web workers cannot silently
            # overwrite one another's branches. The unique constraint handles
            # the equivalent race while creating a brand-new session.
            for attempt in range(3):
                try:
                    chat = UserChatHistory.query.filter_by(
                        user_id=user_id, session_id=session_id
                    ).first()
                    if not chat:
                        seed = [user_message, model_message] if user_message else [model_message]
                        db_graph = _apply_chat_operation(
                            [],
                            operation=operation,
                            target_message_id=target_message_id,
                            parent_message_id=parent_message_id,
                            user_message=user_message,
                            model_message=model_message,
                        )
                        chat = UserChatHistory(
                            user_id=user_id,
                            session_id=session_id,
                            title=_generate_title_from_history([item for item in seed if item]),
                            mind_id=mind_id,
                        )
                        chat.set_messages(db_graph)
                        db.session.add(chat)
                        db.session.commit()
                        result_graph = db_graph
                        break

                    previous_messages_data = chat.messages_data
                    db_graph = _apply_chat_operation(
                        chat.get_messages(),
                        operation=operation,
                        target_message_id=target_message_id,
                        parent_message_id=parent_message_id,
                        user_message=user_message,
                        model_message=model_message,
                    )
                    next_title = chat.title
                    if not next_title or next_title == "Новый чат":
                        next_title = _generate_title_from_history(
                            materialize_conversation_history(db_graph)
                        )
                    values: dict[str, Any] = {
                        "messages_data": json.dumps(db_graph, ensure_ascii=False),
                        "title": next_title,
                        "updated_at": datetime.utcnow(),
                    }
                    if mind_id is not None:
                        values["mind_id"] = mind_id
                    updated = (
                        UserChatHistory.query.filter_by(id=chat.id)
                        .filter(UserChatHistory.messages_data == previous_messages_data)
                        .update(values, synchronize_session=False)
                    )
                    if updated != 1:
                        db.session.rollback()
                        continue
                    db.session.commit()
                    result_graph = db_graph
                    break
                except IntegrityError:
                    db.session.rollback()
                    if attempt == 2:
                        raise
                except Exception:
                    db.session.rollback()
                    raise
            else:
                raise RuntimeError("chat_concurrent_update")

        return materialize_conversation_history(result_graph)


def _select_variant_in_graph(messages: list[Any], message_id: str) -> list[dict]:
    graph = ensure_conversation_graph(messages)
    target = next((message for message in graph if message.get("id") == message_id), None)
    if not target:
        raise ValueError("target_message_not_found")
    _activate_ancestry(graph, message_id)
    return graph


def select_conversation_variant(
    session_id: str,
    message_id: str,
    *,
    user_id: int | None = None,
    allow_guest_file_persistence: bool = False,
) -> list[dict]:
    safe_session_id = secure_filename(str(session_id))
    if not safe_session_id:
        raise ValueError("invalid_session_id")
    lock = _acquire_session_lock(safe_session_id)
    with lock:
        if user_id is not None:
            for _attempt in range(3):
                chat = UserChatHistory.query.filter_by(
                    user_id=user_id, session_id=session_id
                ).first()
                if not chat:
                    raise ValueError("session_not_found")
                previous_messages_data = chat.messages_data
                graph = _select_variant_in_graph(chat.get_messages(), message_id)
                updated = (
                    UserChatHistory.query.filter_by(id=chat.id)
                    .filter(UserChatHistory.messages_data == previous_messages_data)
                    .update(
                        {
                            "messages_data": json.dumps(graph, ensure_ascii=False),
                            "updated_at": datetime.utcnow(),
                        },
                        synchronize_session=False,
                    )
                )
                if updated != 1:
                    db.session.rollback()
                    continue
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    raise
                return materialize_conversation_history(graph)
            raise RuntimeError("chat_concurrent_update")
        if allow_guest_file_persistence:
            current_data = read_chat_file_secure(safe_session_id, require_auth=True)
            graph = _select_variant_in_graph(
                current_data.get("history", []) if isinstance(current_data, dict) else [],
                message_id,
            )
            next_data = dict(current_data)
            next_data["history"] = graph
            next_data["last_updated"] = time.time()
            write_chat_file(safe_session_id, next_data)
            return materialize_conversation_history(graph)
    raise ValueError("session_not_found")


def append_messages_to_history(
    session_id: str,
    new_messages: list,
    model_name: str,
    user_id: int | None = None,
    *,
    allow_guest_file_persistence: bool | None = None,
    mind_id: int | None = None,
) -> None:
    safe_session_id = secure_filename(str(session_id))
    if not safe_session_id:
        return

    lock = _acquire_session_lock(safe_session_id)
    with lock:
        try:
            incoming = [normalize_message(message) for message in new_messages]
            is_authenticated_user = user_id is not None and isinstance(user_id, int)
            if allow_guest_file_persistence is None:
                allow_file_persistence = bool(not is_authenticated_user and ALLOW_GUEST_CHATS_SAVE)
            else:
                allow_file_persistence = bool(allow_guest_file_persistence)
            current_data = read_chat_file(safe_session_id) if allow_file_persistence else {}
            file_history = current_data.get("history", []) if isinstance(current_data, dict) else []
            to_append_file = _collect_new_messages(file_history, incoming)

            if to_append_file and allow_file_persistence:
                file_history.extend(to_append_file)
                chat_data = {
                    "session_id": session_id,
                    "last_updated": time.time(),
                    "model_used_in_last_message": model_name,
                    "history": file_history,
                    "title": current_data.get("title")
                    or _generate_title_from_history(file_history),
                }
                write_chat_file(safe_session_id, chat_data)

            if user_id and isinstance(user_id, int):
                try:
                    chat = UserChatHistory.query.filter_by(
                        user_id=user_id, session_id=session_id
                    ).first()
                    if not chat:
                        chat = UserChatHistory(
                            user_id=user_id,
                            session_id=session_id,
                            title=_generate_title_from_history(incoming),
                        )
                        db.session.add(chat)

                    if mind_id is not None:
                        chat.mind_id = mind_id

                    db_messages = chat.get_messages()
                    to_append_db = _collect_new_messages(db_messages, incoming)
                    if to_append_db:
                        db_messages.extend(to_append_db)
                        chat.set_messages(db_messages)

                    if not chat.title or chat.title == "Новый чат":
                        chat.title = _generate_title_from_history(db_messages or incoming)

                    chat.updated_at = datetime.utcnow()
                    db.session.commit()
                except Exception as exc:
                    logger.exception("Could not save to DB: %s", exc)
                    db.session.rollback()
        except Exception as exc:
            logger.exception("Failed to append chat history for %s: %s", session_id, exc)
