from __future__ import annotations

import json
import re
import time
from datetime import datetime

from flask import jsonify, request, session

from routes.api_errors import api_error_boundary, require_authenticated_user_id
from utils.auth import UserSettings, db
from utils.rate_limiting import RateLimiter, rate_limit

DRAFT_MAX_CHARS = 20_000
DRAFT_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
draft_save_limiter = RateLimiter(max_requests=600, time_window=3600, namespace="chat_draft")


def _load_settings(user_id: int, *, create: bool = False) -> UserSettings | None:
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if settings is None and create:
        settings = UserSettings(user_id=user_id)
        db.session.add(settings)
    return settings


def _favorite_ids(state: dict) -> list[str]:
    raw_favorites = state.get("favoriteChats", [])
    if not isinstance(raw_favorites, list):
        return []
    return [item for item in raw_favorites if isinstance(item, str) and item]


def _validated_session_id(payload: object) -> str:
    if not isinstance(payload, dict):
        raise ValueError("session_id required")
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        raise ValueError("session_id required")
    if len(session_id) > 200:
        raise ValueError("session_id too long")
    return session_id


def _save_user_state(settings: UserSettings, state: dict) -> None:
    settings.settings_data = json.dumps(state, ensure_ascii=False)
    settings.updated_at = datetime.utcnow()
    db.session.commit()


def register_user_state_routes(api_bp):
    @api_bp.route("/api/user/draft", methods=["GET"])
    @api_error_boundary("draft_load_failed")
    def get_chat_draft():
        user_id = require_authenticated_user_id()
        settings = _load_settings(user_id)
        state = settings.get_settings() if settings else {}
        draft = state.get("chatDraft")
        return jsonify({"draft": draft if isinstance(draft, dict) else None}), 200

    @api_bp.route("/api/user/draft", methods=["PUT"])
    @rate_limit(draft_save_limiter, "Too many draft updates. Please wait.")
    @api_error_boundary("draft_save_failed")
    def save_chat_draft():
        user_id = require_authenticated_user_id()
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "invalid_draft"}), 400
        content = payload.get("content", "")
        session_id = payload.get("session_id")
        device_id = payload.get("device_id")
        base_revision = payload.get("base_revision")

        if not isinstance(content, str) or len(content) > DRAFT_MAX_CHARS:
            return jsonify({"error": "invalid_draft"}), 400
        if session_id is not None and (
            not isinstance(session_id, str) or not DRAFT_SESSION_ID_RE.fullmatch(session_id)
        ):
            return jsonify({"error": "invalid_session_id"}), 400
        if not isinstance(device_id, str) or not device_id.strip() or len(device_id) > 100:
            return jsonify({"error": "invalid_device_id"}), 400
        if base_revision is not None and (
            not isinstance(base_revision, int)
            or isinstance(base_revision, bool)
            or base_revision < 0
        ):
            return jsonify({"error": "invalid_revision"}), 400

        settings = UserSettings.query.filter_by(user_id=user_id).with_for_update().first()
        if settings is None:
            settings = UserSettings(user_id=user_id)
            db.session.add(settings)
        state = settings.get_settings()
        current = state.get("chatDraft") if isinstance(state.get("chatDraft"), dict) else None
        raw_current_revision = current.get("revision", 0) if current else 0
        current_revision = (
            raw_current_revision
            if isinstance(raw_current_revision, int)
            and not isinstance(raw_current_revision, bool)
            and raw_current_revision >= 0
            else 0
        )
        if base_revision is not None and base_revision != current_revision:
            return jsonify({"error": "draft_conflict", "draft": current}), 409

        draft = {
            "content": content,
            "session_id": session_id,
            "device_id": device_id.strip()[:100],
            "revision": current_revision + 1,
            "updated_at": int(time.time() * 1000),
        }
        state["chatDraft"] = draft
        _save_user_state(settings, state)
        return jsonify({"draft": draft}), 200

    @api_bp.route("/api/user/draft", methods=["DELETE"])
    @api_error_boundary("draft_delete_failed")
    def delete_chat_draft():
        user_id = require_authenticated_user_id()
        settings = UserSettings.query.filter_by(user_id=user_id).with_for_update().first()
        if settings is None:
            return jsonify({"deleted": True}), 200
        state = settings.get_settings()
        state.pop("chatDraft", None)
        _save_user_state(settings, state)
        return jsonify({"deleted": True}), 200

    @api_bp.route("/api/user/favorites", methods=["GET"])
    @api_error_boundary("favorites_load_failed")
    def get_favorites():
        raw_user_id = session.get("user_id")
        if not isinstance(raw_user_id, int):
            return jsonify({"favorites": []}), 200

        settings = _load_settings(raw_user_id)
        favorites = _favorite_ids(settings.get_settings()) if settings else []
        return jsonify({"favorites": favorites}), 200

    @api_bp.route("/api/user/favorites", methods=["POST"])
    @api_error_boundary("favorite_add_failed")
    def add_favorite():
        try:
            session_id = _validated_session_id(request.get_json(silent=True) or {})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        settings = _load_settings(require_authenticated_user_id(), create=True)
        assert settings is not None
        state = settings.get_settings()
        favorites = _favorite_ids(state)
        if session_id not in favorites:
            favorites.append(session_id)
            state["favoriteChats"] = favorites
            _save_user_state(settings, state)
        return jsonify({"favorites": favorites}), 200

    @api_bp.route("/api/user/favorites", methods=["DELETE"])
    @api_error_boundary("favorite_remove_failed")
    def remove_favorite():
        try:
            session_id = _validated_session_id(request.get_json(silent=True) or {})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        settings = _load_settings(require_authenticated_user_id())
        if settings is None:
            return jsonify({"favorites": []}), 200

        state = settings.get_settings()
        favorites = _favorite_ids(state)
        if session_id in favorites:
            favorites.remove(session_id)
            state["favoriteChats"] = favorites
            _save_user_state(settings, state)
        return jsonify({"favorites": favorites}), 200

    @api_bp.route("/api/user/preferences", methods=["GET"])
    @api_error_boundary("preferences_load_failed")
    def get_preferences():
        raw_user_id = session.get("user_id")
        if not isinstance(raw_user_id, int):
            return jsonify({"preferences": {}}), 200

        settings = _load_settings(raw_user_id)
        state = settings.get_settings() if settings else {}
        return (
            jsonify(
                {
                    "preferences": {
                        "readingMode": state.get("readingMode", False),
                        "sessionSlugIndex": state.get("sessionSlugIndex", {}),
                    }
                }
            ),
            200,
        )

    @api_bp.route("/api/user/preferences", methods=["PUT"])
    @api_error_boundary("preferences_update_failed")
    def update_preferences():
        user_id = require_authenticated_user_id()
        payload = request.get_json(silent=True) or {}
        settings = _load_settings(user_id, create=True)
        assert settings is not None
        state = settings.get_settings()

        if "readingMode" in payload:
            state["readingMode"] = bool(payload["readingMode"])
        if "sessionSlugIndex" in payload:
            state["sessionSlugIndex"] = payload["sessionSlugIndex"]
        _save_user_state(settings, state)

        return (
            jsonify(
                {
                    "message": "Настройки сохранены",
                    "preferences": {
                        "readingMode": state.get("readingMode", False),
                        "sessionSlugIndex": state.get("sessionSlugIndex", {}),
                    },
                }
            ),
            200,
        )
