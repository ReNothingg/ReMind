import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

from flask import has_request_context, request, session
from werkzeug.utils import secure_filename

from config import ALLOW_GUEST_CHATS_SAVE, ALLOWED_HOSTS, BACKEND_URL, CHATS_FOLDER, SECRET_KEY
from utils.auth import ChatShare, UserChatHistory, db
from utils.responses import logger

SESSION_LOCKS: dict[str, threading.Lock] = {}


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
            logger.warning("Token session ID mismatch: %s != %s", token_session_id, session_id)
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
            logger.warning("Token signature mismatch for session: %s", session_id)
            return False

        return True
    except Exception as exc:
        logger.warning("Token verification failed: %s", exc)
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
            logger.warning("Guest chat access disabled: %s", safe_session_id)
            return {}

        if not has_valid_guest_session_token(safe_session_id):
            logger.warning("Unauthorized access attempt to guest chat: %s", safe_session_id)
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
        return {
            "id": msg.get("id") or _new_message_id(),
            "role": role,
            "parts": parts,
            "timestamp": msg.get("timestamp") or int(time.time()),
        }
    except Exception:
        return {
            "id": _new_message_id(),
            "role": "user",
            "parts": [{"text": ""}],
            "timestamp": int(time.time()),
        }


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
    safe_session_id = secure_filename(str(session_id))
    if not safe_session_id:
        return []

    if user_id and isinstance(user_id, int):
        try:
            chat = UserChatHistory.query.filter_by(user_id=user_id, session_id=session_id).first()
            if chat:
                return [normalize_message(message) for message in chat.get_messages()]
        except Exception as exc:
            logger.debug("Could not load from DB: %s", exc)

    if not allow_file_fallback:
        return []

    data = read_chat_file_secure(safe_session_id, require_auth=require_guest_token)
    return _normalize_history_from_data(data)


def append_messages_to_history(
    session_id: str,
    new_messages: list,
    model_name: str,
    user_id: int | None = None,
    *,
    allow_guest_file_persistence: bool | None = None,
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
