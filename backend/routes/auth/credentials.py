from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta

from flask import (
    jsonify,
    request,
    session,
    url_for,
)
from sqlalchemy import func
from werkzeug.security import generate_password_hash

from backend.auth.accounts import (
    format_account_restriction_message,
    is_account_disabled,
    is_telegram_placeholder_email,
)
from backend.auth.apple import _revoke_pending_apple_link_challenges
from backend.auth.credentials import (
    PASSWORD_RESET_CODE_MAX_ATTEMPTS,
    PASSWORD_RESET_CODE_RE,
    PASSWORD_RESET_CODE_TTL_SECONDS,
    PASSWORD_RESET_REQUEST_ID_RE,
    _password_reset_code_hash,
    _verify_user_password,
    verify_turnstile,
)
from backend.auth.identities import _validate_unique_username
from backend.db.models import PasswordResetChallenge, User, UserSettings, db
from backend.responses import make_error
from backend.security.input_validation import InputValidator, ValidationError
from backend.security.rate_limiting import (
    login_limiter,
    password_reset_limiter,
    password_reset_verify_limiter,
    rate_limit,
)
from backend.services.mailer import send_email


def register_credentials_routes(app):
    @app.route("/api/auth/register", methods=["POST"])
    @rate_limit(login_limiter, "Too many registration attempts")
    def api_register():

        try:
            data = request.get_json(silent=True) or {}
            username = data.get("username", "")
            name = data.get("name", "")
            email = data.get("email", "")
            password = data.get("password", "")
            from backend.config import TURNSTILE_SITE_KEY

            turnstile_token = data.get("turnstile_response") or data.get("cf-turnstile-response")
            if TURNSTILE_SITE_KEY and not verify_turnstile(turnstile_token):
                return jsonify({"error": "Ошибка проверки Cloudflare Turnstile"}), 400

            if not username or not email or not password:
                return jsonify({"error": "Все поля обязательны"}), 400

            try:
                username = _validate_unique_username(username)
                email = InputValidator.validate_email(email)
                InputValidator.validate_password(password)
                account_name = (
                    InputValidator.validate_name(name)
                    if isinstance(name, str) and name.strip()
                    else username
                )
            except ValidationError as e:
                message = str(e)
                field = "username"
                if message.startswith("Name "):
                    field = "name"
                elif message.startswith("Password "):
                    field = "password"
                elif "email" in message.lower():
                    field = "email"
                return jsonify({"error": message, "field": field}), 400

            user_exists = User.query.filter_by(email=email).first()
            if user_exists:
                return jsonify({"error": "Email уже зарегистрирован"}), 400
            try:
                from argon2 import PasswordHasher

                ph = PasswordHasher()
                hashed_password = ph.hash(password)
            except ImportError:
                hashed_password = generate_password_hash(password, method="pbkdf2:sha256")
            confirmation_token = secrets.token_urlsafe(32)
            confirmation_token_expires = datetime.utcnow() + timedelta(days=7)

            new_user = User(
                username=username,
                name=account_name,
                email=email,
                password=hashed_password,
                confirmation_token=confirmation_token,
                confirmation_token_expires=confirmation_token_expires,
            )

            db.session.add(new_user)
            db.session.commit()
            settings = UserSettings(user_id=new_user.id)
            db.session.add(settings)
            db.session.commit()
            confirmation_link = url_for("confirm_email", token=confirmation_token, _external=True)
            template_data = {
                "username": InputValidator.sanitize_output(username),
                "confirmation_link": confirmation_link,
            }

            email_sent = False
            try:
                email_sent = bool(
                    send_email(
                        to_email=email,
                        subject="Подтвердите вашу регистрацию",
                        body="",
                        template_name="confirmation",
                        template_data=template_data,
                    )
                )
            except Exception as e:
                app.logger.warning(f"Email sending error: {e}")

            if not email_sent:
                db.session.delete(settings)
                db.session.delete(new_user)
                db.session.commit()
                return (
                    jsonify(
                        {
                            "error": "confirmation_delivery_failed",
                            "code": "confirmation_delivery_failed",
                        }
                    ),
                    503,
                )

            return (
                jsonify(
                    {
                        "message": "Регистрация успешна! Проверьте email для подтверждения аккаунта",
                        "user_id": new_user.id,
                    }
                ),
                201,
            )

        except Exception as e:
            app.logger.exception(f"API registration error: {e}")
            return jsonify({"error": "Ошибка при регистрации"}), 500

    @app.route("/api/auth/password-reset/request", methods=["POST"])
    @rate_limit(password_reset_limiter, "Too many password reset requests")
    def api_password_reset_request():
        from backend.security.audit_log import AuditEvents, log_auth_event
        from backend.services.email_localization import password_reset_email_copy

        data = request.get_json(silent=True) or {}
        raw_email = data.get("email", "") if isinstance(data, dict) else ""
        language = data.get("language", "en") if isinstance(data, dict) else "en"
        reset_request_id = secrets.token_urlsafe(18)
        generic_payload = {
            "message": "password_reset_code_sent",
            "reset_request_id": reset_request_id,
            "expires_in": PASSWORD_RESET_CODE_TTL_SECONDS,
        }

        try:
            email = InputValidator.validate_email(str(raw_email).strip())
        except ValidationError:
            log_auth_event(AuditEvents.AUTH_PASSWORD_RESET_REQUEST, str(raw_email), True)
            return jsonify(generic_payload), 200

        user = User.query.filter(func.lower(User.email) == email.lower()).first()
        if not user or is_telegram_placeholder_email(user):
            log_auth_event(AuditEvents.AUTH_PASSWORD_RESET_REQUEST, email, True)
            return jsonify(generic_payload), 200

        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        recent_count = PasswordResetChallenge.query.filter(
            PasswordResetChallenge.user_id == user.id,
            PasswordResetChallenge.created_at >= one_hour_ago,
        ).count()
        if recent_count >= 3:
            log_auth_event(AuditEvents.AUTH_PASSWORD_RESET_REQUEST, email, True)
            return jsonify(generic_payload), 200

        now = datetime.utcnow()
        PasswordResetChallenge.query.filter_by(user_id=user.id, consumed_at=None).update(
            {"consumed_at": now},
            synchronize_session=False,
        )
        code = f"{secrets.randbelow(1_000_000):06d}"
        challenge = PasswordResetChallenge(
            request_id=reset_request_id,
            code_hash=_password_reset_code_hash(reset_request_id, code),
            user_id=user.id,
            expires_at=now + timedelta(seconds=PASSWORD_RESET_CODE_TTL_SECONDS),
        )
        db.session.add(challenge)
        db.session.commit()

        settings = UserSettings.query.filter_by(user_id=user.id).first()
        preferred_language = settings.language if settings and settings.language else language
        copy = password_reset_email_copy(
            preferred_language,
            InputValidator.sanitize_output(user.username),
        )
        email_sent = bool(
            send_email(
                to_email=user.email,
                subject=copy["subject"],
                body="",
                template_name="password_reset_code",
                template_data={
                    "heading": copy["heading"],
                    "greeting": copy["greeting"],
                    "intro": copy["intro"],
                    "code": code,
                    "expiry": copy["expiry"],
                    "ignore": copy["ignore"],
                },
            )
        )
        if not email_sent:
            db.session.delete(challenge)
            db.session.commit()

        log_auth_event(AuditEvents.AUTH_PASSWORD_RESET_REQUEST, email, True)
        return jsonify(generic_payload), 200

    @app.route("/api/auth/password-reset/complete", methods=["POST"])
    @rate_limit(password_reset_verify_limiter, "Too many password reset attempts")
    def api_password_reset_complete():
        from backend.security.audit_log import AuditEvents, log_audit_event, log_security_event
        from backend.services.email_localization import password_reset_email_copy

        data = request.get_json(silent=True) or {}
        reset_request_id = data.get("reset_request_id", "") if isinstance(data, dict) else ""
        code = data.get("code", "") if isinstance(data, dict) else ""
        password = data.get("password", "") if isinstance(data, dict) else ""
        request_valid = isinstance(reset_request_id, str) and bool(
            PASSWORD_RESET_REQUEST_ID_RE.fullmatch(reset_request_id)
        )
        code_valid = isinstance(code, str) and bool(PASSWORD_RESET_CODE_RE.fullmatch(code))

        if not request_valid or not code_valid:
            return make_error(
                "Invalid or expired password reset code",
                status=400,
                code="invalid_or_expired_code",
            )

        challenge = PasswordResetChallenge.query.filter_by(request_id=reset_request_id).first()
        now = datetime.utcnow()
        unavailable = (
            not challenge
            or challenge.consumed_at is not None
            or challenge.expires_at <= now
            or challenge.failed_attempts >= PASSWORD_RESET_CODE_MAX_ATTEMPTS
        )
        if unavailable:
            return make_error(
                "Invalid or expired password reset code",
                status=400,
                code="invalid_or_expired_code",
            )

        latest_challenge_id = (
            db.session.query(PasswordResetChallenge.id)
            .filter_by(user_id=challenge.user_id)
            .order_by(
                PasswordResetChallenge.created_at.desc(),
                PasswordResetChallenge.id.desc(),
            )
            .limit(1)
            .scalar()
        )
        if latest_challenge_id != challenge.id:
            return make_error(
                "Invalid or expired password reset code",
                status=400,
                code="invalid_or_expired_code",
            )

        candidate_hash = _password_reset_code_hash(reset_request_id, code)
        if not hmac.compare_digest(challenge.code_hash, candidate_hash):
            PasswordResetChallenge.query.filter(
                PasswordResetChallenge.id == challenge.id,
                PasswordResetChallenge.consumed_at.is_(None),
                PasswordResetChallenge.failed_attempts < PASSWORD_RESET_CODE_MAX_ATTEMPTS,
            ).update(
                {
                    "failed_attempts": PasswordResetChallenge.failed_attempts + 1,
                },
                synchronize_session=False,
            )
            db.session.commit()
            PasswordResetChallenge.query.filter(
                PasswordResetChallenge.id == challenge.id,
                PasswordResetChallenge.consumed_at.is_(None),
                PasswordResetChallenge.failed_attempts >= PASSWORD_RESET_CODE_MAX_ATTEMPTS,
            ).update({"consumed_at": now}, synchronize_session=False)
            db.session.commit()
            log_security_event(
                AuditEvents.SECURITY_INVALID_TOKEN,
                {"reason": "password_reset_code_mismatch"},
            )
            return make_error(
                "Invalid or expired password reset code",
                status=400,
                code="invalid_or_expired_code",
            )

        try:
            InputValidator.validate_password(password)
        except ValidationError as error:
            return make_error(
                str(error),
                status=400,
                code="invalid_password",
                extra={"field": "password"},
            )

        user = db.session.get(User, challenge.user_id)
        if not user:
            challenge.consumed_at = now
            db.session.commit()
            return make_error(
                "Invalid or expired password reset code",
                status=400,
                code="invalid_or_expired_code",
            )

        claimed = PasswordResetChallenge.query.filter(
            PasswordResetChallenge.id == challenge.id,
            PasswordResetChallenge.consumed_at.is_(None),
            PasswordResetChallenge.expires_at > now,
            PasswordResetChallenge.failed_attempts < PASSWORD_RESET_CODE_MAX_ATTEMPTS,
        ).update({"consumed_at": now}, synchronize_session=False)
        if claimed != 1:
            db.session.rollback()
            return make_error(
                "Invalid or expired password reset code",
                status=400,
                code="invalid_or_expired_code",
            )

        try:
            from argon2 import PasswordHasher

            user.password = PasswordHasher().hash(password)
        except ImportError:
            user.password = generate_password_hash(password, method="pbkdf2:sha256")
        user.auth_version = int(user.auth_version or 0) + 1
        user.reset_token = None
        user.reset_token_expires = None
        db.session.commit()

        log_audit_event(AuditEvents.AUTH_PASSWORD_RESET_COMPLETE, {}, user.id)
        settings = UserSettings.query.filter_by(user_id=user.id).first()
        copy = password_reset_email_copy(
            settings.language if settings and settings.language else "en",
            InputValidator.sanitize_output(user.username),
        )
        send_email(
            to_email=user.email,
            subject=copy["changedSubject"],
            body="",
            template_name="password_changed_localized",
            template_data={
                "heading": copy["changedHeading"],
                "greeting": copy["greeting"],
                "intro": copy["changedIntro"],
                "warning": copy["changedWarning"],
            },
        )
        return jsonify({"message": "password_reset_complete"}), 200

    @app.route("/api/auth/login", methods=["POST"])
    @rate_limit(login_limiter, "Too many login attempts")
    def api_login():

        try:
            from backend.security.brute_force import brute_force_protection, record_login_attempt
            from backend.security.session_security import regenerate_session

            data = request.get_json(silent=True) or {}
            email = data.get("email", "").strip()
            password = data.get("password", "")

            from backend.config import TURNSTILE_SITE_KEY

            turnstile_token = data.get("turnstile_response") or data.get("cf-turnstile-response")
            if TURNSTILE_SITE_KEY and not verify_turnstile(turnstile_token):
                return jsonify({"error": "Ошибка проверки Cloudflare Turnstile"}), 400

            if not email or not password:
                return jsonify({"error": "Email и пароль обязательны"}), 400

            try:
                email = InputValidator.validate_email(email)
            except ValidationError:
                return jsonify({"error": "Неверный email или пароль"}), 401

            is_locked, _ = brute_force_protection.is_locked("email", email)
            if is_locked:
                return jsonify({"error": "Слишком много попыток входа"}), 429

            user = User.query.filter_by(email=email).first()
            password_valid = _verify_user_password(user, password)

            if not user or not password_valid:
                record_login_attempt(email, False)
                return jsonify({"error": "Неверный email или пароль"}), 401

            if is_account_disabled(user):
                record_login_attempt(email, False)
                return jsonify({"error": format_account_restriction_message(user)}), 403

            if not user.is_confirmed:
                return (
                    jsonify({"error": "Пожалуйста, подтвердите ваш email перед входом"}),
                    403,
                )

            record_login_attempt(email, True)
            session.clear()
            session["user_id"] = user.id
            session["username"] = InputValidator.sanitize_output(user.username)
            session["_auth_version"] = int(user.auth_version or 0)
            regenerate_session()
            session.permanent = True

            return jsonify({"message": "Успешный вход", "user": user.to_dict()}), 200

        except Exception as e:
            app.logger.exception(f"API login error: {e}")
            return jsonify({"error": "Ошибка при входе"}), 500

    @app.route("/api/auth/logout", methods=["POST"])
    def api_logout():

        from backend.security.session_security import invalidate_session

        _revoke_pending_apple_link_challenges(session.get("user_id"))
        invalidate_session()
        return jsonify({"message": "Успешный выход"}), 200
