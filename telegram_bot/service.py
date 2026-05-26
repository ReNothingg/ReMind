from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from aiogram.types import User as TelegramApiUser
from flask import Flask

from ai_engine import get_model_function
from config import DEFAULT_LANGUAGE, TELEGRAM_BOT_DEFAULT_MODEL
from services.telegram_chat_history import (
    TelegramChatHistoryStore,
    TelegramSessionSummary,
    TelegramUserProfile,
)


class TelegramChatService:
    def __init__(
        self,
        flask_app: Flask,
        session_store: TelegramChatHistoryStore | None = None,
        model_name: str | None = None,
    ) -> None:
        self.flask_app = flask_app
        self.session_store = session_store or TelegramChatHistoryStore()
        self.model_name = (model_name or TELEGRAM_BOT_DEFAULT_MODEL or "gemini").strip() or "gemini"
        self._generation_locks: dict[int, asyncio.Lock] = {}
        self._generation_locks_guard = threading.Lock()

    def build_profile(self, user: TelegramApiUser) -> TelegramUserProfile:
        return TelegramUserProfile(
            telegram_id=user.id,
            is_premium=bool(getattr(user, "is_premium", False)),
            username=str(getattr(user, "username", "") or ""),
            first_name=str(getattr(user, "first_name", "") or ""),
            last_name=str(getattr(user, "last_name", "") or ""),
            language_code=self._normalize_language(getattr(user, "language_code", "") or ""),
        )

    def get_generation_lock(self, telegram_id: int) -> asyncio.Lock:
        with self._generation_locks_guard:
            lock = self._generation_locks.get(telegram_id)
            if lock is None:
                lock = asyncio.Lock()
                self._generation_locks[telegram_id] = lock
            return lock

    def get_or_create_active_session(self, profile: TelegramUserProfile) -> TelegramSessionSummary:
        return self.session_store.get_or_create_active_session(profile)

    def create_new_session(self, profile: TelegramUserProfile) -> TelegramSessionSummary:
        return self.session_store.create_session(profile)

    def list_sessions(self, telegram_id: int, limit: int = 8) -> list[TelegramSessionSummary]:
        return self.session_store.list_sessions(telegram_id, limit=limit)

    def get_active_session_id(self, telegram_id: int) -> str | None:
        return self.session_store.get_active_session_id(telegram_id)

    def switch_session(
        self, telegram_id: int, session_id: str
    ) -> TelegramSessionSummary | None:
        return self.session_store.switch_active_session(telegram_id, session_id)

    async def stream_chat(
        self,
        profile: TelegramUserProfile,
        text: str,
        session_id: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        session = (
            self.session_store.get_or_create_active_session(profile)
            if not session_id
            else self.session_store.switch_active_session(profile.telegram_id, session_id)
        )
        if session is None:
            session = self.session_store.create_session(profile)

        history = self.session_store.load_history(profile.telegram_id, session.session_id)
        user_data = {
            "message": text,
            "history": history,
            "files": [],
            "meta": self._build_meta(profile, history),
        }

        model_func = get_model_function(self.model_name)
        if not model_func:
            raise RuntimeError(f"Model '{self.model_name}' not supported.")

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        def push(kind: str, payload: Any) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))

        def worker() -> None:
            try:
                with self.flask_app.app_context():
                    model_output = model_func(None, user_data)
                    if inspect.isgenerator(model_output):
                        for chunk in model_output:
                            push("chunk", chunk)
                    else:
                        push("chunk", model_output)
            except Exception as exc:
                push("error", exc)
            finally:
                push("done", None)

        threading.Thread(target=worker, daemon=True).start()

        full_reply = ""
        final_data: dict[str, Any] = {}

        while True:
            kind, payload = await queue.get()
            if kind == "chunk":
                full_reply, final_data, yielded = self._consume_model_payload(
                    payload, full_reply, final_data
                )
                if yielded:
                    yield yielded
                continue

            if kind == "error":
                raise payload

            if kind == "done":
                break

        final_reply = str(final_data.get("reply") or full_reply or "").strip()
        final_data["reply"] = final_reply
        saved_session = self.session_store.append_exchange(
            profile=profile,
            session_id=session.session_id,
            user_text=text,
            reply_text=final_reply,
            model_name=self.model_name,
        )
        yield {
            "final": True,
            **final_data,
            "session_id": saved_session.session_id,
            "session_title": saved_session.title,
        }

    def _build_meta(self, profile: TelegramUserProfile, history: list[dict[str, Any]]) -> dict[str, Any]:
        full_name = " ".join(part for part in [profile.first_name, profile.last_name] if part).strip()
        return {
            "interface_language": profile.language_code or DEFAULT_LANGUAGE,
            "platform_type": "Telegram Bot",
            "device_type": "telegram_bot",
            "theme": "telegram",
            "user_agent": "Telegram Bot API",
            "local_hour": datetime.utcnow().hour,
            "avg_conversation_depth": len(history),
            "avg_message_length": self._average_message_length(history),
            "telegram_id": str(profile.telegram_id),
            "telegram_is_premium": profile.is_premium,
            "telegram_username": profile.username,
            "telegram_first_name": profile.first_name,
            "telegram_last_name": profile.last_name,
            "telegram_full_name": full_name,
            "personalization_nickname": full_name or profile.username or profile.first_name,
        }

    def _consume_model_payload(
        self,
        payload: Any,
        full_reply: str,
        final_data: dict[str, Any],
    ) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
        if isinstance(payload, dict):
            if "reply_part" in payload:
                reply_part = str(payload.get("reply_part") or "")
                updated_full_reply = full_reply + reply_part
                updated_final_data = {**final_data, **{k: v for k, v in payload.items() if k != "reply_part"}}
                return updated_full_reply, updated_final_data, {"reply_part": reply_part}

            if "reply" in payload:
                reply_text = str(payload.get("reply") or "")
                updated_final_data = {**final_data, **payload}
                return full_reply + reply_text, updated_final_data, None

            updated_final_data = {**final_data, **payload}
            return full_reply, updated_final_data, payload if payload else None

        reply_part = str(payload)
        return full_reply + reply_part, final_data, {"reply_part": reply_part}

    def _average_message_length(self, history: list[dict[str, Any]]) -> int:
        lengths: list[int] = []
        for message in history:
            text_parts: list[str] = []
            for part in message.get("parts", []):
                if isinstance(part, dict) and part.get("text"):
                    text_parts.append(str(part["text"]))
            if text_parts:
                lengths.append(len(" ".join(text_parts)))
        if not lengths:
            return 0
        return int(sum(lengths) / len(lengths))

    def _normalize_language(self, language_code: str) -> str:
        normalized = str(language_code or "").strip().lower()
        if not normalized:
            return DEFAULT_LANGUAGE
        if "-" in normalized:
            normalized = normalized.split("-", maxsplit=1)[0]
        return normalized or DEFAULT_LANGUAGE
