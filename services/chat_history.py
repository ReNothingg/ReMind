import os
import json
import time
import base64
import hmac
import hashlib
import uuid
import re
import threading
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse
from flask import request, session
from werkzeug.utils import secure_filename

from config import (
    CHATS_FOLDER,
    SECRET_KEY,
    ALLOW_GUEST_CHATS_SAVE,
    BACKEND_URL,
    ALLOWED_HOSTS,
)
from utils.auth import UserChatHistory, ChatShare, db
from utils.responses import logger

SESSION_LOCKS = {}


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

def _acquire_session_lock(safe_session_id: str):
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
        with open(chat_file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _generate_guest_session_token(session_id: str, timestamp: int) -> str:
    message = f"{session_id}:{timestamp}".encode("utf-8")
    signature = hmac.new(
        SECRET_KEY.encode("utf-8"), message, hashlib.sha256
    ).hexdigest()
    token_data = f"{session_id}:{timestamp}:{signature}"
    return base64.b64encode(token_data.encode("utf-8")).decode("utf-8")

def _verify_guest_session_token(
    token: str, session_id: str, max_age_seconds: int = 604800
) -> bool:
    try:
        token_data = base64.b64decode(token.encode("utf-8")).decode("utf-8")
        parts = token_data.split(":")
        if len(parts) != 3:
            return False

        token_session_id, timestamp_str, signature = parts

        if token_session_id != session_id:
            logger.warning(
                f"Token session ID mismatch: {token_session_id} != {session_id}"
            )
            return False

        timestamp = int(timestamp_str)
        current_time = int(time.time())
        if current_time - timestamp > max_age_seconds:
            logger.warning(f"Token expired: {current_time - timestamp} seconds old")
            return False

        message = f"{session_id}:{timestamp}".encode("utf-8")
        expected_signature = hmac.new(
            SECRET_KEY.encode("utf-8"), message, hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_signature):
            logger.warning(f"Token signature mismatch for session: {session_id}")
            return False

        return True
    except Exception as e:
        logger.warning(f"Token verification failed: {e}")
        return False

def _get_chat_access_token_from_request() -> Optional[str]:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return request.args.get("chat_token")

def read_chat_file_secure(safe_session_id: str, require_auth: bool = False) -> dict:
    user_id = session.get("user_id")
    is_authenticated = user_id is not None

    if is_authenticated:
        return read_chat_file(safe_session_id)

    if require_auth:
        if not ALLOW_GUEST_CHATS_SAVE:
            logger.warning(f"Guest chat access disabled: {safe_session_id}")
            return {}

        token = _get_chat_access_token_from_request()
        if not token or not _verify_guest_session_token(token, safe_session_id):
            logger.warning(f"Unauthorized access attempt to guest chat: {safe_session_id}")
            return {}

    return read_chat_file(safe_session_id)

def resolve_session_identifier(session_identifier: str):
    safe_identifier = secure_filename(str(session_identifier))
    share_entry = (
        ChatShare.query.filter(
            (ChatShare.session_id == safe_identifier)
            | (ChatShare.public_id == safe_identifier)
        ).first()
        if safe_identifier
        else None
    )
    resolved_session_id = share_entry.session_id if share_entry else safe_identifier
    return resolved_session_id, share_entry

def build_share_url(public_id: str) -> str:
    base = _get_public_base_url()
    return f"{base}/c/{public_id}" if base else f"/c/{public_id}"

def write_chat_file(safe_session_id: str, data: dict):
    CHATS_FOLDER.mkdir(parents=True, exist_ok=True)
    chat_file_path = CHATS_FOLDER / f"{safe_session_id}.json"
    tmp_path = CHATS_FOLDER / f"{safe_session_id}.json.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(str(tmp_path), str(chat_file_path))
    finally:
        if tmp_path.exists():
            try:
                os.remove(tmp_path)
            except Exception:
                pass

def normalize_message(msg: dict) -> dict:
    try:
        if not isinstance(msg, dict):
            return {
                "id": f"m_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}",
                "role": "user",
                "parts": [{"text": str(msg)}],
                "timestamp": int(time.time()),
            }
        role = msg.get("role", "user")
        parts = msg.get("parts") or (
            [{"text": msg.get("text")}] if msg.get("text") else [{"text": ""}]
        )
        mid = msg.get("id") or f"m_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
        ts = msg.get("timestamp") or int(time.time())
        return {"id": mid, "role": role, "parts": parts, "timestamp": ts}
    except Exception:
        return {
            "id": f"m_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}",
            "role": "user",
            "parts": [{"text": ""}],
            "timestamp": int(time.time()),
        }

def _message_signature(msg: dict) -> str:
    try:
        role = (msg.get("role") or "").lower()
        parts = msg.get("parts") or []
        pieces = []
        for p in parts:
            if isinstance(p, dict):
                if "text" in p and p["text"] is not None:
                    pieces.append(str(p["text"]))
                elif "url_path" in p:
                    pieces.append(str(p.get("url_path")))
                else:
                    pieces.append(json.dumps(p, sort_keys=True))
            else:
                pieces.append(str(p))
        body = "||".join(pieces)
        sig = f"{role}::{hash(body)}"
        return sig
    except Exception:
        return f"{(msg.get('role') or 'x')}::err"

def _generate_title_from_history(history: list) -> str:
    try:
        for msg in history:
            if msg.get("role") == "user" and (
                text := (msg.get("parts") or [{}])[0].get("text", "").strip()
            ):
                clean = re.sub(r"\s+", " ", text)
                return (clean[:45] + "…") if len(clean) > 48 else clean
    except Exception:
        pass
    return "Новый чат"

def load_chat_history(session_id: str, user_id: int = None) -> list:
    safe_session_id = secure_filename(str(session_id))
    if not safe_session_id:
        return []

    if user_id and isinstance(user_id, int):
        try:
            chat = UserChatHistory.query.filter_by(
                user_id=user_id, session_id=session_id
            ).first()

            if chat:
                history = chat.get_messages()
                return [normalize_message(msg) for msg in history]
            else:
                return []
        except Exception as e:
            logger.debug(f"Could not load from DB: {e}")
            return []

    data = read_chat_file(safe_session_id)
    history = data.get("history", []) if isinstance(data, dict) else []
    return [normalize_message(msg) for msg in history]

def append_messages_to_history(
    session_id: str, new_messages: list, model_name: str, user_id: int = None
):
    safe_session_id = secure_filename(str(session_id))
    if not safe_session_id:
        return

    lock = _acquire_session_lock(safe_session_id)
    with lock:
        try:
            current_data = {}
            if (user_id and isinstance(user_id, int)) or ALLOW_GUEST_CHATS_SAVE:
                current_data = read_chat_file(safe_session_id)
            history = (
                current_data.get("history", [])
                if isinstance(current_data, dict)
                else []
            )

            incoming = [normalize_message(m) for m in new_messages]
            existing_ids = {m.get("id") for m in history}
            to_append_file = []

            for msg in incoming:
                if msg.get("id") not in existing_ids:
                    msg_sig = _message_signature(msg)
                    is_duplicate = any(
                        _message_signature(ex) == msg_sig for ex in history[-10:]
                    )
                    if not is_duplicate:
                        to_append_file.append(msg)

            if to_append_file and (
                (user_id and isinstance(user_id, int)) or ALLOW_GUEST_CHATS_SAVE
            ):
                history.extend(to_append_file)
                chat_data = {
                    "session_id": session_id,
                    "last_updated": time.time(),
                    "model_used_in_last_message": model_name,
                    "history": history,
                    "title": current_data.get("title")
                    or _generate_title_from_history(history),
                }
                write_chat_file(safe_session_id, chat_data)

            if user_id and isinstance(user_id, int):
                try:
                    chat = UserChatHistory.query.filter_by(
                        user_id=user_id, session_id=session_id
                    ).first()

                    if not chat:
                        title = _generate_title_from_history(incoming)
                        chat = UserChatHistory(
                            user_id=user_id, session_id=session_id, title=title
                        )
                        db.session.add(chat)
                        db.session.commit()
                        logger.info(
                            f"✅ Created new chat session in DB: user={user_id}, session={session_id}"
                        )

                    db_messages = chat.get_messages()
                    db_existing_ids = {m.get("id") for m in db_messages}
                    to_append_db = []

                    for msg in incoming:
                        if msg.get("id") not in db_existing_ids:
                            msg_sig = _message_signature(msg)
                            is_duplicate = any(
                                _message_signature(ex) == msg_sig
                                for ex in db_messages[-10:]
                            )
                            if not is_duplicate:
                                to_append_db.append(msg)

                    if to_append_db:
                        db_messages.extend(to_append_db)
                        chat.set_messages(db_messages)

                        if not chat.title or chat.title == "Новый чат":
                            chat.title = _generate_title_from_history(db_messages)

                        chat.updated_at = datetime.utcnow()
                        db.session.commit()
                        logger.info(
                            f"✅ Saved messages to DB for user={user_id}, session={session_id}"
                        )

                except Exception as e:
                    logger.exception(f"Could not save to DB: {e}")
                    db.session.rollback()

        except Exception as e:
            logger.exception(f"Failed to append chat history for {session_id}: {e}")
