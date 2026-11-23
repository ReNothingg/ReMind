from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta

import jwt
from flask import (
    jsonify,
    request,
    session,
)
from sqlalchemy.exc import IntegrityError

from backend.auth.accounts import format_account_restriction_message, is_account_disabled
from backend.auth.apple import (
    APPLE_AUTH_CHALLENGE_TTL_SECONDS,
    APPLE_CHALLENGE_RE,
    APPLE_ID_TOKEN_MAX_LENGTH,
    AppleAuthError,
    _apple_display_name,
    _consume_apple_auth_challenge,
    _consume_apple_token_replay,
    _find_or_create_apple_user,
    _issue_apple_auth_challenge,
    _link_apple_identity,
    _verify_apple_identity_token,
)
from backend.auth.identities import AuthIdentityConflictError
from backend.auth.oauth import _decode_mobile_google_oauth_token
from backend.auth.telegram import (
    TELEGRAM_ID_TOKEN_MAX_LENGTH,
    TELEGRAM_LINK_REQUEST_ID_RE,
    TELEGRAM_LINK_TOKEN_TTL_SECONDS,
    TELEGRAM_LOGIN_NONCE_SESSION_KEY,
    _current_telegram_login_nonce,
    _find_or_create_telegram_user,
    _sync_telegram_identity,
    _telegram_link_token_hash,
    _verify_telegram_id_token,
)
from backend.db.models import TelegramLinkRequest, User, db
from backend.security.input_validation import InputValidator
from backend.security.rate_limiting import (
    login_limiter,
    rate_limit,
)


def register_providers_routes(app):
    @app.route("/api/auth/apple/nonce", methods=["GET"])
    @rate_limit(login_limiter, "Too many login attempts")
    def api_apple_nonce():
        from backend.config import APPLE_APP_BUNDLE_ID

        if not APPLE_APP_BUNDLE_ID:
            return jsonify({"error": "apple_unavailable", "code": "apple_unavailable"}), 503
        mode = request.args.get("mode", "login")
        if mode not in {"login", "link"}:
            return jsonify({"error": "invalid_request", "code": "invalid_request"}), 400

        link_user_id = None
        if mode == "link":
            raw_user_id = session.get("user_id")
            link_user = db.session.get(User, raw_user_id) if raw_user_id else None
            if not link_user:
                return jsonify({"error": "auth_required", "code": "auth_required"}), 401
            link_user_id = link_user.id
        try:
            challenge, raw_nonce = _issue_apple_auth_challenge(
                flow="native",
                mode=mode,
                link_user_id=link_user_id,
            )
        except Exception as exc:
            db.session.rollback()
            app.logger.error("Apple native challenge creation failed (%s)", type(exc).__name__)
            return (
                jsonify({"error": "apple_auth_unavailable", "code": "apple_auth_unavailable"}),
                503,
            )

        response = jsonify(
            {
                "challenge": challenge,
                "nonce": raw_nonce,
                "expires_in": APPLE_AUTH_CHALLENGE_TTL_SECONDS,
            }
        )
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response, 200

    @app.route("/api/auth/apple", methods=["POST"])
    @rate_limit(login_limiter, "Too many login attempts")
    def api_apple_login():
        from backend.config import APPLE_APP_BUNDLE_ID
        from backend.security.session_security import regenerate_session

        if not APPLE_APP_BUNDLE_ID:
            return jsonify({"error": "apple_unavailable", "code": "apple_unavailable"}), 503
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "invalid_request", "code": "invalid_request"}), 400
        identity_token = data.get("identity_token")
        challenge = data.get("challenge")
        if (
            not isinstance(identity_token, str)
            or not identity_token
            or len(identity_token) > APPLE_ID_TOKEN_MAX_LENGTH
            or not isinstance(challenge, str)
            or not APPLE_CHALLENGE_RE.fullmatch(challenge)
        ):
            return jsonify({"error": "invalid_request", "code": "invalid_request"}), 400

        try:
            metadata = _consume_apple_auth_challenge(challenge, flow="native")
            if metadata["mode"] == "link":
                current_user_id = session.get("user_id")
                if current_user_id != metadata["link_user_id"]:
                    raise AppleAuthError("auth_required")
            claims = _verify_apple_identity_token(
                identity_token,
                audience=APPLE_APP_BUNDLE_ID,
                expected_nonce_hash=metadata["nonce_hash"],
            )
            _consume_apple_token_replay(identity_token, claims)
            display_name = _apple_display_name(data.get("name"))

            if metadata["mode"] == "link":
                user = db.session.get(User, metadata["link_user_id"])
                if not user or is_account_disabled(user):
                    raise AppleAuthError("auth_required")
                _link_apple_identity(user, claims)
                return jsonify({"message": "apple_linked", "user": user.to_dict()}), 200

            user = _find_or_create_apple_user(claims, display_name)
        except AuthIdentityConflictError as exc:
            db.session.rollback()
            code = "email_in_use" if str(exc) == "email_in_use" else "auth_identity_in_use"
            return jsonify({"error": code, "code": code}), 409
        except AppleAuthError as exc:
            db.session.rollback()
            code = (
                str(exc)
                if str(exc)
                in {
                    "apple_email_required",
                    "auth_required",
                    "invalid_or_expired_challenge",
                }
                else "apple_auth_failed"
            )
            status = 401 if code in {"auth_required", "invalid_or_expired_challenge"} else 400
            return jsonify({"error": code, "code": code}), status
        except (jwt.PyJWTError, IntegrityError) as exc:
            db.session.rollback()
            app.logger.warning("Apple native authentication rejected (%s)", type(exc).__name__)
            return jsonify({"error": "apple_auth_failed", "code": "apple_auth_failed"}), 401
        except Exception as exc:
            db.session.rollback()
            app.logger.error("Apple native authentication failed (%s)", type(exc).__name__)
            return (
                jsonify({"error": "apple_auth_unavailable", "code": "apple_auth_unavailable"}),
                503,
            )

        if is_account_disabled(user):
            return jsonify({"error": "account_disabled", "code": "account_disabled"}), 403
        session.clear()
        session["user_id"] = user.id
        session["username"] = InputValidator.sanitize_output(user.username)
        session["_auth_version"] = int(user.auth_version or 0)
        regenerate_session()
        session.permanent = True
        return jsonify({"message": "apple_authenticated", "user": user.to_dict()}), 200

    @app.route("/api/auth/telegram", methods=["POST"])
    @rate_limit(login_limiter, "Too many login attempts")
    def api_telegram_login():
        from backend.config import TELEGRAM_CLIENT_ID
        from backend.security.session_security import regenerate_session

        if not TELEGRAM_CLIENT_ID:
            return jsonify({"error": "telegram_unavailable", "code": "telegram_unavailable"}), 503

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "invalid_request", "code": "invalid_request"}), 400

        mode = data.get("mode", "login")
        if mode not in {"login", "link"}:
            return jsonify({"error": "invalid_request", "code": "invalid_request"}), 400
        link_user = None
        if mode == "link":
            link_user_id = session.get("user_id")
            link_user = db.session.get(User, link_user_id) if link_user_id else None
            if not link_user:
                return jsonify({"error": "auth_required", "code": "auth_required"}), 401

        id_token = data.get("id_token")
        if (
            not isinstance(id_token, str)
            or not id_token
            or len(id_token) > TELEGRAM_ID_TOKEN_MAX_LENGTH
        ):
            return jsonify({"error": "invalid_token", "code": "invalid_token"}), 400

        expected_nonce = _current_telegram_login_nonce()
        if not expected_nonce:
            return jsonify({"error": "nonce_expired", "code": "nonce_expired"}), 400

        try:
            claims = _verify_telegram_id_token(id_token, TELEGRAM_CLIENT_ID, expected_nonce)
            if link_user:
                _sync_telegram_identity(link_user, claims)
                db.session.commit()
                session.pop(TELEGRAM_LOGIN_NONCE_SESSION_KEY, None)
                return (
                    jsonify({"message": "telegram_linked", "user": link_user.to_dict()}),
                    200,
                )
            user = _find_or_create_telegram_user(claims)
        except AuthIdentityConflictError as exc:
            db.session.rollback()
            code = str(exc) or "auth_identity_in_use"
            return jsonify({"error": code, "code": code}), 409
        except IntegrityError:
            db.session.rollback()
            return (
                jsonify({"error": "auth_identity_in_use", "code": "auth_identity_in_use"}),
                409,
            )
        except jwt.PyJWTError as exc:
            app.logger.warning("Telegram ID token rejected (%s)", type(exc).__name__)
            return jsonify({"error": "telegram_auth_failed", "code": "telegram_auth_failed"}), 401
        except Exception as exc:
            db.session.rollback()
            app.logger.error("Telegram login failed (%s)", type(exc).__name__)
            return jsonify({"error": "telegram_auth_failed", "code": "telegram_auth_failed"}), 503

        if is_account_disabled(user):
            return jsonify({"error": "account_disabled", "code": "account_disabled"}), 403

        session.clear()
        session["user_id"] = user.id
        session["username"] = InputValidator.sanitize_output(user.username)
        session["_auth_version"] = int(user.auth_version or 0)
        regenerate_session()
        session.permanent = True

        return jsonify({"message": "telegram_authenticated", "user": user.to_dict()}), 200

    @app.route("/api/auth/telegram/link", methods=["POST"])
    @rate_limit(login_limiter, "Too many link attempts")
    def api_create_telegram_link():
        from backend.config import TELEGRAM_BOT_USERNAME

        user_id = session.get("user_id")
        user = db.session.get(User, user_id) if user_id else None
        if not user:
            return jsonify({"error": "auth_required", "code": "auth_required"}), 401
        bot_username = str(TELEGRAM_BOT_USERNAME or "").strip().lstrip("@")
        if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", bot_username):
            return jsonify({"error": "telegram_unavailable", "code": "telegram_unavailable"}), 503

        now = datetime.utcnow()
        TelegramLinkRequest.query.filter(
            TelegramLinkRequest.user_id == user.id,
            TelegramLinkRequest.consumed_at.is_(None),
            TelegramLinkRequest.expires_at > now,
        ).update({"expires_at": now}, synchronize_session=False)

        raw_token = secrets.token_urlsafe(24)
        request_id = secrets.token_urlsafe(18)
        link_request = TelegramLinkRequest(
            request_id=request_id,
            token_hash=_telegram_link_token_hash(raw_token),
            user_id=user.id,
            expires_at=now + timedelta(seconds=TELEGRAM_LINK_TOKEN_TTL_SECONDS),
        )
        db.session.add(link_request)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({"error": "telegram_link_failed", "code": "telegram_link_failed"}), 503

        return (
            jsonify(
                {
                    "url": f"https://t.me/{bot_username}?start=connect_{raw_token}",
                    "request_id": request_id,
                    "expires_in": TELEGRAM_LINK_TOKEN_TTL_SECONDS,
                }
            ),
            201,
        )

    @app.route("/api/auth/telegram/link/status", methods=["POST"])
    def api_telegram_link_status():
        user_id = session.get("user_id")
        user = db.session.get(User, user_id) if user_id else None
        if not user:
            return jsonify({"error": "auth_required", "code": "auth_required"}), 401
        data = request.get_json(silent=True)
        request_id = data.get("request_id") if isinstance(data, dict) else None
        if not isinstance(request_id, str) or not TELEGRAM_LINK_REQUEST_ID_RE.fullmatch(request_id):
            return jsonify({"error": "invalid_request", "code": "invalid_request"}), 400

        link_request = TelegramLinkRequest.query.filter_by(
            request_id=request_id, user_id=user.id
        ).first()
        if not link_request:
            return jsonify({"error": "not_found", "code": "not_found"}), 404
        if link_request.consumed_at is not None:
            if link_request.failure_code:
                return jsonify({"status": "failed", "code": link_request.failure_code}), 200
            return jsonify({"status": "linked", "user": user.to_dict()}), 200
        if link_request.expires_at <= datetime.utcnow():
            return jsonify({"status": "expired"}), 200
        return jsonify({"status": "pending"}), 200

    @app.route("/api/auth/mobile/google/complete", methods=["POST"])
    @rate_limit(login_limiter, "Too many login attempts")
    def api_mobile_google_complete():
        try:
            from backend.config import SECRET_KEY
            from backend.security.session_security import regenerate_session

            data = request.get_json(silent=True) or {}
            payload = _decode_mobile_google_oauth_token(SECRET_KEY, data.get("token", ""))
            if not payload:
                return jsonify({"error": "Неверный или истекший Google token"}), 401

            raw_user_id = payload.get("user_id")
            try:
                user_id = int(raw_user_id)
            except (TypeError, ValueError):
                return jsonify({"error": "Неверный Google token"}), 401

            user = db.session.get(User, user_id)
            if not user:
                return jsonify({"error": "Пользователь не найден"}), 404
            if is_account_disabled(user):
                return jsonify({"error": format_account_restriction_message(user)}), 403

            session.clear()
            session["user_id"] = user.id
            session["username"] = InputValidator.sanitize_output(user.username)
            session["_auth_version"] = int(user.auth_version or 0)
            regenerate_session()
            session.permanent = True

            return jsonify({"message": "Успешный вход через Google", "user": user.to_dict()}), 200
        except Exception as e:
            app.logger.exception(f"Mobile Google OAuth complete error: {e}")
            return jsonify({"error": "Ошибка при входе через Google"}), 500
