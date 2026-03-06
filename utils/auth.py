import json
import re
import secrets
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import requests
from authlib.integrations.base_client.errors import MismatchingStateError
from authlib.integrations.flask_client import OAuth
from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from itsdangerous import BadData, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from .input_validation import InputValidator, ValidationError
from .mailer import send_email
from .rate_limiting import login_limiter, rate_limit
from .responses import make_error
from .session_security import resolve_cookie_domain

db: Any = SQLAlchemy()
oauth = OAuth()
OAUTH_FALLBACK_STATE_COOKIE = "oauth_state_fallback"
OAUTH_FALLBACK_STATE_TTL_SECONDS = 900


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=True)
    is_confirmed = db.Column(db.Boolean, default=False)
    confirmation_token = db.Column(db.String(100), nullable=True)
    confirmation_token_expires = db.Column(db.DateTime, nullable=True)  # TTL for confirmation
    reset_token = db.Column(db.String(100), nullable=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)  # TTL for reset token (1 hour)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    oauth_provider = db.Column(db.String(20), nullable=True)
    oauth_id = db.Column(db.String(100), nullable=True)

    def __repr__(self):
        return f"<User {self.username}>"

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "is_confirmed": self.is_confirmed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "oauth_provider": self.oauth_provider,
        }


class UserSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    theme = db.Column(db.String(20), default="dark")
    language = db.Column(db.String(10), default="ru")
    settings_data = db.Column(db.Text, default="{}")  # JSON for additional settings
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<UserSettings {self.user_id}>"

    def get_settings(self):
        try:
            return json.loads(self.settings_data) if self.settings_data else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "theme": self.theme,
            "language": self.language,
            "settings_data": self.get_settings(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class UserChatHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    session_id = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(200), default="Новый чат")
    messages_data = db.Column(db.Text, default="[]")  # JSON array of messages
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<UserChatHistory {self.session_id}>"

    def get_messages(self):
        try:
            return json.loads(self.messages_data) if self.messages_data else []
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    def set_messages(self, messages):
        self.messages_data = json.dumps(messages, ensure_ascii=False)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "title": self.title,
            "messages": self.get_messages(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ChatShare(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    session_id = db.Column(db.String(100), nullable=False, unique=True, index=True)
    public_id = db.Column(db.String(128), nullable=False, unique=True, index=True)
    is_public = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "public_id": self.public_id,
            "is_public": self.is_public,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


def is_valid_password(password):

    if len(password) < 8:
        return False
    if not re.search(r"\d", password):
        return False
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False
    return True


def _is_argon2_hash(stored_password: str) -> bool:
    return isinstance(stored_password, str) and stored_password.startswith("$argon2")


def _upgrade_password_hash(user, password: str, ph) -> None:
    try:
        user.password = ph.hash(password)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.warning(
            "Password verified for user %s, but hash migration failed",
            getattr(user, "id", None),
        )


def _verify_user_password(user, password: str) -> bool:
    stored_password = getattr(user, "password", None)
    if not stored_password or not password:
        return False

    if _is_argon2_hash(stored_password):
        try:
            from argon2 import PasswordHasher
            from argon2.exceptions import InvalidHashError, VerifyMismatchError
        except ImportError:
            current_app.logger.warning(
                "Argon2 password stored for user %s, but argon2 is unavailable",
                getattr(user, "id", None),
            )
            return False

        ph = PasswordHasher()
        try:
            password_valid: bool = bool(ph.verify(stored_password, password))
        except (VerifyMismatchError, InvalidHashError):
            return False

        if password_valid and ph.check_needs_rehash(stored_password):
            _upgrade_password_hash(user, password, ph)
        return bool(password_valid)

    try:
        password_valid = bool(check_password_hash(stored_password, password))
    except ValueError:
        return False

    if not password_valid:
        return False

    try:
        from argon2 import PasswordHasher
    except ImportError:
        return True

    _upgrade_password_hash(user, password, PasswordHasher())
    return True


def _is_allowed_hostname(hostname: str | None, allowed_hosts) -> bool:
    if not hostname:
        return False

    host = hostname.lower().strip(".")
    for allowed in allowed_hosts or []:
        allowed_host = (allowed or "").lower().strip()
        if not allowed_host:
            continue
        if allowed_host.startswith("."):
            suffix = allowed_host[1:].strip(".")
            if host == suffix or host.endswith(f".{suffix}"):
                return True
            continue
        if host == allowed_host.strip("."):
            return True
    return False


def _is_loopback_hostname(hostname: str) -> bool:
    host = (hostname or "").lower().strip(".")
    return host in {"localhost", "127.0.0.1", "::1"}


def _is_safe_redirect_target(target: str, allowed_hosts) -> bool:
    if not target or not isinstance(target, str):
        return False

    parsed = urlparse(target)
    if not parsed.netloc:
        return target.startswith("/") and not target.startswith("//")

    if parsed.scheme not in ("http", "https"):
        return False

    return _is_allowed_hostname(parsed.hostname, allowed_hosts)


def _normalize_redirect_target(target: str, allowed_hosts) -> str:
    if not _is_safe_redirect_target(target, allowed_hosts):
        return ""

    parsed = urlparse(target)
    if not parsed.netloc:
        return target

    normalized = parsed.path or "/"
    if parsed.params:
        normalized = f"{normalized};{parsed.params}"
    if parsed.query:
        normalized = f"{normalized}?{parsed.query}"
    if parsed.fragment:
        normalized = f"{normalized}#{parsed.fragment}"
    return normalized


def _oauth_state_serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="google-oauth-fallback-state")


def _encode_oauth_fallback_state(secret_key: str, payload: dict) -> str:
    serializer = _oauth_state_serializer(secret_key)
    return serializer.dumps(payload)


def _decode_oauth_fallback_state(
    secret_key: str,
    raw_value: str,
    max_age: int = OAUTH_FALLBACK_STATE_TTL_SECONDS,
):
    if not raw_value or not secret_key:
        return None
    serializer = _oauth_state_serializer(secret_key)
    try:
        data = serializer.loads(raw_value, max_age=max_age)
    except BadData:
        return None
    return data if isinstance(data, dict) else None


def _resolve_oauth_redirect_base(
    request_host_url: str,
    backend_url: str | None,
    allowed_hosts,
    preferred_target: str = "",
) -> str:
    parsed_target = urlparse(preferred_target or "")
    if (
        parsed_target.scheme in ("http", "https")
        and parsed_target.netloc
        and _is_allowed_hostname(parsed_target.hostname, allowed_hosts)
    ):
        return f"{parsed_target.scheme}://{parsed_target.netloc}"

    request_host = urlparse(request_host_url).hostname
    if request_host and _is_loopback_hostname(request_host):
        return request_host_url.rstrip("/")

    if backend_url:
        return backend_url.rstrip("/")

    if not _is_allowed_hostname(request_host, allowed_hosts):
        return ""

    return request_host_url.rstrip("/")


def verify_turnstile(turnstile_response):

    from flask import current_app

    from config import LOCALHOST_MODE, TURNSTILE_SECRET_KEY, TURNSTILE_VERIFY_URL

    if LOCALHOST_MODE:
        current_app.logger.debug("Turnstile verification skipped (localhost mode)")
        return True

    if not turnstile_response:
        current_app.logger.warning("Turnstile token missing - request will be rejected")
        return False

    try:
        payload = {
            "secret": TURNSTILE_SECRET_KEY,
            "response": turnstile_response,
            "remoteip": request.remote_addr,
        }

        response = requests.post(TURNSTILE_VERIFY_URL, data=payload, timeout=10)

        if response.status_code != 200:
            current_app.logger.error(f"Turnstile API returned status {response.status_code}")
            return False

        result = response.json()
        success = result.get("success", False)

        if not success:
            error_codes = result.get("error-codes", [])
            current_app.logger.warning(f"Turnstile verification failed: {error_codes}")

        return success

    except requests.RequestException as e:
        current_app.logger.error(f"Turnstile verification request error: {str(e)}")
        return False
    except Exception as e:
        current_app.logger.error(f"Turnstile verification error: {str(e)}")
        return False


def register_auth_routes(app):

    @app.route("/register", methods=["GET", "POST"])
    @rate_limit(login_limiter, "Too many registration attempts")
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")
            turnstile_response = request.form.get("cf-turnstile-response")
            if not verify_turnstile(turnstile_response):
                flash(
                    "Ошибка проверки Cloudflare Turnstile. Пожалуйста, подтвердите, что вы не робот.",
                    "danger",
                )
                from config import TURNSTILE_SITE_KEY

                return render_template("register.html", turnstile_site_key=TURNSTILE_SITE_KEY)
            try:
                username = InputValidator.validate_username(username)
            except ValidationError as e:
                flash(str(e), "danger")
                from config import TURNSTILE_SITE_KEY

                return render_template("register.html", turnstile_site_key=TURNSTILE_SITE_KEY)

            try:
                email = InputValidator.validate_email(email)
            except ValidationError as e:
                flash(str(e), "danger")
                from config import TURNSTILE_SITE_KEY

                return render_template("register.html", turnstile_site_key=TURNSTILE_SITE_KEY)

            if password != confirm_password:
                flash("Пароли не совпадают", "danger")
                from config import TURNSTILE_SITE_KEY

                return render_template("register.html", turnstile_site_key=TURNSTILE_SITE_KEY)

            try:
                InputValidator.validate_password(password)
            except ValidationError as e:
                flash(str(e), "danger")
                from config import TURNSTILE_SITE_KEY

                return render_template("register.html", turnstile_site_key=TURNSTILE_SITE_KEY)
            user_exists = User.query.filter_by(email=email).first()
            if user_exists:
                flash("Email уже зарегистрирован", "danger")
                from config import TURNSTILE_SITE_KEY

                return render_template("register.html", turnstile_site_key=TURNSTILE_SITE_KEY)
            try:
                try:
                    from argon2 import PasswordHasher

                    ph = PasswordHasher()
                    hashed_password = ph.hash(password)
                except ImportError:
                    hashed_password = generate_password_hash(password, method="pbkdf2:sha256")

                confirmation_token = secrets.token_urlsafe(32)
                confirmation_token_expires = datetime.utcnow() + timedelta(days=7)  # 7 days TTL

                new_user = User(
                    username=username,
                    email=email,
                    password=hashed_password,
                    confirmation_token=confirmation_token,
                    confirmation_token_expires=confirmation_token_expires,
                )

                db.session.add(new_user)
                db.session.commit()
                confirmation_link = url_for(
                    "confirm_email", token=confirmation_token, _external=True
                )
                template_data = {
                    "username": InputValidator.sanitize_output(username),
                    "confirmation_link": confirmation_link,
                }

                send_email(
                    to_email=email,
                    subject="Подтвердите вашу регистрацию",
                    body="",
                    template_name="confirmation",
                    template_data=template_data,
                )

                flash(
                    "Регистрация успешна! Проверьте email для подтверждения аккаунта",
                    "success",
                )
                return redirect(url_for("login"))

            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Registration error: {str(e)}")
                flash("Ошибка при регистрации. Пожалуйста, попробуйте позже.", "danger")
                from config import TURNSTILE_SITE_KEY

                return render_template("register.html", turnstile_site_key=TURNSTILE_SITE_KEY)

        from config import TURNSTILE_SITE_KEY

        return render_template("register.html", turnstile_site_key=TURNSTILE_SITE_KEY)

    @app.route("/confirm/<token>")
    def confirm_email(token):
        user = User.query.filter_by(confirmation_token=token).first()
        if not user or (
            user.confirmation_token_expires and user.confirmation_token_expires < datetime.utcnow()
        ):
            if user:
                user.confirmation_token = None
                user.confirmation_token_expires = None
                db.session.commit()
            flash("Недействительная или устаревшая ссылка для подтверждения", "danger")
            return redirect(url_for("login"))

        user.is_confirmed = True
        user.confirmation_token = None
        user.confirmation_token_expires = None
        db.session.commit()

        flash("Ваш аккаунт подтвержден! Теперь вы можете войти", "success")
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    @rate_limit(login_limiter, "Too many login attempts")
    def login():
        from utils.audit_log import AuditEvents, log_auth_event
        from utils.brute_force import brute_force_protection, record_login_attempt
        from utils.session_security import regenerate_session

        if request.method == "POST":
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")
            remember = True if request.form.get("remember") else False
            is_locked, remaining = brute_force_protection.is_locked("email", email)
            if is_locked:
                log_auth_event(AuditEvents.AUTH_LOGIN_FAILED, email, False, "account_locked")
                flash(
                    f"Слишком много попыток. Попробуйте через {remaining // 60 + 1} минут.",
                    "danger",
                )
                from config import TURNSTILE_SITE_KEY

                return render_template("login.html", turnstile_site_key=TURNSTILE_SITE_KEY)
            turnstile_response = request.form.get("cf-turnstile-response")
            if not verify_turnstile(turnstile_response):
                flash(
                    "Ошибка проверки Cloudflare Turnstile. Пожалуйста, подтвердите, что вы не робот.",
                    "danger",
                )
                from config import TURNSTILE_SITE_KEY

                return render_template("login.html", turnstile_site_key=TURNSTILE_SITE_KEY)
            try:
                email = InputValidator.validate_email(email)
            except ValidationError:
                record_login_attempt(email, False)
                log_auth_event(AuditEvents.AUTH_LOGIN_FAILED, email, False, "invalid_email")
                flash("Неверный email или пароль", "danger")
                from config import TURNSTILE_SITE_KEY

                return render_template("login.html", turnstile_site_key=TURNSTILE_SITE_KEY)

            user = User.query.filter_by(email=email).first()
            password_valid = _verify_user_password(user, password)

            if not user or not password_valid:
                record_login_attempt(email, False)
                log_auth_event(AuditEvents.AUTH_LOGIN_FAILED, email, False, "invalid_credentials")
                flash("Неверный email или пароль", "danger")
                from config import TURNSTILE_SITE_KEY

                return render_template("login.html", turnstile_site_key=TURNSTILE_SITE_KEY)

            if not user.is_confirmed:
                log_auth_event(AuditEvents.AUTH_LOGIN_FAILED, email, False, "email_not_confirmed")
                flash("Пожалуйста, подтвердите ваш email перед входом", "warning")
                from config import TURNSTILE_SITE_KEY

                return render_template("login.html", turnstile_site_key=TURNSTILE_SITE_KEY)
            record_login_attempt(email, True)
            log_auth_event(AuditEvents.AUTH_LOGIN_SUCCESS, email, True)
            session.clear()
            session["user_id"] = user.id
            session["username"] = InputValidator.sanitize_output(user.username)
            regenerate_session()

            if remember:
                session.permanent = True

            return redirect(url_for("good"))
        try:
            app.logger.debug(f"Login route GET args: {request.args}")
            if "code" in request.args:
                app.logger.info(
                    "Detected OAuth 'code' on /login; processing via /login/google/callback"
                )
                return authorize_google()
            oauth_error = request.args.get("error")
            oauth_error_description = request.args.get("error_description") or request.args.get(
                "error_description"
            )
            if oauth_error:
                app.logger.warning(
                    f"OAuth provider returned error on /login: {oauth_error} - {oauth_error_description}"
                )
                flash(
                    f"Ошибка авторизации: {oauth_error_description or oauth_error}",
                    "danger",
                )
        except Exception as _e:
            app.logger.debug(f"Failed to log login route args: {_e}")

        from config import TURNSTILE_SITE_KEY

        return render_template("login.html", turnstile_site_key=TURNSTILE_SITE_KEY)

    @app.route("/good")
    def good():
        if "user_id" not in session:
            flash("Пожалуйста, сначала войдите в систему", "warning")
            return redirect(url_for("login"))

        username = session.get("username")
        return render_template("good.html", username=username)

    @app.route("/forgot_password", methods=["GET", "POST"])
    def forgot_password():
        if request.method == "POST":
            email = request.form.get("email")
            user = User.query.filter_by(email=email).first()
            if user:
                reset_token = secrets.token_urlsafe(32)
                user.reset_token = reset_token
                user.reset_token_expires = datetime.utcnow() + timedelta(hours=1)  # 1 hour TTL
                db.session.commit()
                reset_link = url_for("reset_password", token=reset_token, _external=True)
                template_data = {"username": user.username, "reset_link": reset_link}

                send_email(
                    to_email=email,
                    subject="Сброс пароля",
                    body="",
                    template_name="reset_password",
                    template_data=template_data,
                )
            flash(
                "Если аккаунт с таким email существует, инструкции по сбросу пароля были отправлены",
                "success",
            )
            return redirect(url_for("login"))

        return render_template("forgot_password.html")

    @app.route("/reset_password/<token>", methods=["GET", "POST"])
    def reset_password(token):
        user = User.query.filter_by(reset_token=token).first()
        if not user or (user.reset_token_expires and user.reset_token_expires < datetime.utcnow()):
            if user:
                user.reset_token = None
                user.reset_token_expires = None
                db.session.commit()
            flash("Недействительная или устаревшая ссылка для сброса", "danger")
            return redirect(url_for("login"))

        if request.method == "POST":
            password = request.form.get("password")
            confirm_password = request.form.get("confirm_password")

            if password != confirm_password:
                flash("Пароли не совпадают", "danger")
                return render_template("reset_password.html", token=token)

            if not is_valid_password(password):
                flash(
                    "Пароль должен содержать минимум 8 символов, 1 цифру и 1 спецсимвол",
                    "danger",
                )
                return render_template("reset_password.html", token=token)
            try:
                from argon2 import PasswordHasher

                ph = PasswordHasher()
                user.password = ph.hash(password)
            except ImportError:
                user.password = generate_password_hash(password, method="pbkdf2:sha256")
            user.reset_token = None
            user.reset_token_expires = None
            db.session.commit()
            template_data = {"username": user.username}
            send_email(
                to_email=user.email,
                subject="Пароль успешно изменен",
                body="",
                template_name="password_changed",
                template_data=template_data,
            )

            flash("Ваш пароль успешно обновлен", "success")
            return redirect(url_for("login"))

        return render_template("reset_password.html", token=token)

    @app.route("/logout", methods=["POST"])
    def logout():
        from utils.audit_log import AuditEvents, log_audit_event
        from utils.session_security import invalidate_session

        user_id = session.get("user_id")
        if user_id:
            log_audit_event(AuditEvents.AUTH_LOGOUT, {}, user_id)
        invalidate_session()
        flash("Вы вышли из системы", "info")
        return redirect(url_for("login"))

    @app.route("/logout", methods=["GET"])
    def logout_get():
        return redirect(url_for("login"))

    @app.route("/profile")
    def profile():
        if "user_id" not in session:
            flash("Пожалуйста, сначала войдите в систему", "warning")
            return redirect(url_for("login"))

        user_id = session.get("user_id")
        user = User.query.get(user_id)
        settings = UserSettings.query.filter_by(user_id=user_id).first()
        personalization = {}
        if settings:
            personalization = settings.get_settings() or {}

        return render_template("profile.html", user=user, personalization=personalization)

    @app.route("/login/google")
    def login_google():
        from config import ALLOWED_HOSTS, BACKEND_URL, SECRET_KEY, SESSION_COOKIE_DOMAIN

        redirect_to_candidate = (
            request.args.get("redirect_to") or request.headers.get("Referer") or ""
        )
        safe_redirect_path = _normalize_redirect_target(redirect_to_candidate, ALLOWED_HOSTS)
        if safe_redirect_path:
            session["oauth_redirect_to"] = safe_redirect_path

        redirect_base = _resolve_oauth_redirect_base(
            request_host_url=request.host_url,
            backend_url=BACKEND_URL,
            allowed_hosts=ALLOWED_HOSTS,
            preferred_target=safe_redirect_path,
        )
        if not redirect_base:
            app.logger.warning("Blocked OAuth start due to untrusted request host")
            return redirect(url_for("login"))
        redirect_uri = f"{redirect_base}{url_for('authorize_google')}"

        google_client = getattr(oauth, "google", None)
        if google_client is None:
            app.logger.error("Google OAuth is not configured (missing client registration)")
            return make_error(
                "Google OAuth is not configured", status=503, code="oauth_unavailable"
            )

        try:
            auth_data = google_client.create_authorization_url(redirect_uri)
            google_client.save_authorize_data(redirect_uri=redirect_uri, **auth_data)

            response = redirect(auth_data["url"])
            state = auth_data.get("state")
            if SECRET_KEY and state:
                cookie_domain = resolve_cookie_domain(SESSION_COOKIE_DOMAIN, request.host)
                fallback_payload = {
                    "state": state,
                    "redirect_uri": redirect_uri,
                }
                fallback_cookie = _encode_oauth_fallback_state(SECRET_KEY, fallback_payload)
                request_host = urlparse(request.host_url).hostname
                secure_cookie = not _is_loopback_hostname(request_host)
                response.set_cookie(
                    OAUTH_FALLBACK_STATE_COOKIE,
                    fallback_cookie,
                    max_age=OAUTH_FALLBACK_STATE_TTL_SECONDS,
                    httponly=True,
                    secure=secure_cookie,
                    samesite="Lax",
                    domain=cookie_domain,
                    path=url_for("authorize_google"),
                )
            return response
        except Exception as exc:
            app.logger.exception(f"Failed to start Google OAuth redirect: {exc}")
            return make_error("Failed to start Google OAuth", status=500, code="oauth_start_failed")

    @app.route("/login/google/callback")
    def authorize_google():
        try:
            app.logger.debug(f"authorize_google request args: {request.args}")
            app.logger.debug(f"authorize_google request url: {request.url}")
            app.logger.info(f"authorize_google Host: {request.host}")
            app.logger.info(f"authorize_google Scheme: {request.scheme}")
            app.logger.info(f"authorize_google Base URL: {request.base_url}")
            from config import ALLOWED_HOSTS

            redirect_to = session.pop("oauth_redirect_to", None)
            try:
                app.logger.info("Attempting to exchange code for access token...")
                token = oauth.google.authorize_access_token()
                app.logger.debug("Token obtained successfully")
            except MismatchingStateError as token_err:
                from config import SECRET_KEY

                app.logger.warning(
                    f"OAuth state mismatch. Trying signed fallback state cookie: {token_err}"
                )
                fallback_state_raw = request.cookies.get(OAUTH_FALLBACK_STATE_COOKIE, "")
                fallback_state = _decode_oauth_fallback_state(SECRET_KEY, fallback_state_raw)
                request_state = request.args.get("state", "")
                request_code = request.args.get("code", "")
                fallback_state_value = str((fallback_state or {}).get("state", ""))
                fallback_redirect_uri = str((fallback_state or {}).get("redirect_uri", ""))
                if (
                    fallback_state
                    and request_state
                    and fallback_state_value
                    and request_code
                    and secrets.compare_digest(fallback_state_value, request_state)
                ):
                    app.logger.warning(
                        "Fallback state validation succeeded. Exchanging token without session state."
                    )
                    token = oauth.google.fetch_access_token(
                        code=request_code,
                        redirect_uri=fallback_redirect_uri or request.base_url,
                    )
                    app.logger.debug("Token obtained successfully via fallback state cookie")
                else:
                    app.logger.error("Fallback state validation failed")
                    raise
            except Exception as token_err:
                app.logger.error(f"Failed to get access token: {token_err}")
                app.logger.error(f"Request args: {dict(request.args)}")
                if hasattr(token_err, "description"):
                    app.logger.error(f"Error description: {token_err.description}")
                raise
            if not isinstance(token, dict) or not token.get("access_token"):
                app.logger.error(
                    "Google token exchange returned no access_token. "
                    f"Token keys: {list(token.keys()) if isinstance(token, dict) else type(token)}"
                )
                raise RuntimeError("google_oauth_missing_access_token")

            # When token is obtained via fallback flow, Authlib may not populate client token state.
            oauth.google.token = token
            resp = oauth.google.get("https://www.googleapis.com/oauth2/v3/userinfo", token=token)
            user_info = resp.json()
            app.logger.debug(f"User info obtained: {user_info.get('email')}")
            if "email" not in user_info:
                flash("Не удалось получить email из Google аккаунта", "danger")
                return redirect(url_for("login"))
            google_id = user_info.get("sub")
            email = user_info.get("email")

            user = User.query.filter_by(email=email).first()

            if not user:
                username = user_info.get("name", email.split("@")[0])
                new_user = User(
                    username=username,
                    email=email,
                    is_confirmed=True,
                    oauth_provider="google",
                    oauth_id=google_id,
                )
                db.session.add(new_user)
                db.session.commit()
                user = new_user
                flash("Аккаунт создан с помощью Google авторизации", "success")
            elif not user.oauth_id:
                user.oauth_provider = "google"
                user.oauth_id = google_id
                user.is_confirmed = True
                db.session.commit()
                flash("Ваш аккаунт связан с Google", "success")
            from utils.session_security import regenerate_session

            session.clear()
            session["user_id"] = user.id
            session["username"] = InputValidator.sanitize_output(user.username)
            regenerate_session()
            session.permanent = True
            from config import SESSION_COOKIE_DOMAIN

            cookie_domain = resolve_cookie_domain(SESSION_COOKIE_DOMAIN, request.host)
            safe_redirect_path = _normalize_redirect_target(redirect_to, ALLOWED_HOSTS)
            if safe_redirect_path:
                response = redirect(safe_redirect_path)
            else:
                response = redirect("/")
            response.delete_cookie(
                OAUTH_FALLBACK_STATE_COOKIE,
                domain=cookie_domain,
                path=url_for("authorize_google"),
            )
            return response

        except Exception as e:
            app.logger.exception(f"OAuth error in authorize_google(): {e}")
            flash("Ошибка при входе через Google", "danger")
            response = redirect(url_for("login"))
            from config import SESSION_COOKIE_DOMAIN

            cookie_domain = resolve_cookie_domain(SESSION_COOKIE_DOMAIN, request.host)
            response.delete_cookie(
                OAUTH_FALLBACK_STATE_COOKIE,
                domain=cookie_domain,
                path=url_for("authorize_google"),
            )
            return response

    @app.route("/api/auth/check", methods=["GET"])
    def api_check_auth():

        if "user_id" in session:
            user = User.query.get(session["user_id"])
            if user:
                return jsonify({"authenticated": True, "user": user.to_dict()}), 200
        return jsonify({"authenticated": False, "user": None}), 200

    @app.route("/api/auth/config", methods=["GET"])
    def api_auth_config():

        from config import GOOGLE_CLIENT_ID, TURNSTILE_SITE_KEY

        return (
            jsonify(
                {
                    "turnstile_site_key": TURNSTILE_SITE_KEY,
                    "gauth_available": bool(GOOGLE_CLIENT_ID),
                    "google_login_url": url_for("login_google"),
                }
            ),
            200,
        )

    @app.route("/api/auth/register", methods=["POST"])
    @rate_limit(login_limiter, "Too many registration attempts")
    def api_register():

        try:
            data = request.get_json(silent=True) or {}
            username = data.get("username", "")
            email = data.get("email", "")
            password = data.get("password", "")
            from config import TURNSTILE_SITE_KEY

            turnstile_token = data.get("turnstile_response") or data.get("cf-turnstile-response")
            if TURNSTILE_SITE_KEY and not verify_turnstile(turnstile_token):
                return jsonify({"error": "Ошибка проверки Cloudflare Turnstile"}), 400

            if not username or not email or not password:
                return jsonify({"error": "Все поля обязательны"}), 400

            try:
                username = InputValidator.validate_username(username)
                email = InputValidator.validate_email(email)
                InputValidator.validate_password(password)
            except ValidationError as e:
                return jsonify({"error": str(e)}), 400

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

            try:
                send_email(
                    to_email=email,
                    subject="Подтвердите вашу регистрацию",
                    body="",
                    template_name="confirmation",
                    template_data=template_data,
                )
            except Exception as e:
                app.logger.warning(f"Email sending error: {e}")

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

    @app.route("/api/auth/login", methods=["POST"])
    @rate_limit(login_limiter, "Too many login attempts")
    def api_login():

        try:
            from utils.brute_force import brute_force_protection, record_login_attempt
            from utils.session_security import regenerate_session

            data = request.get_json(silent=True) or {}
            email = data.get("email", "").strip()
            password = data.get("password", "")

            from config import TURNSTILE_SITE_KEY

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

            if not user.is_confirmed:
                return (
                    jsonify({"error": "Пожалуйста, подтвердите ваш email перед входом"}),
                    403,
                )

            record_login_attempt(email, True)
            session.clear()
            session["user_id"] = user.id
            session["username"] = InputValidator.sanitize_output(user.username)
            regenerate_session()
            session.permanent = True

            return jsonify({"message": "Успешный вход", "user": user.to_dict()}), 200

        except Exception as e:
            app.logger.exception(f"API login error: {e}")
            return jsonify({"error": "Ошибка при входе"}), 500

    @app.route("/api/auth/logout", methods=["POST"])
    def api_logout():

        from utils.session_security import invalidate_session

        invalidate_session()
        return jsonify({"message": "Успешный выход"}), 200

    @app.route("/api/auth/profile", methods=["GET"])
    def api_get_profile():

        if "user_id" not in session:
            return jsonify({"error": "Не авторизирован"}), 401

        user = User.query.get(session["user_id"])
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
            user = User.query.get(session["user_id"])

            if not user:
                return jsonify({"error": "Пользователь не найден"}), 404

            if "username" in data:
                user.username = InputValidator.validate_username(data["username"])

            db.session.commit()

            return jsonify({"message": "Профиль обновлен", "user": user.to_dict()}), 200

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
            return jsonify({"error": "Настройки не найдены"}), 404

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
            if "settings_data" in data:
                settings.settings_data = json.dumps(data["settings_data"], ensure_ascii=False)
            elif data:
                current_settings = settings.get_settings()
                for key, value in data.items():
                    if key not in ["theme", "language"]:
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

    @app.route("/api/chat-history/<session_id>", methods=["GET"])
    def api_get_chat_history(session_id):

        if "user_id" not in session:
            return jsonify({"error": "Не авторизирован"}), 401

        chat = UserChatHistory.query.filter_by(
            user_id=session["user_id"], session_id=session_id
        ).first()

        if not chat:
            return (
                jsonify({"session_id": session_id, "messages": [], "title": None}),
                200,
            )

        return (
            jsonify(
                {
                    "session_id": session_id,
                    "title": chat.title,
                    "messages": chat.get_messages(),
                    "created_at": chat.created_at.isoformat(),
                    "updated_at": chat.updated_at.isoformat(),
                }
            ),
            200,
        )

    @app.route("/api/chat-history/<session_id>", methods=["POST"])
    def api_save_chat_history(session_id):

        if "user_id" not in session:
            return jsonify({"error": "Не авторизирован"}), 401

        try:
            data = request.get_json(silent=True) or {}
            messages = data.get("messages", [])
            title = data.get("title", "Новый чат")

            chat = UserChatHistory.query.filter_by(
                user_id=session["user_id"], session_id=session_id
            ).first()

            if not chat:
                chat = UserChatHistory(
                    user_id=session["user_id"], session_id=session_id, title=title
                )
                db.session.add(chat)

            chat.set_messages(messages)
            chat.title = title
            chat.updated_at = datetime.utcnow()
            db.session.commit()

            return (
                jsonify({"message": "История сохранена", "chat": chat.to_dict()}),
                200,
            )

        except Exception as e:
            db.session.rollback()
            app.logger.exception(f"API save chat history error: {e}")
            return jsonify({"error": "Не удалось сохранить историю"}), 500

    @app.route("/api/chat-history", methods=["GET"])
    def api_list_chat_histories():

        if "user_id" not in session:
            return jsonify({"error": "Не авторизирован"}), 401

        chats = UserChatHistory.query.filter_by(user_id=session["user_id"]).all()
        chats.sort(key=lambda x: x.updated_at, reverse=True)

        return jsonify({"chats": [chat.to_dict() for chat in chats]}), 200

    @app.route("/api/chat-history/<session_id>", methods=["DELETE"])
    def api_delete_chat_history(session_id):

        if "user_id" not in session:
            return jsonify({"error": "Не авторизирован"}), 401

        db_user_id = session.get("user_id")
        if not db_user_id or not isinstance(db_user_id, int):
            return jsonify({"error": "Неверная сессия"}), 401

        chat = UserChatHistory.query.filter_by(user_id=db_user_id, session_id=session_id).first()

        if chat:
            db.session.delete(chat)
            db.session.commit()

        return ("", 204)

    @app.route("/api/user/favorites", methods=["GET"])
    def api_get_favorites():

        if "user_id" not in session:
            return jsonify({"favorites": []}), 200

        try:
            db_user_id = session.get("user_id")
            if not db_user_id or not isinstance(db_user_id, int):
                return jsonify({"favorites": []}), 200

            settings = UserSettings.query.filter_by(user_id=db_user_id).first()
            if not settings:
                return jsonify({"favorites": []}), 200

            user_settings = settings.get_settings()
            favorites = user_settings.get("favoriteChats", [])
            return jsonify({"favorites": favorites}), 200
        except Exception as e:
            app.logger.exception(f"API get favorites error: {e}")
            return jsonify({"favorites": []}), 200

    @app.route("/api/user/favorites", methods=["POST"])
    def api_add_favorite():

        if "user_id" not in session:
            return jsonify({"error": "Не авторизирован"}), 401

        try:
            data = request.get_json(silent=True) or {}
            session_id = data.get("session_id")
            if not session_id:
                return jsonify({"error": "session_id required"}), 400
            session_id = str(session_id).strip()
            if len(session_id) > 200:
                return jsonify({"error": "session_id too long"}), 400

            db_user_id = session.get("user_id")
            if not db_user_id or not isinstance(db_user_id, int):
                return jsonify({"error": "Неверная сессия"}), 401

            settings = UserSettings.query.filter_by(user_id=db_user_id).first()
            if not settings:
                settings = UserSettings(user_id=db_user_id)
                db.session.add(settings)

            user_settings = settings.get_settings()
            favorites = user_settings.get("favoriteChats", [])
            if session_id not in favorites:
                favorites.append(session_id)
                user_settings["favoriteChats"] = favorites
                settings.settings_data = json.dumps(user_settings, ensure_ascii=False)
                settings.updated_at = datetime.utcnow()
                db.session.commit()

            return jsonify({"favorites": favorites}), 200
        except Exception as e:
            db.session.rollback()
            app.logger.exception(f"API add favorite error: {e}")
            return jsonify({"error": "Не удалось сохранить избранное"}), 500

    @app.route("/api/user/favorites", methods=["DELETE"])
    def api_remove_favorite():

        if "user_id" not in session:
            return jsonify({"error": "Не авторизирован"}), 401

        try:
            data = request.get_json(silent=True) or {}
            session_id = data.get("session_id")
            if not session_id:
                return jsonify({"error": "session_id required"}), 400
            session_id = str(session_id).strip()
            if len(session_id) > 200:
                return jsonify({"error": "session_id too long"}), 400

            db_user_id = session.get("user_id")
            if not db_user_id or not isinstance(db_user_id, int):
                return jsonify({"error": "Неверная сессия"}), 401

            settings = UserSettings.query.filter_by(user_id=db_user_id).first()
            if not settings:
                return jsonify({"favorites": []}), 200

            user_settings = settings.get_settings()
            favorites = user_settings.get("favoriteChats", [])
            if session_id in favorites:
                favorites.remove(session_id)
                user_settings["favoriteChats"] = favorites
                settings.settings_data = json.dumps(user_settings, ensure_ascii=False)
                settings.updated_at = datetime.utcnow()
                db.session.commit()

            return jsonify({"favorites": favorites}), 200
        except Exception as e:
            db.session.rollback()
            app.logger.exception(f"API remove favorite error: {e}")
            return jsonify({"error": "Не удалось обновить избранное"}), 500

    @app.route("/api/user/preferences", methods=["GET"])
    def api_get_preferences():

        if "user_id" not in session:
            return jsonify({"preferences": {}}), 200

        try:
            db_user_id = session.get("user_id")
            if not db_user_id or not isinstance(db_user_id, int):
                return jsonify({"preferences": {}}), 200

            settings = UserSettings.query.filter_by(user_id=db_user_id).first()
            if not settings:
                return jsonify({"preferences": {}}), 200

            user_settings = settings.get_settings()
            preferences = {
                "readingMode": user_settings.get("readingMode", False),
                "sessionSlugIndex": user_settings.get("sessionSlugIndex", {}),
            }
            return jsonify({"preferences": preferences}), 200
        except Exception as e:
            app.logger.exception(f"API get preferences error: {e}")
            return jsonify({"preferences": {}}), 200

    @app.route("/api/user/preferences", methods=["PUT"])
    def api_update_preferences():

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

            user_settings = settings.get_settings()

            if "readingMode" in data:
                user_settings["readingMode"] = bool(data["readingMode"])
            if "sessionSlugIndex" in data:
                user_settings["sessionSlugIndex"] = data["sessionSlugIndex"]

            settings.settings_data = json.dumps(user_settings, ensure_ascii=False)
            settings.updated_at = datetime.utcnow()
            db.session.commit()

            return (
                jsonify(
                    {
                        "message": "Настройки сохранены",
                        "preferences": {
                            "readingMode": user_settings.get("readingMode", False),
                            "sessionSlugIndex": user_settings.get("sessionSlugIndex", {}),
                        },
                    }
                ),
                200,
            )
        except Exception as e:
            db.session.rollback()
            app.logger.exception(f"API update preferences error: {e}")
            return jsonify({"error": "Не удалось обновить настройки"}), 500


def setup_auth(app):

    from sqlalchemy import event

    from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET

    db.init_app(app)
    oauth.init_app(app)

    db_uri = (app.config.get("SQLALCHEMY_DATABASE_URI") or "").lower()
    if db_uri.startswith("sqlite:"):
        with app.app_context():
            engine = db.engine
            if not getattr(engine, "_remind_sqlite_pragmas", False):

                @event.listens_for(engine, "connect")
                def _set_sqlite_pragmas(dbapi_connection, _connection_record):
                    cursor = dbapi_connection.cursor()
                    cursor.execute("PRAGMA journal_mode=MEMORY")
                    cursor.execute("PRAGMA temp_store=MEMORY")
                    cursor.execute("PRAGMA synchronous=NORMAL")
                    cursor.close()

                engine._remind_sqlite_pragmas = True

    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
        app.logger.info(f"Registering Google OAuth with client_id: {GOOGLE_CLIENT_ID[:20]}...")
        oauth.register(
            name="google",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            access_token_url="https://oauth2.googleapis.com/token",
            api_base_url="https://openidconnect.googleapis.com/v1/",
            client_kwargs={"scope": "openid email profile"},
            authorize_params={"access_type": "offline", "prompt": "consent"},
        )
        app.logger.info("Google OAuth registered successfully")
    with app.app_context():
        db.create_all()
        app.logger.info("Database tables created successfully")
    register_auth_routes(app)
