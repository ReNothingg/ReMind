from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

import requests
from sqlalchemy.exc import IntegrityError

from ai_engine import get_model_function
from ai_engine.registry import DEFAULT_MODEL_ID
from config import (
    BACKEND_URL,
    SECRET_KEY,
    TELEGRAM_BOT_API_BASE,
    TELEGRAM_BOT_POLL_TIMEOUT_SECONDS,
    TELEGRAM_BOT_REQUEST_TIMEOUT_SECONDS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_BOT_USERNAME,
)
from services.chat_history import (
    conversation_context_for_operation,
    load_chat_graph,
    load_chat_history,
    normalize_message,
    persist_chat_operation,
)
from services.telegram_i18n import language_from_telegram, telegram_text
from utils.auth import (
    AuthIdentity,
    TelegramInlineResult,
    User,
    UserChatHistory,
    db,
    is_account_disabled,
)

logger = logging.getLogger("remind")
_THINK_RE = re.compile(r"<think\b[^>]*>[\s\S]*?</think>", re.IGNORECASE)
_UNSUPPORTED_TOOL_BLOCK_RE = re.compile(
    r"```(?:canmore|chartjs|d3js|mermaid|nomnoml)\b[\s\S]*?```"
    r"|<(?:beatbox|quiz|spinwheel)\b[^>]*>[\s\S]*?</(?:beatbox|quiz|spinwheel)>",
    re.IGNORECASE,
)
_TG_THINKING_TAG_RE = re.compile(r"</?tg-thinking\b[^>]*>", re.IGNORECASE)
_MENTION_RE_TEMPLATE = r"(?<![\w@])@{username}(?!\w)"
_MAX_INPUT_CHARS = 8_000
_MAX_INLINE_INPUT_CHARS = 2_000
_MAX_INLINE_ANSWER_CHARS = 3_500
_MAX_RICH_MESSAGE_CHARS = 32_000
_INLINE_RETENTION_DAYS = 2
_INLINE_RESULT_TITLE_CHARS = 80
_INLINE_RESULT_DESCRIPTION_CHARS = 140
_INLINE_RESULT_TEXT_CHARS = 4_000


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


def _float_env(name: str, default: float, *, min_value: float = 0.1, max_value: float = 5.0) -> float:
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


_DRAFT_INTERVAL_SECONDS = _float_env("TELEGRAM_DRAFT_INTERVAL_SECONDS", 0.55, min_value=0.2, max_value=5.0)
_TELEGRAM_MAX_CONTEXT_MESSAGES = _int_env("TELEGRAM_MAX_CONTEXT_MESSAGES", 4, min_value=1, max_value=20)
_TELEGRAM_MAX_CONTEXT_MESSAGES_INLINE = _int_env(
    "TELEGRAM_MAX_CONTEXT_MESSAGES_INLINE", _TELEGRAM_MAX_CONTEXT_MESSAGES, min_value=1, max_value=20
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
    return _TELEGRAM_MAX_CONTEXT_MESSAGES_INLINE if source == "telegram_inline" else _TELEGRAM_MAX_CONTEXT_MESSAGES


def _telegram_thinking_level(source: str) -> str:
    if source == "telegram_inline":
        return _TELEGRAM_THINKING_LEVEL_INLINE
    if source.startswith("telegram_"):
        return _TELEGRAM_THINKING_LEVEL_MESSAGE
    return _TELEGRAM_THINKING_LEVEL


def _telegram_use_canonical_history(source: str) -> bool:
    return not source.startswith("telegram_")


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
    if not payload:
        return ""
    message_text = payload.get("results", [])
    if isinstance(message_text, list):
        if message_text:
            first = message_text[0]
            if isinstance(first, dict):
                input_message_content = first.get("input_message_content") if isinstance(first.get("input_message_content"), dict) else {}
                if "message_text" in input_message_content:
                    message_text = str(input_message_content.get("message_text") or "")
                elif "rich_message" in input_message_content:
                    message_text = str(input_message_content.get("rich_message", {}).get("markdown") or "")
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
        self._session = requests.Session()

    def call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: int | tuple[int, int] | None = None,
    ) -> Any:
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

    def get_updates(self, offset: int | None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": TELEGRAM_BOT_POLL_TIMEOUT_SECONDS,
            "limit": 25,
            "allowed_updates": [
                "message",
                "guest_message",
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
                    "rich_message": {"markdown": markdown},
                },
            )
            return True
        except TelegramAPIError:
            plain = _THINK_RE.sub("", markdown).strip()
            try:
                self.call(
                    "sendMessageDraft",
                    {"chat_id": chat_id, "draft_id": draft_id, "text": plain[:4096]},
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


def _visible_answer(value: str) -> str:
    without_thoughts = _THINK_RE.sub("", str(value or ""))
    return _UNSUPPORTED_TOOL_BLOCK_RE.sub("", without_thoughts).strip()


def _trim_inline_answer(value: str) -> str:
    answer = value.strip()
    if len(answer) <= _MAX_INLINE_ANSWER_CHARS:
        return answer
    shortened = answer[: _MAX_INLINE_ANSWER_CHARS - 1].rstrip()
    boundary = max(shortened.rfind(". "), shortened.rfind("! "), shortened.rfind("? "))
    if boundary > _MAX_INLINE_ANSWER_CHARS // 2:
        shortened = shortened[: boundary + 1]
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
    on_progress: Callable[[str, bool, str], None] | None = None,
) -> str:
    if session_chat:
        existing = _existing_delivery(session_chat.session_id, linked.user.id, request_id)
        if existing is not None:
            return existing

    start_at = time.perf_counter()
    thinking_level = _telegram_thinking_level(source)
    max_context_messages = _telegram_context_limit(source)
    history_is_canonical = _telegram_use_canonical_history(source)
    history = load_chat_history(session_chat.session_id, linked.user.id) if session_chat else []

    user_data: dict[str, Any] = {
        "message": question,
        "history": history[-max_context_messages:] if history else [],
        "history_is_canonical": history_is_canonical,
        "request_id": request_id,
        "files": [],
        "privacy": {"service_improvement_opt_in": False},
        "webSearch": False,
        "autoWebSearch": False,
        "toolsEnabled": False,
        "thinkingLevel": thinking_level,
        "telegram_context": _telegram_context(linked, source, chat_payload, brief=brief),
        "meta": {
            "platform_type": "Telegram",
            "device_type": source,
            "interface_language": linked.language,
        },
    }
    model_func = get_model_function(DEFAULT_MODEL_ID)
    if not model_func:
        raise RuntimeError("Default model is unavailable")

    reply_chunks: list[str] = []
    internal_chunks: list[str] = []
    thought_summary_chunks: list[str] = []
    thinking_active = False
    try:
        for chunk in model_func(linked.user.id, user_data):
            if isinstance(chunk, dict):
                if "thinking_update" in chunk:
                    update = chunk.get("thinking_update")
                    thinking_active = isinstance(update, dict) and update.get("status") != "complete"
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
                if "reply_part" in chunk:
                    reply_chunks.append(str(chunk.get("reply_part") or ""))
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
        logger.exception(
            "Telegram answer generation failed: user_id=%s source=%s request_id=%s",
            linked.user.id,
            source,
            request_id,
        )
        raise

    raw_reply = "".join(reply_chunks)
    answer = _visible_answer(raw_reply)
    if brief:
        answer = _trim_inline_answer(answer)
    if not answer:
        raise RuntimeError("Model returned an empty Telegram answer")

    if persist and session_chat:
        graph = load_chat_graph(session_chat.session_id, linked.user.id)
        history_context, parent_message_id = conversation_context_for_operation(graph, "send", None)
        del history_context
        user_message = normalize_message(
            {
                "id": f"tg_u_{request_id}"[:120],
                "role": "user",
                "parts": [{"text": question}],
                "request_id": request_id,
                "source": source,
            }
        )
        model_message = normalize_message(
            {
                "id": f"tg_a_{request_id}"[:120],
                "role": "model",
                "parts": [{"text": "".join(internal_chunks) + answer}],
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


def _inline_answer_payload(text: str, *, force_plain: bool = False) -> dict[str, Any]:
    normalized = (text or "").strip()
    if not normalized:
        normalized = telegram_text("en", "generation_failed")
    visible = _trim_inline_answer(normalized)
    if force_plain:
        return {"message_text": visible[:_INLINE_RESULT_TEXT_CHARS]}
    # Telegram inline results require plain sendable payload in answerInlineQuery.
    # Use rich payload only as optional enhancement path, keep plain as primary.
    return {"message_text": visible[:_INLINE_RESULT_TEXT_CHARS]}


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
    except TelegramAPIError as exc:
        if base_payload.get("button"):
            # Older payload can fail with unknown field name.
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
        return "telegram_private", "private"
    return "telegram_group", f"{chat.get('id')}:{thread_id}"


def _is_addressed_to_bot(message: dict[str, Any], bot_username: str, bot_id: int) -> bool:
    chat = _as_dict(message.get("chat"))
    if chat.get("type") == "private":
        return True
    text = str(message.get("text") or "")
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
        api.send_text(chat_id, telegram_text(language, "settings"))
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
    text = str(message.get("text") or "").strip()
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
    if not text:
        api.send_text(
            chat_id,
            telegram_text(language, "unsupported_message"),
            reply_to_message_id=message_id,
        )
        return
    question = _clean_group_question(text, bot_username)[:_MAX_INPUT_CHARS]
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
            on_progress=progress,
        )
    except Exception:
        logger.exception("Telegram message generation failed for update_id=%s", update_id)
        api.send_text(
            chat_id,
            telegram_text(language, "generation_failed"),
            reply_to_message_id=message_id,
        )
        return
    _send_answer(api, chat_id, answer, reply_to_message_id=message_id)


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
        result = {
            "type": "article",
            "id": secrets.token_hex(8),
            "title": telegram_text(language, "inline_result_title"),
            "input_message_content": _inline_answer_payload(answer),
        }
    except Exception:
        logger.exception("Telegram guest generation failed for update_id=%s", update_id)
        result = {
            "type": "article",
            "id": secrets.token_hex(8),
            "title": telegram_text(language, "inline_result_title"),
            "input_message_content": {"message_text": telegram_text(language, "generation_failed")},
        }
    api.call("answerGuestQuery", {"guest_query_id": query_id, "result": result})


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
    commands = [
        {"command": command, "description": telegram_text("en", f"command_{command}")}
        for command in ("start", "new", "reset", "stop", "clear", "help", "settings")
    ]
    api.call("setMyCommands", {"commands": commands, "language_code": "en"})
    api.call(
        "setMyCommands",
        {
            "commands": [
                {"command": command, "description": telegram_text("ru", f"command_{command}")}
                for command in ("start", "new", "reset", "stop", "clear", "help", "settings")
            ],
            "language_code": "ru",
        },
    )
    if me.get("supports_inline_queries") is not True:
        logger.warning("Telegram inline mode is not enabled in BotFather")
    if me.get("supports_guest_queries") is not True:
        logger.warning("Telegram Guest Mode is not enabled in BotFather")
    return bot_id, username


def dispatch_update(
    api: TelegramBotAPI,
    update: dict[str, Any],
    *,
    bot_id: int,
    bot_username: str,
) -> None:
    update_id = int(update.get("update_id") or 0)
    if isinstance(update.get("message"), dict):
        handle_message_update(
            api,
            update["message"],
            update_id=update_id,
            bot_username=bot_username,
            bot_id=bot_id,
        )
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
    logger.info("Telegram bot worker started for @%s", bot_username)
    offset: int | None = None
    last_prune_at = 0.0
    failure_delay = 1.0
    while True:
        try:
            updates = api.get_updates(offset)
            failure_delay = 1.0
            for update in updates:
                update_id = int(update.get("update_id") or 0)
                try:
                    with app.app_context():
                        dispatch_update(
                            api,
                            update,
                            bot_id=bot_id,
                            bot_username=bot_username,
                        )
                except Exception:
                    logger.exception("Telegram update failed: update_id=%s", update_id)
                finally:
                    offset = max(offset or 0, update_id + 1)
            if time.monotonic() - last_prune_at > 3600:
                with app.app_context():
                    _prune_inline_results()
                last_prune_at = time.monotonic()
        except TelegramAPIError as exc:
            logger.warning(
                "Telegram polling failed in %s with code %s; retrying",
                exc.method,
                exc.error_code,
            )
            time.sleep(failure_delay)
            failure_delay = min(30.0, failure_delay * 2)
