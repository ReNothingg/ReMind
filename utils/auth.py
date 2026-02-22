import os
import secrets
import re
import json
from datetime import timedelta, datetime
from urllib.parse import urlparse
import requests
import jwt
from flask import render_template, request, redirect, url_for, flash, session, jsonify
import logging
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth
from .mailer import send_email
from .input_validation import InputValidator, ValidationError
from .rate_limiting import login_limiter, password_reset_limiter, rate_limit

db = SQLAlchemy()
oauth = OAuth()
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
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self):
        return f"<UserSettings {self.user_id}>"

    def get_settings(self):
        try:
            return json.loads(self.settings_data) if self.settings_data else {}
        except:
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
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self):
        return f"<UserChatHistory {self.session_id}>"

    def get_messages(self):
        try:
            return json.loads(self.messages_data) if self.messages_data else []
        except:
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


def _is_allowed_hostname(hostname: str, allowed_hosts) -> bool:
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


def verify_turnstile(turnstile_response):

    from config import TURNSTILE_SECRET_KEY, TURNSTILE_VERIFY_URL, LOCALHOST_MODE
    from flask import current_app
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
            current_app.logger.error(
                f"Turnstile API returned status {response.status_code}"
            )
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
    @rate_limit(login_limiter, 'Too many registration attempts')
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

                return render_template(
                    "register.html", turnstile_site_key=TURNSTILE_SITE_KEY
                )
            try:
                username = InputValidator.validate_username(username)
            except ValidationError as e:
                flash(str(e), "danger")
                from config import TURNSTILE_SITE_KEY
                return render_template(
                    "register.html", turnstile_site_key=TURNSTILE_SITE_KEY
                )

            try:
                email = InputValidator.validate_email(email)
            except ValidationError as e:
                flash(str(e), "danger")
                from config import TURNSTILE_SITE_KEY
                return render_template(
                    "register.html", turnstile_site_key=TURNSTILE_SITE_KEY
                )

            if password != confirm_password:
                flash("Пароли не совпадают", "danger")
                from config import TURNSTILE_SITE_KEY
                return render_template(
                    "register.html", turnstile_site_key=TURNSTILE_SITE_KEY
                )

            try:
                InputValidator.validate_password(password)
            except ValidationError as e:
                flash(str(e), "danger")
                from config import TURNSTILE_SITE_KEY
                return render_template(
                    "register.html", turnstile_site_key=TURNSTILE_SITE_KEY
                )
            user_exists = User.query.filter_by(email=email).first()
            if user_exists:
                flash("Email уже зарегистрирован", "danger")
                from config import TURNSTILE_SITE_KEY
                return render_template(
                    "register.html", turnstile_site_key=TURNSTILE_SITE_KEY
                )
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
                return render_template(
                    "register.html", turnstile_site_key=TURNSTILE_SITE_KEY
                )

        from config import TURNSTILE_SITE_KEY
        return render_template("register.html", turnstile_site_key=TURNSTILE_SITE_KEY)

    @app.route("/confirm/<token>")
    def confirm_email(token):
        user = User.query.filter_by(confirmation_token=token).first()
        if not user or (user.confirmation_token_expires and user.confirmation_token_expires < datetime.utcnow()):
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
    @rate_limit(login_limiter, 'Too many login attempts')
    def login():
        from utils.brute_force import brute_force_protection, record_login_attempt
        from utils.audit_log import log_auth_event, AuditEvents
        from utils.session_security import regenerate_session

        if request.method == "POST":
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")
            remember = True if request.form.get("remember") else False
            is_locked, remaining = brute_force_protection.is_locked('email', email)
            if is_locked:
                log_auth_event(AuditEvents.AUTH_LOGIN_FAILED, email, False, 'account_locked')
                flash(f"Слишком много попыток. Попробуйте через {remaining // 60 + 1} минут.", "danger")
                from config import TURNSTILE_SITE_KEY
                return render_template("login.html", turnstile_site_key=TURNSTILE_SITE_KEY)
            turnstile_response = request.form.get("cf-turnstile-response")
            if not verify_turnstile(turnstile_response):
                flash(
                    "Ошибка проверки Cloudflare Turnstile. Пожалуйста, подтвердите, что вы не робот.",
                    "danger",
                )
                from config import TURNSTILE_SITE_KEY

                return render_template(
                    "login.html", turnstile_site_key=TURNSTILE_SITE_KEY
                )
            try:
                email = InputValidator.validate_email(email)
            except ValidationError:
                record_login_attempt(email, False)
                log_auth_event(AuditEvents.AUTH_LOGIN_FAILED, email, False, 'invalid_email')
                flash("Неверный email или пароль", "danger")
                from config import TURNSTILE_SITE_KEY
                return render_template(
                    "login.html", turnstile_site_key=TURNSTILE_SITE_KEY
                )

            user = User.query.filter_by(email=email).first()
            password_valid = False
            if user and user.password:
                try:
                    from argon2 import PasswordHasher
                    from argon2.exceptions import VerifyMismatchError, InvalidHashError
                    ph = PasswordHasher()
                    try:
                        ph.verify(user.password, password)
                        password_valid = True
                        if ph.check_needs_rehash(user.password):
                            user.password = ph.hash(password)
                            db.session.commit()
                    except (VerifyMismatchError, InvalidHashError):
                        if check_password_hash(user.password, password):
                            password_valid = True
                            user.password = ph.hash(password)
                            db.session.commit()
                except ImportError:
                    password_valid = check_password_hash(user.password, password)

            if not user or not password_valid:
                record_login_attempt(email, False)
                log_auth_event(AuditEvents.AUTH_LOGIN_FAILED, email, False, 'invalid_credentials')
                flash("Неверный email или пароль", "danger")
                from config import TURNSTILE_SITE_KEY

                return render_template(
                    "login.html", turnstile_site_key=TURNSTILE_SITE_KEY
                )

            if not user.is_confirmed:
                log_auth_event(AuditEvents.AUTH_LOGIN_FAILED, email, False, 'email_not_confirmed')
                flash("Пожалуйста, подтвердите ваш email перед входом", "warning")
                from config import TURNSTILE_SITE_KEY

                return render_template(
                    "login.html", turnstile_site_key=TURNSTILE_SITE_KEY
                )
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
                    "Detected OAuth 'code' on /login; redirecting to /login/google/callback to complete authorization"
                )
                return redirect(
                    url_for("authorize_google", **request.args.to_dict(flat=True))
                )
            oauth_error = request.args.get("error")
            oauth_error_description = request.args.get(
                "error_description"
            ) or request.args.get("error_description")
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
            flash("Если аккаунт с таким email существует, инструкции по сбросу пароля были отправлены", "success")
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
        from utils.audit_log import log_audit_event, AuditEvents
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

        return render_template(
            "profile.html", user=user, personalization=personalization
        )
    @app.route("/login/google")
    def login_google():
        from config import BACKEND_URL, ALLOWED_HOSTS, LOCALHOST_MODE

        redirect_to_candidate = request.args.get("redirect_to") or request.headers.get("Referer") or ""
        if _is_safe_redirect_target(redirect_to_candidate, ALLOWED_HOSTS):
            session["oauth_redirect_to"] = redirect_to_candidate

        request_host = urlparse(request.host_url).hostname
        prefer_request_host = LOCALHOST_MODE or _is_loopback_hostname(request_host)

        if BACKEND_URL and not prefer_request_host:
            redirect_uri = f"{BACKEND_URL.rstrip('/')}{url_for('authorize_google')}"
        else:
            if not _is_allowed_hostname(request_host, ALLOWED_HOSTS):
                app.logger.warning("Blocked OAuth start due to untrusted request host")
                return redirect(url_for("login"))
            redirect_uri = f"{request.host_url.rstrip('/')}{url_for('authorize_google')}"

        return oauth.google.authorize_redirect(redirect_uri)

    @app.route("/login/google/callback")
    def authorize_google():
        try:
            app.logger.debug(f"authorize_google request args: {request.args}")
            app.logger.debug(f"authorize_google request url: {request.url}")
            app.logger.info(f"authorize_google Host: {request.host}")
            app.logger.info(f"authorize_google Scheme: {request.scheme}")
            app.logger.info(f"authorize_google Base URL: {request.base_url}")
            try:
                app.logger.info("Attempting to exchange code for access token...")
                token = oauth.google.authorize_access_token()
                app.logger.debug(f"Token obtained successfully")
            except Exception as token_err:
                app.logger.error(f"Failed to get access token: {token_err}")
                app.logger.error(f"Request args: {dict(request.args)}")
                if hasattr(token_err, "description"):
                    app.logger.error(f"Error description: {token_err.description}")
                raise
            resp = oauth.google.get("https://www.googleapis.com/oauth2/v3/userinfo")
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
            from config import ALLOWED_HOSTS
            redirect_to = session.pop("oauth_redirect_to", None)
            if _is_safe_redirect_target(redirect_to, ALLOWED_HOSTS):
                return redirect(redirect_to)
            return redirect("/")

        except Exception as e:
            app.logger.exception(f"OAuth error in authorize_google(): {e}")
            flash("Ошибка при входе через Google", "danger")
            err_param = request.args.get("error")
            err_desc = request.args.get("error_description")
            if err_param:
                return redirect(
                    url_for("login", error=err_param, error_description=err_desc)
                )
            return redirect(url_for("login"))

    @app.route("/api/auth/check", methods=["GET"])
    def api_check_auth():

        if "user_id" in session:
            user = User.query.get(session["user_id"])
            if user:
                return jsonify({"authenticated": True, "user": user.to_dict()}), 200
        return jsonify({"authenticated": False, "user": None}), 200

    @app.route("/api/auth/config", methods=["GET"])
    def api_auth_config():

        from config import TURNSTILE_SITE_KEY, GOOGLE_CLIENT_ID

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

            turnstile_token = data.get("turnstile_response") or data.get(
                "cf-turnstile-response"
            )
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
                hashed_password = generate_password_hash(
                    password, method="pbkdf2:sha256"
                )
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
            confirmation_link = url_for(
                "confirm_email", token=confirmation_token, _external=True
            )
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
            turnstile_token = data.get("turnstile_response") or data.get(
                "cf-turnstile-response"
            )
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

            password_valid = False
            if user and user.password:
                try:
                    from argon2 import PasswordHasher
                    from argon2.exceptions import VerifyMismatchError, InvalidHashError

                    ph = PasswordHasher()
                    try:
                        ph.verify(user.password, password)
                        password_valid = True
                        if ph.check_needs_rehash(user.password):
                            user.password = ph.hash(password)
                            db.session.commit()
                    except (VerifyMismatchError, InvalidHashError):
                        if check_password_hash(user.password, password):
                            password_valid = True
                            user.password = ph.hash(password)
                            db.session.commit()
                except ImportError:
                    password_valid = check_password_hash(user.password, password)

            if not user or not password_valid:
                record_login_attempt(email, False)
                return jsonify({"error": "Неверный email или пароль"}), 401

            if not user.is_confirmed:
                return (
                    jsonify(
                        {"error": "Пожалуйста, подтвердите ваш email перед входом"}
                    ),
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
                settings.settings_data = json.dumps(
                    data["settings_data"], ensure_ascii=False
                )
            elif data:
                current_settings = settings.get_settings()
                for key, value in data.items():
                    if key not in ["theme", "language"]:
                        current_settings[key] = value
                settings.settings_data = json.dumps(
                    current_settings, ensure_ascii=False
                )

            settings.updated_at = datetime.utcnow()
            db.session.commit()

            return (
                jsonify(
                    {"message": "Настройки сохранены", "settings": settings.to_dict()}
                ),
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

        chat = UserChatHistory.query.filter_by(
            user_id=db_user_id, session_id=session_id
        ).first()

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
                            "sessionSlugIndex": user_settings.get(
                                "sessionSlugIndex", {}
                            ),
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

    from config import SECRET_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
    from sqlalchemy import event
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
                    # Some Windows ACL setups deny deleting journal files.
                    # Keep journaling/temp files in memory to avoid startup failures.
                    cursor.execute("PRAGMA journal_mode=MEMORY")
                    cursor.execute("PRAGMA temp_store=MEMORY")
                    cursor.execute("PRAGMA synchronous=NORMAL")
                    cursor.close()
                engine._remind_sqlite_pragmas = True

    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
        app.logger.info(
            f"Registering Google OAuth with client_id: {GOOGLE_CLIENT_ID[:20]}..."
        )
        google = oauth.register(
            name="google",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
            authorize_params={"access_type": "offline", "prompt": "consent"},
            jwks_uri="https://www.googleapis.com/oauth2/v3/certs",
        )
        app.logger.info("Google OAuth registered successfully")
    with app.app_context():
        db.create_all()
        app.logger.info("Database tables created successfully")
    register_auth_routes(app)
