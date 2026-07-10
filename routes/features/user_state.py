from __future__ import annotations

import json
from datetime import datetime

from flask import jsonify, request, session

from routes.api_errors import api_error_boundary, require_authenticated_user_id
from utils.auth import UserSettings, db


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
