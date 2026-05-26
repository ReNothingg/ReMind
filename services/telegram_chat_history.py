from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import TELEGRAM_CHATS_FOLDER
from services.chat_history import normalize_message

INDEX_FILENAME = "index.json"
DEFAULT_SESSION_TITLE = "Новый чат"


@dataclass(frozen=True, slots=True)
class TelegramUserProfile:
    telegram_id: int
    is_premium: bool = False
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    language_code: str = "ru"

    @property
    def display_name(self) -> str:
        full_name = " ".join(part for part in [self.first_name, self.last_name] if part).strip()
        if full_name:
            return full_name
        if self.username:
            return self.username
        return str(self.telegram_id)


@dataclass(frozen=True, slots=True)
class TelegramSessionSummary:
    session_id: str
    title: str
    created_at: float
    updated_at: float
    preview: str


class TelegramChatHistoryStore:
    def __init__(self, base_folder: Path | None = None) -> None:
        self.base_folder = Path(base_folder or TELEGRAM_CHATS_FOLDER)
        self.base_folder.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def get_or_create_active_session(self, profile: TelegramUserProfile) -> TelegramSessionSummary:
        index_data = self._read_index(profile.telegram_id)
        active_session_id = str(index_data.get("active_session_id") or "").strip()
        if active_session_id:
            session = self.get_session(profile.telegram_id, active_session_id)
            if session is not None:
                return session
        return self.create_session(profile)

    def create_session(self, profile: TelegramUserProfile) -> TelegramSessionSummary:
        session_id = f"s_{uuid.uuid4().hex[:20]}"
        now = time.time()
        payload = {
            "session_id": session_id,
            "telegram_id": profile.telegram_id,
            "title": DEFAULT_SESSION_TITLE,
            "created_at": now,
            "updated_at": now,
            "history": [],
        }
        with self._session_lock(profile.telegram_id):
            self._write_session(profile.telegram_id, session_id, payload)
            index_data = self._read_index(profile.telegram_id)
            sessions = [item for item in self._normalize_index_sessions(index_data) if item["session_id"] != session_id]
            sessions.insert(
                0,
                {
                    "session_id": session_id,
                    "title": DEFAULT_SESSION_TITLE,
                    "created_at": now,
                    "updated_at": now,
                    "preview": "",
                },
            )
            self._write_index(
                profile.telegram_id,
                {
                    "active_session_id": session_id,
                    "sessions": sessions,
                },
            )
        return TelegramSessionSummary(
            session_id=session_id,
            title=DEFAULT_SESSION_TITLE,
            created_at=now,
            updated_at=now,
            preview="",
        )

    def switch_active_session(
        self, telegram_id: int, session_id: str
    ) -> TelegramSessionSummary | None:
        with self._session_lock(telegram_id):
            payload = self._read_session(telegram_id, session_id)
            if not payload:
                return None

            now = time.time()
            payload["updated_at"] = now
            self._write_session(telegram_id, session_id, payload)

            index_data = self._read_index(telegram_id)
            sessions = [
                item
                for item in self._normalize_index_sessions(index_data)
                if item["session_id"] != session_id
            ]
            sessions.insert(
                0,
                {
                    "session_id": session_id,
                    "title": str(payload.get("title") or DEFAULT_SESSION_TITLE).strip()
                    or DEFAULT_SESSION_TITLE,
                    "created_at": float(payload.get("created_at") or now),
                    "updated_at": now,
                    "preview": self._preview_from_history(payload.get("history", [])),
                },
            )
            self._write_index(
                telegram_id,
                {
                    "active_session_id": session_id,
                    "sessions": sessions,
                },
            )
        return self._payload_to_summary(payload)

    def get_session(self, telegram_id: int, session_id: str) -> TelegramSessionSummary | None:
        payload = self._read_session(telegram_id, session_id)
        if not payload:
            return None
        return self._payload_to_summary(payload)

    def list_sessions(self, telegram_id: int, limit: int = 8) -> list[TelegramSessionSummary]:
        index_data = self._read_index(telegram_id)
        sessions = [
            TelegramSessionSummary(
                session_id=item["session_id"],
                title=item["title"],
                created_at=item["created_at"],
                updated_at=item["updated_at"],
                preview=item["preview"],
            )
            for item in self._normalize_index_sessions(index_data)
        ]
        sessions.sort(key=lambda item: item.updated_at, reverse=True)
        return sessions[:limit]

    def get_active_session_id(self, telegram_id: int) -> str | None:
        index_data = self._read_index(telegram_id)
        active_session_id = str(index_data.get("active_session_id") or "").strip()
        return active_session_id or None

    def load_history(self, telegram_id: int, session_id: str) -> list[dict[str, Any]]:
        payload = self._read_session(telegram_id, session_id)
        history = payload.get("history", []) if isinstance(payload, dict) else []
        normalized: list[dict[str, Any]] = []
        for item in history:
            normalized.append(normalize_message(item))
        return normalized

    def append_exchange(
        self,
        profile: TelegramUserProfile,
        session_id: str,
        user_text: str,
        reply_text: str,
        model_name: str,
    ) -> TelegramSessionSummary:
        now = time.time()
        with self._session_lock(profile.telegram_id):
            payload = self._read_session(profile.telegram_id, session_id)
            if not payload:
                payload = {
                    "session_id": session_id,
                    "telegram_id": profile.telegram_id,
                    "title": DEFAULT_SESSION_TITLE,
                    "created_at": now,
                    "updated_at": now,
                    "history": [],
                }

            history = payload.get("history", [])
            history.extend(
                [
                    normalize_message({"role": "user", "parts": [{"text": user_text.strip()}]}),
                    normalize_message({"role": "model", "parts": [{"text": reply_text.strip()}]}),
                ]
            )

            title = self._resolve_title(history) or payload.get("title") or DEFAULT_SESSION_TITLE
            payload.update(
                {
                    "title": title,
                    "updated_at": now,
                    "model": model_name,
                    "history": history,
                }
            )
            self._write_session(profile.telegram_id, session_id, payload)

            index_data = self._read_index(profile.telegram_id)
            sessions = [
                item
                for item in self._normalize_index_sessions(index_data)
                if item["session_id"] != session_id
            ]
            sessions.insert(
                0,
                {
                    "session_id": session_id,
                    "title": title,
                    "created_at": float(payload.get("created_at") or now),
                    "updated_at": now,
                    "preview": self._preview_from_history(history),
                },
            )
            self._write_index(
                profile.telegram_id,
                {
                    "active_session_id": session_id,
                    "sessions": sessions,
                },
            )

        return TelegramSessionSummary(
            session_id=session_id,
            title=title,
            created_at=float(payload.get("created_at") or now),
            updated_at=now,
            preview=self._preview_from_history(history),
        )

    def _user_folder(self, telegram_id: int) -> Path:
        folder = self.base_folder / str(int(telegram_id))
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _index_path(self, telegram_id: int) -> Path:
        return self._user_folder(telegram_id) / INDEX_FILENAME

    def _session_path(self, telegram_id: int, session_id: str) -> Path:
        safe_session_id = "".join(ch for ch in str(session_id) if ch.isalnum() or ch in "-_").strip()
        if not safe_session_id:
            raise ValueError("Invalid session_id")
        return self._user_folder(telegram_id) / f"{safe_session_id}.json"

    def _session_lock(self, telegram_id: int) -> threading.Lock:
        key = str(int(telegram_id))
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)

    def _read_index(self, telegram_id: int) -> dict[str, Any]:
        return self._read_json(self._index_path(telegram_id))

    def _write_index(self, telegram_id: int, payload: dict[str, Any]) -> None:
        self._write_json(self._index_path(telegram_id), payload)

    def _read_session(self, telegram_id: int, session_id: str) -> dict[str, Any]:
        try:
            return self._read_json(self._session_path(telegram_id, session_id))
        except ValueError:
            return {}

    def _write_session(self, telegram_id: int, session_id: str, payload: dict[str, Any]) -> None:
        self._write_json(self._session_path(telegram_id, session_id), payload)

    def _normalize_index_sessions(self, index_data: dict[str, Any]) -> list[dict[str, Any]]:
        raw_sessions = index_data.get("sessions", []) if isinstance(index_data, dict) else []
        normalized: list[dict[str, Any]] = []
        for item in raw_sessions:
            if not isinstance(item, dict):
                continue
            session_id = str(item.get("session_id") or "").strip()
            if not session_id:
                continue
            normalized.append(
                {
                    "session_id": session_id,
                    "title": str(item.get("title") or DEFAULT_SESSION_TITLE).strip()
                    or DEFAULT_SESSION_TITLE,
                    "created_at": float(item.get("created_at") or 0.0),
                    "updated_at": float(item.get("updated_at") or 0.0),
                    "preview": str(item.get("preview") or "").strip(),
                }
            )
        return normalized

    def _payload_to_summary(self, payload: dict[str, Any]) -> TelegramSessionSummary:
        history = payload.get("history", [])
        return TelegramSessionSummary(
            session_id=str(payload.get("session_id") or ""),
            title=str(payload.get("title") or DEFAULT_SESSION_TITLE).strip() or DEFAULT_SESSION_TITLE,
            created_at=float(payload.get("created_at") or 0.0),
            updated_at=float(payload.get("updated_at") or 0.0),
            preview=self._preview_from_history(history),
        )

    def _resolve_title(self, history: list[dict[str, Any]]) -> str:
        for message in history:
            if message.get("role") != "user":
                continue
            parts = message.get("parts", [])
            for part in parts:
                if isinstance(part, dict) and part.get("text"):
                    text = " ".join(str(part["text"]).split()).strip()
                    if text:
                        return text[:57] + "..." if len(text) > 60 else text
        return DEFAULT_SESSION_TITLE

    def _preview_from_history(self, history: list[dict[str, Any]]) -> str:
        for message in reversed(history):
            if message.get("role") != "model":
                continue
            for part in message.get("parts", []):
                if isinstance(part, dict) and part.get("text"):
                    text = " ".join(str(part["text"]).split()).strip()
                    if text:
                        return text[:77] + "..." if len(text) > 80 else text
        return ""
