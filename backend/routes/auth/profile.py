from __future__ import annotations

import json
from datetime import datetime

from flask import (
    jsonify,
    request,
    session,
)
from sqlalchemy.exc import IntegrityError

from backend.auth.identities import _validate_unique_username
from backend.db.models import (
    REMOVED_SETTINGS_DATA_KEYS,
    User,
    UserSettings,
    db,
    sanitize_settings_data,
)
from backend.security.input_validation import InputValidator, ValidationError


def register_profile_routes(app):
    @app.route("/api/auth/profile", methods=["GET"])
    def api_get_profile():

        if "user_id" not in session:
            return jsonify({"error": "Не авторизирован"}), 401

        user = db.session.get(User, session["user_id"])
        if not user:
            return jsonify({"error": "Пользователь не найден"}), 404

        settings = UserSettings.query.filter_by(user_id=user.id).first()

        return (
            jsonify(
                {
                    "user": user.to_dict(),
                    "settings": settings.to_dict() if settings else None,
                }
            ),
            200,
        )

    @app.route("/api/auth/profile", methods=["PUT"])
    def api_update_profile():

        if "user_id" not in session:
            return jsonify({"error": "Не авторизирован"}), 401

        try:
            data = request.get_json(silent=True) or {}
            user = db.session.get(User, session["user_id"])

            if not user:
                return jsonify({"error": "Пользователь не найден"}), 404

            if "username" in data:
                user.username = _validate_unique_username(data["username"], exclude_user_id=user.id)
                session["username"] = InputValidator.sanitize_output(user.username)
            if "name" in data:
                raw_name = data.get("name")
                user.name = (
                    InputValidator.validate_name(raw_name)
                    if isinstance(raw_name, str) and raw_name.strip()
                    else None
                )

            db.session.commit()

            return jsonify({"message": "Профиль обновлен", "user": user.to_dict()}), 200

        except ValidationError as e:
            db.session.rollback()
            field = "username" if "Username" in str(e) else "name"
            return jsonify({"error": str(e), "field": field}), 400

        except Exception as e:
            db.session.rollback()
            app.logger.exception(f"API update profile error: {e}")
            return jsonify({"error": "Не удалось обновить профиль"}), 500

    @app.route("/api/auth/settings", methods=["GET"])
    def api_get_settings():

        if "user_id" not in session:
            return jsonify({"error": "Не авторизирован"}), 401

        settings = UserSettings.query.filter_by(user_id=session["user_id"]).first()
        if not settings:
            settings = UserSettings(user_id=session["user_id"])
            db.session.add(settings)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                settings = UserSettings.query.filter_by(user_id=session["user_id"]).first()
                if not settings:
                    raise

        return jsonify(settings.to_dict()), 200

    @app.route("/api/auth/settings", methods=["PUT"])
    def api_update_settings():

        if "user_id" not in session:
            return jsonify({"error": "Не авторизирован"}), 401

        try:
            data = request.get_json(silent=True) or {}
            db_user_id = session.get("user_id")
            if not db_user_id or not isinstance(db_user_id, int):
                return jsonify({"error": "Неверная сессия"}), 401

            settings = UserSettings.query.filter_by(user_id=db_user_id).first()

            if not settings:
                settings = UserSettings(user_id=db_user_id)
                db.session.add(settings)
            if "theme" in data:
                settings.theme = data["theme"]
            if "language" in data:
                settings.language = data["language"]
            if "automatic_web_search" in data:
                settings.automatic_web_search = bool(data["automatic_web_search"])
            if "settings_data" in data:
                sanitized_settings = sanitize_settings_data(data["settings_data"])
                settings.settings_data = json.dumps(sanitized_settings, ensure_ascii=False)
            elif data:
                current_settings = settings.get_settings()
                for key, value in data.items():
                    if (
                        key not in ["theme", "language", "automatic_web_search"]
                        and key not in REMOVED_SETTINGS_DATA_KEYS
                    ):
                        current_settings[key] = value
                settings.settings_data = json.dumps(current_settings, ensure_ascii=False)

            settings.updated_at = datetime.utcnow()
            db.session.commit()

            return (
                jsonify({"message": "Настройки сохранены", "settings": settings.to_dict()}),
                200,
            )

        except Exception as e:
            db.session.rollback()
            app.logger.exception(f"API update settings error: {e}")
            return jsonify({"error": "Не удалось обновить настройки"}), 500
