from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import io
import json
import logging
import os
import re
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import requests
from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import FileStorage

from backend.ai_engine import get_model_function
from backend.ai_engine.registry import DEFAULT_MODEL_ID
from backend.auth.accounts import is_account_disabled
from backend.auth.telegram import consume_telegram_link_token
from backend.config import (
    BACKEND_URL,
    SECRET_KEY,
    TELEGRAM_BOT_API_BASE,
    TELEGRAM_BOT_POLL_TIMEOUT_SECONDS,
    TELEGRAM_BOT_REQUEST_TIMEOUT_SECONDS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_BOT_USERNAME,
    UPLOAD_FOLDER,
)
from backend.db.models import (
    AuthIdentity,
    TelegramBusinessLink,
    TelegramInlineResult,
    User,
    UserChatHistory,
    db,
)
from backend.services.chat.attachments import _build_model_message_parts
from backend.services.chat.cancellation import GenerationStopped
from backend.services.chat.conversation import conversation_context_for_operation, normalize_message
from backend.services.chat.history import load_chat_graph, load_chat_history, persist_chat_operation
from backend.services.files import (
    CHAT_UPLOAD_MAX_TOTAL_BYTES,
    handle_file_upload,
    restore_stored_file_for_model,
    validate_chat_uploads,
)
from backend.services.minds import require_portable_mind, resolve_mind_context_for_chat
from backend.services.model_access import can_user_access_model
from backend.services.telegram import agent as telegram_agent
from backend.services.telegram.dispatcher import TelegramUpdates
from backend.services.telegram.i18n import (
    SUPPORTED_LANGUAGES,
    language_from_telegram,
    telegram_text,
)
from backend.services.voice import TTS_MAX_CHARS, synthesize_text_segments

logger = logging.getLogger("remind")
_generation_control = ContextVar("telegram_generation_control", default=None)
_delivery_topic = ContextVar("telegram_delivery_topic", default=None)
_THINK_RE = re.compile(r"<think\b[^>]*>[\s\S]*?</think>", re.IGNORECASE)
_UNSUPPORTED_TOOL_BLOCK_RE = re.compile(
    r"```(?:canmore|chartjs|d3js|mermaid|nomnoml)\b[\s\S]*?```"
    r"|<(?:beatbox|quiz|spinwheel)\b[^>]*>[\s\S]*?</(?:beatbox|quiz|spinwheel)>",
    re.IGNORECASE,
)
_TG_THINKING_TAG_RE = re.compile(r"</?tg-thinking\b[^>]*>", re.IGNORECASE)
_RICH_MARKDOWN_MEDIA_RE = re.compile(r"!\[([^\]\n]{0,500})\]\(([^)\n]{1,2000})\)", re.IGNORECASE)
_MENTION_RE_TEMPLATE = r"(?<![\w@])@{username}(?!\w)"
_MAX_INPUT_CHARS = 8_000
_MAX_INLINE_INPUT_CHARS = 2_000
_MAX_INLINE_ANSWER_CHARS = 3_500
_MAX_RICH_MESSAGE_CHARS = 32_000
_INLINE_RETENTION_DAYS = 2
_INLINE_RESULT_TITLE_CHARS = 80
_INLINE_RESULT_DESCRIPTION_CHARS = 140
_INLINE_RESULT_TEXT_CHARS = 4_000
_TELEGRAM_FILE_PATH_RE = re.compile(r"^[A-Za-z0-9_./-]{1,512}$")
_CALLBACK_DATA_RE = re.compile(r"^(repeat|speak):(tg_[A-Za-z0-9_-]{1,52})$")
_CALLBACK_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")


def _int_env(name: str, default: int, *, min_value: int = 1, max_value: int = 1000) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value


def _float_env(
    name: str, default: float, *, min_value: float = 0.1, max_value: float = 5.0
) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value


def _normalize_thinking_level(value: str, fallback: str = "minimal") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"minimal", "low", "medium", "high"}:
        return normalized
    return fallback


_DRAFT_INTERVAL_SECONDS = _float_env(
    "TELEGRAM_DRAFT_INTERVAL_SECONDS", 0.55, min_value=0.2, max_value=5.0
)
_TELEGRAM_MAX_CONTEXT_MESSAGES = _int_env(
    "TELEGRAM_MAX_CONTEXT_MESSAGES", 4, min_value=1, max_value=20
)
_TELEGRAM_MAX_CONTEXT_MESSAGES_INLINE = _int_env(
    "TELEGRAM_MAX_CONTEXT_MESSAGES_INLINE",
    _TELEGRAM_MAX_CONTEXT_MESSAGES,
    min_value=1,
    max_value=20,
)
_TELEGRAM_THINKING_LEVEL_MESSAGE = _normalize_thinking_level(
    os.environ.get("TELEGRAM_THINKING_LEVEL_MESSAGE", ""),
    fallback="medium",
)
_TELEGRAM_THINKING_LEVEL_INLINE = _normalize_thinking_level(
    os.environ.get("TELEGRAM_THINKING_LEVEL_INLINE", ""),
    fallback="minimal",
)
_TELEGRAM_THINKING_LEVEL = _normalize_thinking_level(
    os.environ.get("TELEGRAM_THINKING_LEVEL", ""),
    fallback="low",
)
if not _TELEGRAM_THINKING_LEVEL_MESSAGE:
    _TELEGRAM_THINKING_LEVEL_MESSAGE = _TELEGRAM_THINKING_LEVEL
if not _TELEGRAM_THINKING_LEVEL_INLINE:
    _TELEGRAM_THINKING_LEVEL_INLINE = _TELEGRAM_THINKING_LEVEL


def _telegram_context_limit(source: str) -> int:
    return (
        _TELEGRAM_MAX_CONTEXT_MESSAGES_INLINE
        if source == "telegram_inline"
        else _TELEGRAM_MAX_CONTEXT_MESSAGES
    )


def _telegram_thinking_level(source: str) -> str:
    if source == "telegram_inline":
        return _TELEGRAM_THINKING_LEVEL_INLINE
    if source.startswith("telegram_"):
        return _TELEGRAM_THINKING_LEVEL_MESSAGE
    return _TELEGRAM_THINKING_LEVEL


def _telegram_use_canonical_history(source: str) -> bool:
    return source == "telegram_private" or not source.startswith("telegram_")


class TelegramAPIError(RuntimeError):
    def __init__(
        self,
        method: str,
        description: str,
        error_code: int | None = None,
        payload: dict[str, Any] | None = None,
    ):
        super().__init__(f"Telegram API {method} failed ({error_code or 'unknown'})")
        self.method = method
        self.description = description[:500]
        self.error_code = error_code
        self.payload = payload or {}


def _safe_preview(payload: dict[str, Any] | None, *, max_len: int = 600) -> str:
    if not payload or payload.get("business_connection_id"):
        return ""
    message_text = payload.get("results", [])
    if isinstance(message_text, list):
        if message_text:
            first = message_text[0]
            if isinstance(first, dict):
                raw_input_message_content = first.get("input_message_content")
                input_message_content: dict[str, Any] = (
                    raw_input_message_content if isinstance(raw_input_message_content, dict) else {}
                )
                if "message_text" in input_message_content:
                    message_text = str(input_message_content.get("message_text") or "")
                elif "rich_message" in input_message_content:
                    message_text = str(
                        input_message_content.get("rich_message", {}).get("markdown") or ""
                    )
                else:
                    message_text = ""
    if not isinstance(message_text, str):
        message_text = str(message_text)
    trimmed = " ".join(str(message_text or "").split())
    if len(trimmed) > max_len:
        trimmed = trimmed[: max_len - 3] + "..."
    return trimmed


class TelegramBotAPI:
    def __init__(self, token: str = TELEGRAM_BOT_TOKEN):
        normalized = str(token or "").strip()
        if not normalized or "/" in normalized:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
        self._base_url = f"{TELEGRAM_BOT_API_BASE}/bot{normalized}"
        self._file_base_url = f"{TELEGRAM_BOT_API_BASE}/file/bot{normalized}"
        self._session = requests.Session()

    def call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: int | tuple[int, int] | None = None,
    ) -> Any:
        topic = _delivery_topic.get()
        if (
            topic
            and payload
            and method
            in {
                "sendMessage",
                "sendRichMessage",
                "sendMessageDraft",
                "sendRichMessageDraft",
                "sendChatAction",
            }
            and payload.get("chat_id") == topic[0]
        ):
            payload = {**payload, "message_thread_id": topic[1]}
        try:
            response = self._session.post(
                f"{self._base_url}/{method}",
                json=payload or {},
                timeout=timeout or (10, TELEGRAM_BOT_REQUEST_TIMEOUT_SECONDS),
            )
        except requests.RequestException as exc:
            raise TelegramAPIError(method, type(exc).__name__) from None
        try:
            data = response.json()
        except ValueError as exc:
            raise TelegramAPIError(method, "invalid_json", response.status_code) from exc
        if response.status_code >= 400 or not data.get("ok"):
            description = str(data.get("description") or "request_failed").strip()
            raise TelegramAPIError(
                method,
                description,
                int(data.get("error_code") or response.status_code or 0),
                payload=payload,
            )
        return data.get("result")

    def get_updates(self, offset: int | None, *, active=False) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": 1 if active else TELEGRAM_BOT_POLL_TIMEOUT_SECONDS,
            "limit": 100,
            "allowed_updates": [
                "message",
                "callback_query",
                "guest_message",
                "stopped_message_generation",
                "business_connection",
                "business_message",
                "edited_business_message",
                "deleted_business_messages",
                "inline_query",
                "chosen_inline_result",
            ],
        }
        if offset is not None:
            payload["offset"] = offset
        result = self.call(
            "getUpdates",
            payload,
            timeout=(10, TELEGRAM_BOT_POLL_TIMEOUT_SECONDS + 15),
        )
        return result if isinstance(result, list) else []

    def download_file(self, file_id: str, *, max_bytes: int) -> bytes:
        file_info = self.call("getFile", {"file_id": file_id})
        file_path = str(file_info.get("file_path") or "") if isinstance(file_info, dict) else ""
        if (
            not _TELEGRAM_FILE_PATH_RE.fullmatch(file_path)
            or file_path.startswith("/")
            or ".." in file_path.split("/")
        ):
            raise TelegramAPIError("getFile", "invalid_file_path")
        try:
            response = self._session.get(
                f"{self._file_base_url}/{quote(file_path, safe='/')}",
                timeout=(10, TELEGRAM_BOT_REQUEST_TIMEOUT_SECONDS),
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as exc:
            raise TelegramAPIError("downloadFile", type(exc).__name__) from None
        try:
            if response.status_code != 200:
                raise TelegramAPIError("downloadFile", "request_failed", response.status_code)
            declared_size = response.headers.get("Content-Length")
            if declared_size is not None:
                try:
                    parsed_size = int(declared_size)
                    if parsed_size < 0:
                        raise TelegramAPIError("downloadFile", "invalid_content_length")
                    if parsed_size > max_bytes:
                        raise TelegramAPIError("downloadFile", "file_too_large")
                except ValueError:
                    raise TelegramAPIError("downloadFile", "invalid_content_length") from None
            body = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise TelegramAPIError("downloadFile", "file_too_large")
            if not body:
                raise TelegramAPIError("downloadFile", "empty_file")
            return bytes(body)
        finally:
            response.close()

    def answer_callback(self, query_id: str, text: str = "", *, show_alert: bool = False) -> Any:
        payload: dict[str, Any] = {
            "callback_query_id": query_id,
            "show_alert": show_alert,
        }
        if text:
            payload["text"] = text[:200]
        return self.call("answerCallbackQuery", payload)

    def send_voice(
        self,
        chat_id: int,
        audio: bytes,
        *,
        reply_to_message_id: int | None = None,
    ) -> Any:
        data: dict[str, str] = {"chat_id": str(chat_id)}
        topic = _delivery_topic.get()
        if topic and topic[0] == chat_id:
            data["message_thread_id"] = str(topic[1])
        if reply_to_message_id:
            data["reply_parameters"] = (
                '{"message_id":%d,"allow_sending_without_reply":true}' % reply_to_message_id
            )
        try:
            response = self._session.post(
                f"{self._base_url}/sendVoice",
                data=data,
                files={"voice": ("remind-answer.mp3", audio, "audio/mpeg")},
                timeout=(10, TELEGRAM_BOT_REQUEST_TIMEOUT_SECONDS),
            )
        except requests.RequestException as exc:
            raise TelegramAPIError("sendVoice", type(exc).__name__) from None
        try:
            payload = response.json()
        except ValueError as exc:
            raise TelegramAPIError("sendVoice", "invalid_json", response.status_code) from exc
        if response.status_code >= 400 or not payload.get("ok"):
            raise TelegramAPIError(
                "sendVoice",
                str(payload.get("description") or "request_failed"),
                int(payload.get("error_code") or response.status_code or 0),
            )
        return payload.get("result")

    def send_document(self, chat_id, path, name, mime, reply_to):
        fields = {
            "chat_id": chat_id,
            "reply_parameters": json.dumps(
                {"message_id": reply_to, "allow_sending_without_reply": True}
            ),
        }
        topic = _delivery_topic.get()
        if topic and topic[0] == chat_id:
            fields["message_thread_id"] = topic[1]
        try:
            with (
                path.open("rb") as file,
                self._session.post(
                    f"{self._base_url}/sendDocument",
                    data=fields,
                    files={"document": (name, file, mime)},
                    timeout=(8, 40),
                    allow_redirects=False,
                ) as response,
            ):
                payload = response.json()
                if response.status_code != 200 or payload.get("ok") is not True:
                    raise TelegramAPIError(
                        "sendDocument", "document_delivery_failed", response.status_code
                    )
        except (OSError, requests.RequestException, ValueError):
            raise TelegramAPIError("sendDocument", "document_delivery_failed") from None

    def send_text(
        self,
        chat_id: int,
        text: str,
        *,
        reply_to_message_id: int | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> Any:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text[:4096] or " "}
        if reply_to_message_id:
            payload["reply_parameters"] = {
                "message_id": reply_to_message_id,
                "allow_sending_without_reply": True,
            }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self.call("sendMessage", payload)

    def send_rich(
        self,
        chat_id: int,
        markdown: str,
        *,
        reply_to_message_id: int | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> Any:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "rich_message": {"markdown": markdown},
        }
        if reply_to_message_id:
            payload["reply_parameters"] = {
                "message_id": reply_to_message_id,
                "allow_sending_without_reply": True,
            }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self.call("sendRichMessage", payload)

    def send_rich_draft(
        self,
        chat_id: int,
        draft_id: int,
        markdown: str,
    ) -> bool:
        try:
            self.call(
                "sendRichMessageDraft",
                {
                    "chat_id": chat_id,
                    "draft_id": draft_id,
                    "can_stop": True,
                    "keep_on_stop": False,
                    "rich_message": {"markdown": markdown},
                },
            )
            return True
        except TelegramAPIError:
            plain = _THINK_RE.sub("", markdown).strip()
            try:
                self.call(
                    "sendMessageDraft",
                    {
                        "chat_id": chat_id,
                        "draft_id": draft_id,
                        "can_stop": True,
                        "keep_on_stop": False,
                        "text": plain[:4096],
                    },
                )
                return True
            except TelegramAPIError:
                logger.debug("Telegram draft update was rejected", exc_info=True)
                return False


@dataclass(frozen=True)
class LinkedTelegramUser:
    user: User
    language: str
    telegram_profile: dict[str, Any]


class _RequestWindow:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and now - events[0] > self.window_seconds:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True


_message_window = _RequestWindow(12, 60)
_inline_window = _RequestWindow(8, 60)
_voice_window = _RequestWindow(6, 60)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _profile_language(profile: dict[str, Any]) -> str:
    return language_from_telegram(profile.get("language_code"))


def _linked_user(profile: dict[str, Any]) -> LinkedTelegramUser | None:
    telegram_user_id = str(profile.get("id") or "").strip()
    if not telegram_user_id or profile.get("is_bot"):
        return None
    identity = AuthIdentity.query.filter_by(
        provider="telegram", provider_user_id=telegram_user_id
    ).first()
    user = db.session.get(User, identity.user_id) if identity else None
    if not user:
        user = User.query.filter_by(oauth_provider="telegram", oauth_id=telegram_user_id).first()
    if not user:
        return None
    return LinkedTelegramUser(
        user=user,
        language=_profile_language(profile),
        telegram_profile=profile,
    )


def _context_hash(user_id: int, source: str, external_context: str) -> str:
    message = f"telegram-chat:v1:{user_id}:{source}:{external_context}".encode("utf-8")
    return hmac.new((SECRET_KEY or "").encode("utf-8"), message, hashlib.sha256).hexdigest()


def _chat_for_context(
    linked: LinkedTelegramUser,
    source: str,
    external_context: str,
    context: dict[str, Any],
    *,
    create: bool,
) -> UserChatHistory | None:
    ref_hash = _context_hash(linked.user.id, source, external_context)
    chat = UserChatHistory.query.filter_by(
        user_id=linked.user.id, external_ref_hash=ref_hash
    ).first()
    if chat or not create:
        return chat
    chat = UserChatHistory(
        user_id=linked.user.id,
        session_id=f"telegram_{uuid.uuid4().hex}",
        source=source,
        external_ref_hash=ref_hash,
    )
    chat.set_source_context(context)
    db.session.add(chat)
    try:
        db.session.commit()
        return chat
    except IntegrityError:
        db.session.rollback()
        return UserChatHistory.query.filter_by(
            user_id=linked.user.id, external_ref_hash=ref_hash
        ).first()


def _start_new_context(linked: LinkedTelegramUser, source: str, external_context: str) -> None:
    ref_hash = _context_hash(linked.user.id, source, external_context)
    chat = UserChatHistory.query.filter_by(
        user_id=linked.user.id, external_ref_hash=ref_hash
    ).first()
    if not chat:
        return
    chat.external_ref_hash = None
    db.session.commit()


def _telegram_context(
    linked: LinkedTelegramUser,
    source: str,
    chat: dict[str, Any] | None,
    *,
    brief: bool,
) -> dict[str, Any]:
    profile = linked.telegram_profile
    return {
        "channel": source,
        "first_name": profile.get("first_name"),
        "last_name": profile.get("last_name"),
        "username": profile.get("username"),
        "language_code": profile.get("language_code"),
        "chat_type": (chat or {}).get("type"),
        "chat_title": (chat or {}).get("title"),
        "response_mode": "brief" if brief else "full",
    }


def _existing_delivery(session_id: str, user_id: int, request_id: str) -> str | None:
    for message in reversed(load_chat_graph(session_id, user_id)):
        if not isinstance(message, dict) or message.get("role") != "model":
            continue
        if message.get("request_id") != request_id:
            continue
        return _visible_answer(
            "\n".join(
                str(part.get("text") or "")
                for part in message.get("parts", [])
                if isinstance(part, dict)
            )
        )
    return None


def _message_for_request(
    graph: list[dict[str, Any]], request_id: str, role: str
) -> dict[str, Any] | None:
    for message in reversed(graph):
        if (
            isinstance(message, dict)
            and message.get("request_id") == request_id
            and message.get("role") == role
        ):
            return message
    return None


def _parent_user_message(
    graph: list[dict[str, Any]], model_message: dict[str, Any] | None
) -> dict[str, Any] | None:
    if not isinstance(model_message, dict):
        return None
    parent_id = str(model_message.get("parent_id") or "")
    if not parent_id:
        return None
    for message in graph:
        if (
            isinstance(message, dict)
            and message.get("id") == parent_id
            and message.get("role") == "user"
        ):
            return message
    return None


def _message_text(message: dict[str, Any] | None) -> str:
    if not isinstance(message, dict):
        return ""
    return _visible_answer(
        "\n".join(
            str(part.get("text") or "")
            for part in message.get("parts", [])
            if isinstance(part, dict) and part.get("text")
        )
    )


def _restored_message_files(message: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(message, dict):
        return []
    restored: list[dict[str, Any]] = []
    for part in message.get("parts", []):
        if not isinstance(part, dict) or not isinstance(part.get("image"), dict):
            continue
        file_info = restore_stored_file_for_model(
            part["image"], max_bytes=CHAT_UPLOAD_MAX_TOTAL_BYTES
        )
        if file_info:
            restored.append(file_info)
    return restored


def _visible_answer(value: str) -> str:
    without_thoughts = _THINK_RE.sub("", str(value or ""))
    return _UNSUPPORTED_TOOL_BLOCK_RE.sub("", without_thoughts).strip()


def _history_parts_for_files(files: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for file_info in files or []:
        if not isinstance(file_info, dict):
            continue
        mime_type = str(file_info.get("mime_type") or "")
        url_path = str(file_info.get("url_path") or "")
        if not mime_type.startswith("image/") or not url_path:
            continue
        parts.append(
            {
                "image": {
                    "url_path": url_path,
                    "mime_type": mime_type,
                    "original_name": file_info.get("original_name"),
                }
            }
        )
    return parts


def _trim_inline_answer(value: str) -> str:
    answer = value.strip()
    if len(answer) <= _MAX_INLINE_ANSWER_CHARS:
        return answer
    shortened = answer[: _MAX_INLINE_ANSWER_CHARS - 1].rstrip()
    boundary = max(shortened.rfind(". "), shortened.rfind("! "), shortened.rfind("? "))
    if boundary > _MAX_INLINE_ANSWER_CHARS // 2:
        shortened = shortened[: boundary + 1]
    return f"{shortened}…"


def _sanitize_rich_markdown(value: str) -> str:
    without_embedded_media = _RICH_MARKDOWN_MEDIA_RE.sub(
        lambda match: f"[{match.group(1)}]({match.group(2)})",
        str(value or ""),
    )
    return without_embedded_media.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _trim_rich_answer(value: str, max_chars: int) -> str:
    answer = str(value or "").strip()
    if len(answer) <= max_chars:
        return answer
    shortened = answer[: max_chars - 1].rstrip()
    boundary = max(shortened.rfind("\n\n"), shortened.rfind(". "))
    if boundary > max_chars // 2:
        shortened = shortened[: boundary + 1].rstrip()
    return f"{shortened}…"


def _generate_answer(
    linked: LinkedTelegramUser,
    question: str,
    *,
    source: str,
    chat_payload: dict[str, Any] | None,
    session_chat: UserChatHistory | None,
    request_id: str,
    brief: bool,
    persist: bool,
    files: list[dict[str, Any]] | None = None,
    on_progress: Callable[[str, bool, str], None] | None = None,
    operation: str = "send",
    target_message_id: str | None = None,
) -> str:
    if operation not in {"send", "regenerate"}:
        raise ValueError("invalid_telegram_chat_operation")
    if operation == "regenerate" and (not session_chat or not target_message_id):
        raise ValueError("invalid_regenerate_target")
    if session_chat:
        existing = _existing_delivery(session_chat.session_id, linked.user.id, request_id)
        if existing is not None:
            return existing

    start_at = time.perf_counter()
    thinking_level = _telegram_thinking_level(source)
    max_context_messages = _telegram_context_limit(source)
    history_is_canonical = _telegram_use_canonical_history(source)
    graph = load_chat_graph(session_chat.session_id, linked.user.id) if session_chat else []
    parent_message_id: str | None = None
    if operation == "regenerate":
        history, parent_message_id = conversation_context_for_operation(
            graph, operation, target_message_id
        )
    else:
        history = load_chat_history(session_chat.session_id, linked.user.id) if session_chat else []

    personal = source == "telegram_private" and not brief
    secretary = source == "telegram_business"
    settings = telegram_agent.preferences(linked.user.id)
    model_name = settings["model"] if personal or secretary else DEFAULT_MODEL_ID
    if not can_user_access_model(model_name, linked.user.id):
        raise RuntimeError("model_access_denied")
    user_data: dict[str, Any] = {
        "message": question,
        "history": history[-max_context_messages:] if history else [],
        "history_is_canonical": history_is_canonical,
        "request_id": request_id,
        "files": files or [],
        "privacy": {"service_improvement_opt_in": False},
        "webSearch": False,
        "autoWebSearch": False,
        "toolsEnabled": personal,
        "_generation_control": _generation_control.get(),
        "telegram_agent": personal,
        "external_telegram": secretary,
        "model": model_name,
        "serviceTier": settings["serviceTier"] if personal or secretary else "standard",
        "thinkingLevel": thinking_level,
        "telegram_context": _telegram_context(linked, source, chat_payload, brief=brief),
        "meta": {
            "platform_type": "Telegram",
            "device_type": source,
            "interface_language": linked.language,
        },
    }
    if personal:
        user_data["autoWebSearch"] = settings["webSearch"]
        if settings["mind_id"]:
            user_data["active_mind"] = resolve_mind_context_for_chat(
                settings["mind_id"], linked.user.id
            )
            if model_name.startswith(("codex/", "key/", "chatgpt/")):
                require_portable_mind(user_data["active_mind"], linked.user.id)
    model_func = get_model_function(model_name)
    if not model_func:
        raise RuntimeError("Default model is unavailable")

    artifacts = []
    panel_text = ""
    reply_chunks: list[str] = []
    internal_chunks: list[str] = []
    thought_summary_chunks: list[str] = []
    thinking_active = False
    try:
        for chunk in model_func(linked.user.id, user_data):
            if control := _generation_control.get():
                control.check()
            if isinstance(chunk, dict):
                if "thinking_update" in chunk:
                    update = chunk.get("thinking_update")
                    thinking_active = (
                        isinstance(update, dict) and update.get("status") != "complete"
                    )
                    if isinstance(update, dict) and update.get("contentDelta"):
                        thought_summary_chunks.append(str(update["contentDelta"]))
                    if on_progress:
                        on_progress(
                            "".join(reply_chunks),
                            thinking_active,
                            "".join(thought_summary_chunks),
                        )
                    continue
                if "internal_reply_part" in chunk:
                    internal_chunks.append(str(chunk.get("internal_reply_part") or ""))
                    continue
                if chunk.get("python_artifacts") and personal:
                    artifacts.extend(chunk["python_artifacts"])
                    continue
                if chunk.get("widget_update"):
                    widget = chunk["widget_update"]
                    state = widget.get("state") or {}
                    if widget.get("tag") == "questions":
                        panel_text = "\n".join(
                            [
                                state.get("title", ""),
                                *(
                                    q["question"] + " — " + " / ".join(q["options"])
                                    for q in state.get("questions", [])
                                ),
                            ]
                        )
                    elif widget.get("tag") == "plan" and on_progress:
                        on_progress(
                            "\n".join(step["title"] for step in state.get("steps", [])), False, ""
                        )
                    continue
                if "reply_part" in chunk:
                    reply_chunks.append(
                        re.sub(
                            r"<tool_panel\b[^>]*></tool_panel>",
                            "",
                            str(chunk.get("reply_part") or ""),
                        )
                    )
                elif "reply" in chunk:
                    reply_chunks = [str(chunk.get("reply") or "")]
                else:
                    continue
            else:
                reply_chunks.append(str(chunk))
            if on_progress:
                on_progress(
                    "".join(reply_chunks),
                    thinking_active,
                    "".join(thought_summary_chunks),
                )
    except Exception:
        if control := _generation_control.get():
            control.check()
        logger.exception(
            "Telegram answer generation failed: user_id=%s source=%s request_id=%s",
            linked.user.id,
            source,
            request_id,
        )
        raise

    raw_reply = "".join(reply_chunks)
    answer = (
        _visible_answer(raw_reply)
        or panel_text
        or (telegram_text(linked.language, "files_ready") if artifacts else "")
    )
    if brief:
        answer = _trim_inline_answer(answer)
    if not answer:
        raise RuntimeError("Model returned an empty Telegram answer")

    if persist and session_chat:
        user_message = None
        if control := _generation_control.get():
            control.check()
        if operation == "send":
            graph = load_chat_graph(session_chat.session_id, linked.user.id)
            history_context, parent_message_id = conversation_context_for_operation(
                graph, operation, None
            )
            del history_context
            user_message = normalize_message(
                {
                    "id": f"tg_u_{request_id}"[:120],
                    "role": "user",
                    "parts": ([{"text": question}] if question else [])
                    + _history_parts_for_files(files),
                    "request_id": request_id,
                    "source": source,
                }
            )
        model_message = normalize_message(
            {
                "id": f"tg_a_{request_id}"[:120],
                "role": "model",
                "parts": _build_model_message_parts(
                    "".join(internal_chunks) + answer, None, artifacts
                ),
                "request_id": request_id,
                "delivery_status": "complete",
                "source": source,
            }
        )
        persist_chat_operation(
            session_chat.session_id,
            operation=operation,
            target_message_id=target_message_id,
            parent_message_id=parent_message_id,
            user_message=user_message,
            model_message=model_message,
            model_name=model_name,
            user_id=linked.user.id,
        )
    generation_ms = (time.perf_counter() - start_at) * 1000.0
    logger.info(
        "Telegram answer generated: request_id=%s source=%s user_id=%s session=%s ms=%.2f chunks=%d",
        request_id,
        source,
        linked.user.id,
        session_chat.session_id if session_chat else "none",
        generation_ms,
        len(reply_chunks),
    )
    return answer


def _split_rich_message(text: str) -> list[str]:
    remaining = text.strip()
    chunks: list[str] = []
    while remaining:
        if len(remaining) <= _MAX_RICH_MESSAGE_CHARS:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n\n", 0, _MAX_RICH_MESSAGE_CHARS)
        if cut < _MAX_RICH_MESSAGE_CHARS // 2:
            cut = _MAX_RICH_MESSAGE_CHARS
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return chunks or [" "]


def _send_answer(
    api: TelegramBotAPI,
    chat_id: int,
    answer: str,
    *,
    reply_to_message_id: int | None,
    reply_markup: dict[str, Any] | None = None,
) -> None:
    for index, chunk in enumerate(_split_rich_message(answer)):
        try:
            api.send_rich(
                chat_id,
                chunk,
                reply_to_message_id=reply_to_message_id if index == 0 else None,
                reply_markup=reply_markup if index == 0 else None,
            )
        except TelegramAPIError:
            logger.warning("Rich Telegram message failed; using plain fallback", exc_info=True)
            plain_parts = [chunk[start : start + 4096] for start in range(0, len(chunk), 4096)]
            for plain_index, plain_part in enumerate(plain_parts):
                api.send_text(
                    chat_id,
                    plain_part,
                    reply_to_message_id=(
                        reply_to_message_id if index == 0 and plain_index == 0 else None
                    ),
                    reply_markup=(reply_markup if index == 0 and plain_index == 0 else None),
                )


def _website_keyboard(language: str, *, inline: bool = False) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = []
    if BACKEND_URL:
        rows.append(
            [
                {
                    "text": telegram_text(
                        language, "inline_connect_button" if inline else "connect_button"
                    ),
                    "url": BACKEND_URL.rstrip("/") + "/?auth=link#settings/account",
                }
            ]
        )
    return {"inline_keyboard": rows}


def _inline_keyboard(language: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {
                    "text": telegram_text(language, "inline_follow_up_button"),
                    "switch_inline_query_current_chat": "",
                }
            ]
        ]
    }


def _answer_keyboard(language: str, request_id: str) -> dict[str, Any] | None:
    if not _CALLBACK_REQUEST_ID_RE.fullmatch(request_id):
        return None
    repeat_data = f"repeat:{request_id}"
    speak_data = f"speak:{request_id}"
    if len(repeat_data.encode("utf-8")) > 64 or len(speak_data.encode("utf-8")) > 64:
        return None
    return {
        "inline_keyboard": [
            [
                {
                    "text": telegram_text(language, "repeat_button"),
                    "callback_data": repeat_data,
                },
                {
                    "text": telegram_text(language, "speak_button"),
                    "callback_data": speak_data,
                },
            ]
        ]
    }


def _inline_answer_payload(text: str, *, force_plain: bool = False) -> dict[str, Any]:
    normalized = (text or "").strip()
    if not normalized:
        normalized = telegram_text("en", "generation_failed")
    if force_plain:
        return {"message_text": _trim_inline_answer(normalized)[:_INLINE_RESULT_TEXT_CHARS]}
    rich_markdown = _trim_inline_answer(_sanitize_rich_markdown(normalized))
    return {"rich_message": {"markdown": rich_markdown}}


def _guest_answer_payload(text: str, *, force_plain: bool = False) -> dict[str, Any]:
    normalized = (text or "").strip()
    if not normalized:
        normalized = telegram_text("en", "generation_failed")
    if force_plain:
        visible = _trim_rich_answer(normalized, _INLINE_RESULT_TEXT_CHARS)
        return {"message_text": visible}
    rich_markdown = _trim_rich_answer(_sanitize_rich_markdown(normalized), _MAX_RICH_MESSAGE_CHARS)
    return {"rich_message": {"markdown": rich_markdown}}


def _inline_result_text(text: str, limit: int) -> str:
    trimmed = (text or "").strip()
    if len(trimmed) <= limit:
        return trimmed
    short = trimmed[: limit - 1].rstrip()
    if len(short) > limit * 0.8:
        return f"{short}…"
    return short[: limit - 1]


def _answer_inline_query(
    api: TelegramBotAPI,
    query_id: str,
    *,
    results: list[dict[str, Any]],
    is_personal: bool = True,
    language: str = "en",
    switch_to_pm: str | None = None,
    switch_to_pm_parameter: str | None = None,
) -> None:
    base_payload: dict[str, Any] = {
        "inline_query_id": query_id,
        "results": results,
        "cache_time": 0,
        "is_personal": is_personal,
    }
    if switch_to_pm:
        parameter = switch_to_pm_parameter or "connect_remind"
        base_payload["button"] = {
            "text": telegram_text(language, switch_to_pm),
            "start_parameter": parameter,
        }
    try:
        api.call("answerInlineQuery", base_payload)
    except TelegramAPIError:
        if base_payload.get("button"):
            legacy_payload = dict(base_payload)
            button = legacy_payload.pop("button")
            legacy_payload.pop("button", None)
            legacy_payload["switch_pm_text"] = button["text"]
            legacy_payload["switch_pm_parameter"] = button["start_parameter"]
            api.call("answerInlineQuery", legacy_payload)
            return
        raise


def _thinking_draft(language: str, thought_summary: str = "") -> str:
    safe_summary = _TG_THINKING_TAG_RE.sub("", str(thought_summary or "")).strip()
    safe_summary = re.sub(
        r"<(?:tool|python|image|search|model)_activity\b[^>]*></(?:tool|python|image|search|model)_activity>",
        "",
        safe_summary,
    ).strip()
    safe_summary = safe_summary[-4_000:]
    label = telegram_text(language, "thinking")
    content = f"{label}\n\n{safe_summary}" if safe_summary else label
    return f"<tg-thinking>{content}</tg-thinking>"


def _command_parts(text: str) -> tuple[str, str]:
    first, _, rest = text.strip().partition(" ")
    command = first.split("@", 1)[0].lower()
    return command, rest.strip()


def _message_source(message: dict[str, Any]) -> tuple[str, str]:
    chat = _as_dict(message.get("chat"))
    chat_type = str(chat.get("type") or "private")
    thread_id = str(message.get("message_thread_id") or "0")
    if chat_type == "private":
        return "telegram_private", f"private:{thread_id}" if thread_id != "0" else "private"
    return "telegram_group", f"{chat.get('id')}:{thread_id}"


def _is_addressed_to_bot(message: dict[str, Any], bot_username: str, bot_id: int) -> bool:
    chat = _as_dict(message.get("chat"))
    if chat.get("type") == "private":
        return True
    text = str(message.get("text") or message.get("caption") or "")
    if bot_username and re.search(
        _MENTION_RE_TEMPLATE.format(username=re.escape(bot_username)), text, re.IGNORECASE
    ):
        return True
    reply = message.get("reply_to_message")
    reply_from = reply.get("from") if isinstance(reply, dict) else None
    return bool(isinstance(reply_from, dict) and int(reply_from.get("id") or 0) == bot_id)


def _clean_group_question(text: str, bot_username: str) -> str:
    cleaned = str(text or "")
    if bot_username:
        cleaned = re.sub(
            _MENTION_RE_TEMPLATE.format(username=re.escape(bot_username)),
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    return re.sub(r"\s+", " ", cleaned).strip()


def _remove_uncommitted_upload(file_info: dict[str, Any] | None) -> None:
    if not isinstance(file_info, dict) or not file_info.get("path"):
        return
    try:
        upload_root = UPLOAD_FOLDER.resolve()
        path = Path(str(file_info["path"])).resolve()
        if path.parent == upload_root and path.is_file():
            path.unlink()
    except OSError:
        logger.warning("Could not remove an uncommitted Telegram upload", exc_info=True)


def _download_message_attachment(
    api: TelegramBotAPI,
    message: dict[str, Any],
    *,
    storage_owner: str,
) -> dict[str, Any] | None:
    document = message.get("document")
    if isinstance(document, dict) and (message.get("chat") or {}).get("type") == "private":
        if not isinstance(document.get("file_id"), str) or not isinstance(
            document.get("file_name"), str
        ):
            raise TelegramAPIError("getFile", "invalid_document")
        if int(document.get("file_size") or 0) > CHAT_UPLOAD_MAX_TOTAL_BYTES:
            raise TelegramAPIError("getFile", "file_too_large")
        content = api.download_file(document["file_id"], max_bytes=CHAT_UPLOAD_MAX_TOTAL_BYTES)
        file = FileStorage(
            stream=io.BytesIO(content),
            filename=document["file_name"],
            content_type=document.get("mime_type"),
        )
        if not validate_chat_uploads([file])[0]:
            raise TelegramAPIError("getFile", "invalid_document")
        return handle_file_upload(file, storage_owner)
    photos = message.get("photo")
    if not isinstance(photos, list) or not photos:
        return None
    candidates = [photo for photo in photos if isinstance(photo, dict) and photo.get("file_id")]
    if not candidates:
        raise TelegramAPIError("getFile", "missing_photo_file_id")

    def safe_dimension(value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    photo = max(
        candidates,
        key=lambda item: safe_dimension(item.get("width")) * safe_dimension(item.get("height")),
    )
    declared_size = safe_dimension(photo.get("file_size"))
    if declared_size > CHAT_UPLOAD_MAX_TOTAL_BYTES:
        raise TelegramAPIError("getFile", "file_too_large")
    raw = api.download_file(
        str(photo.get("file_id")),
        max_bytes=CHAT_UPLOAD_MAX_TOTAL_BYTES,
    )
    storage = FileStorage(
        stream=io.BytesIO(raw),
        filename=f"telegram-photo-{uuid.uuid4().hex}.jpg",
        content_type="image/jpeg",
        content_length=len(raw),
    )
    return handle_file_upload(storage, storage_owner)


def _handle_command(
    api: TelegramBotAPI,
    message: dict[str, Any],
    linked: LinkedTelegramUser | None,
    command: str,
    argument: str,
) -> bool:
    if command not in {"/start", "/help", "/settings", "/new", "/reset", "/stop", "/clear"}:
        return False
    profile = _as_dict(message.get("from"))
    language = _profile_language(profile)
    chat_id = int(_as_dict(message.get("chat")).get("id") or 0)
    if command == "/start":
        if argument.startswith("connect_"):
            chat_type = str(_as_dict(message.get("chat")).get("type") or "")
            if chat_type != "private":
                api.send_text(chat_id, telegram_text(language, "link_private_only"))
                return True
            result = consume_telegram_link_token(
                argument.removeprefix("connect_"), str(profile.get("id") or "")
            )
            message_key = {
                "linked": "link_success",
                "expired": "link_expired",
                "identity_in_use": "link_identity_in_use",
                "already_linked": "link_already_connected",
                "restricted": "account_restricted",
            }.get(result, "link_invalid")
            api.send_text(
                chat_id,
                telegram_text(language, message_key),
                reply_markup=_inline_keyboard(language) if result == "linked" else None,
            )
            return True
        if linked and not is_account_disabled(linked.user):
            keyboard = _inline_keyboard(language)
            if BACKEND_URL:
                keyboard["inline_keyboard"].insert(
                    0,
                    [
                        {
                            "text": telegram_text(language, "open_remind_button"),
                            "url": BACKEND_URL.rstrip("/"),
                        }
                    ],
                )
            api.send_text(
                chat_id,
                telegram_text(language, "start_linked"),
                reply_markup=keyboard,
            )
        else:
            api.send_text(
                chat_id,
                telegram_text(language, "start_unlinked"),
                reply_markup=_website_keyboard(language),
            )
        return True
    if not linked:
        api.send_text(
            chat_id,
            telegram_text(language, "not_connected"),
            reply_markup=_website_keyboard(language),
        )
        return True
    if is_account_disabled(linked.user):
        api.send_text(chat_id, telegram_text(language, "account_restricted"))
        return True
    if command == "/help":
        api.send_text(chat_id, telegram_text(language, "help"))
    elif command == "/settings":
        keyboard = (
            {
                "inline_keyboard": [
                    [
                        {
                            "text": telegram_text(language, "command_settings"),
                            "url": BACKEND_URL.rstrip("/") + "/#settings/telegram",
                        }
                    ]
                ]
            }
            if BACKEND_URL and BACKEND_URL.startswith("https://")
            else None
        )
        api.send_text(chat_id, telegram_text(language, "settings"), reply_markup=keyboard)
    elif command in {"/new", "/reset", "/stop", "/clear"}:
        source, external_context = _message_source(message)
        _start_new_context(linked, source, external_context)
        api.send_text(
            chat_id,
            telegram_text(language, "new_chat" if command == "/new" else "context_reset"),
        )
    return True


def handle_message_update(
    api: TelegramBotAPI,
    message: dict[str, Any],
    *,
    update_id: int,
    bot_username: str,
    bot_id: int,
) -> None:
    profile = _as_dict(message.get("from"))
    if not profile or profile.get("is_bot"):
        return
    if not _is_addressed_to_bot(message, bot_username, bot_id):
        return
    language = _profile_language(profile)
    linked = _linked_user(profile)
    text = str(message.get("text") or message.get("caption") or "").strip()
    has_photo = isinstance(message.get("photo"), list) and bool(message.get("photo"))
    has_document = (
        isinstance(message.get("document"), dict)
        and (message.get("chat") or {}).get("type") == "private"
    )
    if text.startswith("/"):
        command, argument = _command_parts(text)
        if _handle_command(api, message, linked, command, argument):
            return
    chat_id = int(_as_dict(message.get("chat")).get("id") or 0)
    message_id = int(message.get("message_id") or 0)
    if not linked:
        api.send_text(
            chat_id,
            telegram_text(language, "not_connected"),
            reply_to_message_id=message_id,
            reply_markup=_website_keyboard(language),
        )
        return
    if is_account_disabled(linked.user):
        api.send_text(
            chat_id,
            telegram_text(language, "account_restricted"),
            reply_to_message_id=message_id,
        )
        return
    if not text and not (has_photo or has_document):
        api.send_text(
            chat_id,
            telegram_text(language, "unsupported_message"),
            reply_to_message_id=message_id,
        )
        return
    question = _clean_group_question(text, bot_username)[:_MAX_INPUT_CHARS]
    if not question and has_document:
        question = telegram_text(language, "document_default_prompt")
    if not question and has_photo:
        question = telegram_text(language, "photo_default_prompt")
    if not question:
        api.send_text(
            chat_id,
            telegram_text(language, "empty_question"),
            reply_to_message_id=message_id,
        )
        return
    if not _message_window.allow(str(profile.get("id"))):
        api.send_text(
            chat_id,
            telegram_text(language, "rate_limited"),
            reply_to_message_id=message_id,
        )
        return

    source, external_context = _message_source(message)
    chat_payload = _as_dict(message.get("chat"))
    session_chat = _chat_for_context(
        linked,
        source,
        external_context,
        _telegram_context(linked, source, chat_payload, brief=False),
        create=True,
    )
    if not session_chat:
        raise RuntimeError("Could not create Telegram chat session")
    request_id = f"tg_{update_id}"
    existing_answer = _existing_delivery(session_chat.session_id, linked.user.id, request_id)
    if existing_answer is not None:
        _send_answer(
            api,
            chat_id,
            existing_answer,
            reply_to_message_id=message_id,
            reply_markup=_answer_keyboard(language, request_id),
        )
        return
    uploaded_attachment: dict[str, Any] | None = None
    if has_photo or has_document:
        try:
            uploaded_attachment = _download_message_attachment(
                api,
                message,
                storage_owner=session_chat.session_id,
            )
            if uploaded_attachment is None:
                raise TelegramAPIError("getFile", "invalid_photo")
        except TelegramAPIError as exc:
            key = (
                ("document_too_large" if has_document else "photo_too_large")
                if exc.description == "file_too_large"
                else ("document_failed" if has_document else "photo_failed")
            )
            api.send_text(
                chat_id,
                telegram_text(language, key),
                reply_to_message_id=message_id,
            )
            return
    draft_id = max(1, update_id)
    last_draft_at = 0.0
    last_draft_text = ""
    private_chat = chat_payload.get("type") == "private"
    if private_chat:
        api.send_rich_draft(
            chat_id,
            draft_id,
            _thinking_draft(language),
        )

    def progress(partial: str, thinking: bool, thought_summary: str) -> None:
        nonlocal last_draft_at, last_draft_text
        if not private_chat:
            return
        now = time.monotonic()
        visible = partial[-_MAX_RICH_MESSAGE_CHARS:]
        if visible == last_draft_text or now - last_draft_at < _DRAFT_INTERVAL_SECONDS:
            return
        thinking_block = (
            f"{_thinking_draft(language, thought_summary)}\n\n"
            if thinking or (not visible and thought_summary)
            else ""
        )
        api.send_rich_draft(chat_id, draft_id, thinking_block + visible)
        last_draft_at = now
        last_draft_text = visible

    try:
        answer = _generate_answer(
            linked,
            question,
            source=source,
            chat_payload=chat_payload,
            session_chat=session_chat,
            request_id=request_id,
            brief=False,
            persist=True,
            files=[uploaded_attachment] if uploaded_attachment else [],
            on_progress=progress,
        )
    except Exception:
        _remove_uncommitted_upload(uploaded_attachment)
        if control := _generation_control.get():
            if control.stopped.is_set():
                return
        logger.exception("Telegram message generation failed for update_id=%s", update_id)
        api.send_text(
            chat_id,
            telegram_text(language, "generation_failed"),
            reply_to_message_id=message_id,
        )
        return
    if control := _generation_control.get():
        control.check()
    _send_answer(
        api,
        chat_id,
        answer,
        reply_to_message_id=message_id,
        reply_markup=_answer_keyboard(language, request_id),
    )
    if source == "telegram_private":
        _send_saved_documents(api, linked, session_chat, request_id, chat_id, message_id)


def _send_saved_documents(api, linked, session_chat, request_id, chat_id, reply_to):
    if not session_chat:
        return
    graph = load_chat_graph(session_chat.session_id, linked.user.id)
    response = _message_for_request(graph, request_id, "model") or {}
    for part in response.get("parts", [])[:23]:
        file = part.get("file") if isinstance(part, dict) else None
        if not isinstance(file, dict) or file.get("source") not in ("tool", "python"):
            continue
        url = file.get("url_path", "")
        if not re.fullmatch(r"/uploads/[a-f0-9]{32}\.[a-z0-9]{1,10}", url):
            continue
        path = Path(UPLOAD_FOLDER) / url.rsplit("/", 1)[1]
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
            continue
        name = Path(str(file.get("original_name") or path.name)).name
        api.send_document(
            chat_id, path, name, file.get("mime_type") or "application/octet-stream", reply_to
        )


def handle_callback_query(api: TelegramBotAPI, callback: dict[str, Any]) -> None:
    query_id = str(callback.get("id") or "")
    profile = _as_dict(callback.get("from"))
    language = _profile_language(profile)
    match = _CALLBACK_DATA_RE.fullmatch(str(callback.get("data") or ""))
    callback_message = _as_dict(callback.get("message"))
    if not query_id or not profile or profile.get("is_bot") or not match or not callback_message:
        if query_id:
            api.answer_callback(
                query_id,
                telegram_text(language, "action_unavailable"),
                show_alert=True,
            )
        return

    linked = _linked_user(profile)
    if not linked or is_account_disabled(linked.user):
        api.answer_callback(
            query_id,
            telegram_text(
                language,
                "account_restricted" if linked else "not_connected",
            ),
            show_alert=True,
        )
        return

    action, request_id = match.groups()
    source, external_context = _message_source(callback_message)
    chat_payload = _as_dict(callback_message.get("chat"))
    session_chat = _chat_for_context(
        linked,
        source,
        external_context,
        _telegram_context(linked, source, chat_payload, brief=False),
        create=False,
    )
    if not session_chat:
        api.answer_callback(
            query_id,
            telegram_text(language, "action_unavailable"),
            show_alert=True,
        )
        return

    graph = load_chat_graph(session_chat.session_id, linked.user.id)
    model_message = _message_for_request(graph, request_id, "model")
    answer = _message_text(model_message)
    if not model_message or not answer:
        api.answer_callback(
            query_id,
            telegram_text(language, "action_unavailable"),
            show_alert=True,
        )
        return

    chat_id = int(chat_payload.get("id") or 0)
    reply_to_message_id = int(callback_message.get("message_id") or 0)
    if action == "speak":
        if not _voice_window.allow(str(profile.get("id"))):
            api.answer_callback(
                query_id,
                telegram_text(language, "rate_limited"),
                show_alert=True,
            )
            return
        tts_text = answer[:TTS_MAX_CHARS]
        status_key = "speak_truncated" if len(answer) > TTS_MAX_CHARS else "speak_started"
        api.answer_callback(query_id, telegram_text(language, status_key))
        try:
            segments = synthesize_text_segments(tts_text)
        except Exception:
            logger.exception("Telegram speech synthesis failed: user_id=%s", linked.user.id)
            segments = []
        encoded_audio = segments[0].get("audio_base64") if segments else None
        if not isinstance(encoded_audio, str):
            api.send_text(
                chat_id,
                telegram_text(language, "speak_failed"),
                reply_to_message_id=reply_to_message_id,
            )
            return
        try:
            audio = base64.b64decode(encoded_audio, validate=True)
        except (binascii.Error, ValueError):
            audio = b""
        if not audio:
            api.send_text(
                chat_id,
                telegram_text(language, "speak_failed"),
                reply_to_message_id=reply_to_message_id,
            )
            return
        try:
            api.send_voice(
                chat_id,
                audio,
                reply_to_message_id=reply_to_message_id,
            )
        except TelegramAPIError:
            logger.warning("Telegram voice delivery failed", exc_info=True)
            api.send_text(
                chat_id,
                telegram_text(language, "speak_failed"),
                reply_to_message_id=reply_to_message_id,
            )
        return

    if not _message_window.allow(str(profile.get("id"))):
        api.answer_callback(
            query_id,
            telegram_text(language, "rate_limited"),
            show_alert=True,
        )
        return
    user_message = _parent_user_message(graph, model_message)
    question = _message_text(user_message)
    if not question:
        api.answer_callback(
            query_id,
            telegram_text(language, "action_unavailable"),
            show_alert=True,
        )
        return
    files = _restored_message_files(user_message)
    callback_request_id = "tg_cb_" + hashlib.sha256(query_id.encode("utf-8")).hexdigest()[:32]
    api.answer_callback(query_id, telegram_text(language, "repeat_started"))
    try:
        repeated_answer = _generate_answer(
            linked,
            question,
            source=source,
            chat_payload=chat_payload,
            session_chat=session_chat,
            request_id=callback_request_id,
            brief=False,
            persist=True,
            files=files,
            operation="regenerate",
            target_message_id=str(model_message.get("id") or ""),
        )
    except Exception:
        logger.exception(
            "Telegram callback generation failed: user_id=%s request_id=%s",
            linked.user.id,
            callback_request_id,
        )
        api.send_text(
            chat_id,
            telegram_text(language, "generation_failed"),
            reply_to_message_id=reply_to_message_id,
        )
        return
    _send_answer(
        api,
        chat_id,
        repeated_answer,
        reply_to_message_id=reply_to_message_id,
        reply_markup=_answer_keyboard(language, callback_request_id),
    )
    if source == "telegram_private":
        _send_saved_documents(
            api, linked, session_chat, callback_request_id, chat_id, reply_to_message_id
        )


def handle_guest_update(
    api: TelegramBotAPI,
    message: dict[str, Any],
    *,
    update_id: int,
    bot_username: str,
) -> None:
    profile = message.get("guest_bot_caller_user")
    if not isinstance(profile, dict):
        profile = message.get("from") if isinstance(message.get("from"), dict) else {}
    if not profile or profile.get("is_bot"):
        return
    language = _profile_language(profile)
    linked = _linked_user(profile)
    query_id = str(message.get("guest_query_id") or "")
    if not query_id:
        return
    if not linked or is_account_disabled(linked.user):
        text = telegram_text(language, "account_restricted" if linked else "not_connected")
        api.call(
            "answerGuestQuery",
            {
                "guest_query_id": query_id,
                "result": {
                    "type": "article",
                    "id": secrets.token_hex(8),
                    "title": telegram_text(language, "inline_result_title"),
                    "input_message_content": {"message_text": text},
                },
            },
        )
        return
    question = str(message.get("text") or "").strip()[:_MAX_INPUT_CHARS]
    if bot_username:
        question = _clean_group_question(question, bot_username)
    if not question:
        return
    if not _message_window.allow(str(profile.get("id"))):
        result = {
            "type": "article",
            "id": secrets.token_hex(8),
            "title": telegram_text(language, "inline_result_title"),
            "input_message_content": {"message_text": telegram_text(language, "rate_limited")},
        }
        api.call("answerGuestQuery", {"guest_query_id": query_id, "result": result})
        return
    caller_chat = message.get("guest_bot_caller_chat")
    chat_payload = caller_chat if isinstance(caller_chat, dict) else message.get("chat") or {}
    external_context = f"{chat_payload.get('id')}:{message.get('message_thread_id') or 0}"
    source = "telegram_guest"
    session_chat = _chat_for_context(
        linked,
        source,
        external_context,
        _telegram_context(linked, source, chat_payload, brief=False),
        create=True,
    )
    if not session_chat:
        raise RuntimeError("Could not create Telegram guest session")
    rich_answer: str | None = None
    try:
        answer = _generate_answer(
            linked,
            question,
            source=source,
            chat_payload=chat_payload,
            session_chat=session_chat,
            request_id=f"tg_guest_{update_id}",
            brief=False,
            persist=True,
        )
        rich_answer = answer
        result = {
            "type": "article",
            "id": secrets.token_hex(8),
            "title": telegram_text(language, "inline_result_title"),
            "input_message_content": _guest_answer_payload(answer),
        }
    except Exception:
        logger.exception("Telegram guest generation failed for update_id=%s", update_id)
        result = {
            "type": "article",
            "id": secrets.token_hex(8),
            "title": telegram_text(language, "inline_result_title"),
            "input_message_content": {"message_text": telegram_text(language, "generation_failed")},
        }
    payload = {"guest_query_id": query_id, "result": result}
    try:
        api.call("answerGuestQuery", payload)
    except TelegramAPIError:
        if rich_answer is None:
            raise
        logger.warning(
            "Telegram guest rich result was rejected; using plain fallback",
            exc_info=True,
        )
        fallback_result = dict(result)
        fallback_result["input_message_content"] = _guest_answer_payload(
            rich_answer, force_plain=True
        )
        api.call(
            "answerGuestQuery",
            {"guest_query_id": query_id, "result": fallback_result},
        )


def handle_inline_query(api: TelegramBotAPI, inline_query: dict[str, Any]) -> None:
    profile = inline_query.get("from") if isinstance(inline_query.get("from"), dict) else {}
    if not profile or profile.get("is_bot"):
        return
    language = _profile_language(profile)
    query_id = str(inline_query.get("id") or "")
    linked = _linked_user(profile)
    if not linked or is_account_disabled(linked.user):
        _answer_inline_query(
            api,
            query_id,
            results=[],
            is_personal=True,
            language=language,
            switch_to_pm="inline_connect_button",
            switch_to_pm_parameter="connect_remind",
        )
        return
    question = re.sub(r"\s+", " ", str(inline_query.get("query") or "")).strip()[
        :_MAX_INLINE_INPUT_CHARS
    ]
    if not question:
        _answer_inline_query(
            api,
            query_id,
            results=[],
            is_personal=True,
            language=language,
            switch_to_pm="inline_placeholder",
            switch_to_pm_parameter="inline_help",
        )
        return
    if not _inline_window.allow(str(profile.get("id"))):
        answer = telegram_text(language, "rate_limited")
    else:
        source = "telegram_inline"
        chat_payload = {"type": inline_query.get("chat_type") or "unknown"}
        try:
            answer = _generate_answer(
                linked,
                question,
                source=source,
                chat_payload=chat_payload,
                session_chat=None,
                request_id=(
                    "tg_inline_preview_" + hashlib.sha256(query_id.encode()).hexdigest()[:20]
                ),
                brief=True,
                persist=False,
            )
        except Exception:
            logger.exception(
                "Telegram inline generation failed: source=%s question=%s",
                source,
                _inline_result_text(question, 120),
            )
            answer = telegram_text(language, "generation_failed")
    result_id = secrets.token_urlsafe(24)[:32]
    record = TelegramInlineResult(
        result_id=result_id,
        user_id=linked.user.id,
        telegram_user_id=str(profile.get("id")),
        query_text=question,
        answer=answer,
        language=language,
    )
    db.session.add(record)
    db.session.commit()
    result = {
        "type": "article",
        "id": result_id,
        "title": _inline_result_text(
            telegram_text(language, "inline_result_title"), _INLINE_RESULT_TITLE_CHARS
        ),
        "description": _inline_result_text(
            telegram_text(language, "inline_result_description"),
            _INLINE_RESULT_DESCRIPTION_CHARS,
        ),
        "input_message_content": _inline_answer_payload(answer),
        "reply_markup": _inline_keyboard(language),
    }
    try:
        _answer_inline_query(api, query_id, results=[result], is_personal=True)
    except TelegramAPIError as exc:
        logger.warning(
            "Telegram inline result rejected: query_id=%s error_code=%s reason=%s payload=%s",
            query_id,
            exc.error_code,
            exc.description,
            _safe_preview(exc.payload),
        )
        fallback = {
            **result,
            "input_message_content": _inline_answer_payload(answer, force_plain=True),
        }
        _answer_inline_query(api, query_id, results=[fallback], is_personal=True)
    except Exception:
        db.session.delete(record)
        db.session.commit()
        raise


def handle_chosen_inline_result(chosen: dict[str, Any]) -> None:
    profile = _as_dict(chosen.get("from"))
    linked = _linked_user(profile)
    if not linked:
        return
    result_id = str(chosen.get("result_id") or "")
    record = TelegramInlineResult.query.filter_by(result_id=result_id).first()
    if (
        not record
        or record.user_id != linked.user.id
        or record.telegram_user_id != str(profile.get("id"))
        or record.selected_at is not None
    ):
        return
    source = "telegram_inline"
    chat_payload = {"type": "inline"}
    session_chat = _chat_for_context(
        linked,
        source,
        "inline",
        _telegram_context(linked, source, chat_payload, brief=True),
        create=True,
    )
    if not session_chat:
        raise RuntimeError("Could not create Telegram inline session")
    request_id = f"tg_inline_{result_id}"
    if _existing_delivery(session_chat.session_id, linked.user.id, request_id) is None:
        graph = load_chat_graph(session_chat.session_id, linked.user.id)
        _history, parent_message_id = conversation_context_for_operation(graph, "send", None)
        user_message = normalize_message(
            {
                "id": f"tg_u_{result_id}",
                "role": "user",
                "parts": [{"text": record.query_text}],
                "request_id": request_id,
                "source": source,
            }
        )
        model_message = normalize_message(
            {
                "id": f"tg_a_{result_id}",
                "role": "model",
                "parts": [{"text": record.answer}],
                "request_id": request_id,
                "delivery_status": "complete",
                "source": source,
            }
        )
        persist_chat_operation(
            session_chat.session_id,
            operation="send",
            target_message_id=None,
            parent_message_id=parent_message_id,
            user_message=user_message,
            model_message=model_message,
            model_name=DEFAULT_MODEL_ID,
            user_id=linked.user.id,
        )
    record.selected_at = datetime.utcnow()
    db.session.commit()


def _prune_inline_results() -> None:
    telegram_agent.prune_receipts()
    cutoff = datetime.utcnow() - timedelta(days=_INLINE_RETENTION_DAYS)
    TelegramInlineResult.query.filter(TelegramInlineResult.created_at < cutoff).delete(
        synchronize_session=False
    )
    db.session.commit()


def configure_bot(api: TelegramBotAPI) -> tuple[int, str]:
    me = api.call("getMe")
    if not isinstance(me, dict):
        raise RuntimeError("Telegram getMe returned an invalid result")
    bot_id = int(me.get("id") or 0)
    username = str(me.get("username") or TELEGRAM_BOT_USERNAME).strip().lstrip("@")
    if not bot_id or not username:
        raise RuntimeError("Telegram bot identity is incomplete")
    configured = False
    try:
        api.call(
            "setMySettings",
            {
                "supports_inline_queries": True,
                "supports_guest_queries": True,
                "can_connect_to_business": True,
                "has_topics_enabled": True,
                "allows_users_to_create_topics": True,
                "has_topic_sidebar": True,
            },
        )
        configured = True
    except TelegramAPIError:
        logger.warning("Telegram account connections and topic settings could not be applied")
    for language in sorted(SUPPORTED_LANGUAGES):
        commands = [
            {"command": command, "description": telegram_text(language, f"command_{command}")}
            for command in ("start", "new", "reset", "stop", "clear", "help", "settings")
        ]
        api.call("setMyCommands", {"commands": commands, "language_code": language})
    if not configured and me.get("supports_inline_queries") is not True:
        logger.warning("Telegram inline mode is not enabled in BotFather")
    if not configured and me.get("supports_guest_queries") is not True:
        logger.warning("Telegram Guest Mode is not enabled in BotFather")
    return bot_id, username


def dispatch_update(api, update, *, bot_id, bot_username):
    message = update.get("message") or (update.get("callback_query") or {}).get("message") or {}
    thread = message.get("message_thread_id")
    token = _delivery_topic.set(
        (message.get("chat", {}).get("id"), thread) if type(thread) is int and thread > 0 else None
    )
    try:
        return _dispatch_update(api, update, bot_id=bot_id, bot_username=bot_username)
    finally:
        _delivery_topic.reset(token)


def _business_message(api, message, bot_username):
    identifier = message.get("business_connection_id")
    if not isinstance(identifier, str) or not identifier or len(identifier) > 200:
        return
    binding = db.session.get(TelegramBusinessLink, identifier)
    if not binding:
        latest = api.call("getBusinessConnection", {"business_connection_id": identifier})
        if not isinstance(latest, dict) or latest.get("id") != identifier:
            return
        owner = _linked_user(latest.get("user") or {})
        if not owner or is_account_disabled(owner.user):
            return
        telegram_agent.bind_business(owner, latest, 0)
        binding = db.session.get(TelegramBusinessLink, identifier)
    sender = message.get("from") or {}
    if (
        not binding
        or not binding.enabled
        or not binding.can_reply
        or sender.get("is_bot")
        or str(sender.get("id")) == binding.telegram_user_id
        or message.get("sender_business_bot")
    ):
        return
    linked = _linked_user({"id": binding.telegram_user_id})
    if not linked or linked.user.id != binding.user_id or is_account_disabled(linked.user):
        return
    settings = telegram_agent.preferences(linked.user.id)
    text = str(message.get("text") or "").strip()
    chat = message.get("chat") or {}
    stamp = message.get("date")
    if (
        not text
        or chat.get("type") != "private"
        or type(chat.get("id")) is not int
        or type(message.get("message_id")) is not int
        or type(stamp) is not int
        or not 0 <= time.time() - stamp <= 86400
    ):
        return
    if (
        settings["secretaryMode"] == "off"
        or settings["secretaryMode"] == "mentions"
        and not re.search(_MENTION_RE_TEMPLATE.format(username=re.escape(bot_username)), text, re.I)
    ):
        return
    if not _message_window.allow(
        "business:" + str(linked.user.id)
    ) or not telegram_agent.claim_delivery(binding, chat["id"], message["message_id"]):
        return
    answer = _generate_answer(
        linked,
        text,
        source="telegram_business",
        chat_payload={},
        session_chat=None,
        request_id=f"tg_business_{message['message_id']}",
        brief=False,
        persist=False,
    )
    latest = api.call("getBusinessConnection", {"business_connection_id": identifier})
    if (
        not isinstance(latest, dict)
        or str((latest.get("user") or {}).get("id")) != binding.telegram_user_id
        or latest.get("is_enabled") is not True
        or (latest.get("rights") or {}).get("can_reply") is not True
    ):
        return
    db.session.expire_all()
    if telegram_agent.preferences(linked.user.id)["secretaryMode"] != settings["secretaryMode"]:
        return
    api.call(
        "sendMessage",
        {
            "business_connection_id": identifier,
            "chat_id": chat["id"],
            "text": answer[:4096],
            "reply_parameters": {
                "message_id": message["message_id"],
                "allow_sending_without_reply": False,
            },
        },
    )


def _dispatch_update(
    api: TelegramBotAPI,
    update: dict[str, Any],
    *,
    bot_id: int,
    bot_username: str,
) -> None:
    update_id = int(update.get("update_id") or 0)
    if isinstance(update.get("business_connection"), dict):
        data = update["business_connection"]
        linked = _linked_user(data.get("user") or {})
        if linked and not is_account_disabled(linked.user):
            telegram_agent.bind_business(linked, data, update_id)
        return
    if isinstance(update.get("business_message"), dict):
        _business_message(api, update["business_message"], bot_username)
        return
    if isinstance(update.get("message"), dict):
        handle_message_update(
            api,
            update["message"],
            update_id=update_id,
            bot_username=bot_username,
            bot_id=bot_id,
        )
    elif isinstance(update.get("callback_query"), dict):
        handle_callback_query(api, update["callback_query"])
    elif isinstance(update.get("guest_message"), dict):
        handle_guest_update(
            api,
            update["guest_message"],
            update_id=update_id,
            bot_username=bot_username,
        )
    elif isinstance(update.get("inline_query"), dict):
        handle_inline_query(api, update["inline_query"])
    elif isinstance(update.get("chosen_inline_result"), dict):
        handle_chosen_inline_result(update["chosen_inline_result"])


def run_telegram_bot(app) -> None:
    api = TelegramBotAPI()
    bot_id, bot_username = configure_bot(api)
    local = threading.local()

    def handle(update, control):
        if not hasattr(local, "api"):
            local.api = TelegramBotAPI()
        token = _generation_control.set(control)
        try:
            with app.app_context():
                dispatch_update(local.api, update, bot_id=bot_id, bot_username=bot_username)
        except GenerationStopped:
            pass
        except Exception:
            logger.exception("Telegram update failed: update_id=%s", update.get("update_id"))
        finally:
            _generation_control.reset(token)

    queue = TelegramUpdates(handle, workers=_int_env("TELEGRAM_AGENT_WORKERS", 4, max_value=16))
    logger.info("Telegram worker started for @%s", bot_username)
    last_prune = 0.0
    delay = 1.0
    try:
        while True:
            try:
                queue.ingest([])
                updates = api.get_updates(queue.offset, active=bool(queue.pending))
                before = len(queue.pending)
                queue.ingest(updates)
                if queue.pending and len(queue.pending) == before:
                    queue.pause()
                if time.monotonic() - last_prune > 3600:
                    with app.app_context():
                        _prune_inline_results()
                    last_prune = time.monotonic()
                delay = 1.0
            except Exception:
                logger.warning("Telegram polling unavailable; retrying", exc_info=True)
                time.sleep(delay)
                delay = min(delay * 2, 30)
    finally:
        queue.close()
