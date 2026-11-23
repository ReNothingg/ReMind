from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlparse

import jwt
from authlib.integrations.base_client.errors import MismatchingStateError
from flask import (
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from backend.auth.accounts import (
    format_account_restriction_message,
    is_account_disabled,
    is_telegram_placeholder_email,
)
from backend.auth.apple import (
    APPLE_AUTH_CHALLENGE_TTL_SECONDS,
    APPLE_AUTHORIZE_URL,
    APPLE_OAUTH_BINDING_COOKIE,
    AppleAuthError,
    _apple_display_name,
    _apple_web_client_credentials_available,
    _consume_apple_auth_challenge,
    _consume_apple_token_replay,
    _decode_apple_web_binding,
    _encode_apple_web_binding,
    _exchange_apple_authorization_code,
    _find_or_create_apple_user,
    _issue_apple_auth_challenge,
    _link_apple_identity,
    _revoke_pending_apple_link_challenges,
    _sha256_text,
    _valid_apple_web_redirect_uri,
    _verify_apple_identity_token,
)
from backend.auth.credentials import _verify_user_password, is_valid_password, verify_turnstile
from backend.auth.identities import (
    AuthIdentityConflictError,
    _build_unique_username,
    _find_auth_identity,
    _link_auth_identity,
)
from backend.auth.oauth import (
    OAUTH_FALLBACK_STATE_COOKIE,
    OAUTH_FALLBACK_STATE_TTL_SECONDS,
    _append_url_query,
    _decode_oauth_fallback_state,
    _encode_mobile_google_oauth_token,
    _encode_oauth_fallback_state,
    _is_allowed_mobile_oauth_redirect_uri,
    _is_loopback_hostname,
    _normalize_redirect_target,
    _resolve_oauth_redirect_base,
    oauth,
)
from backend.db.models import User, db
from backend.responses import make_error
from backend.security.input_validation import InputValidator, ValidationError
from backend.security.rate_limiting import (
    login_limiter,
    rate_limit,
)
from backend.security.session_security import resolve_cookie_domain
from backend.services.mailer import send_email


def register_browser_routes(app):
    @app.before_request
    def enforce_authenticated_session_version():
        if request.endpoint == "static":
            return None
        user_id = session.get("user_id")
        if not user_id:
            return None
        user = db.session.get(User, user_id)
        if not user:
            session.clear()
            return None
        current_version = int(user.auth_version or 0)
        stored_version = session.get("_auth_version")
        if stored_version is None and current_version == 0:
            session["_auth_version"] = 0
            return None
        if stored_version != current_version:
            session.clear()
        return None

    @app.route("/register", methods=["GET", "POST"])
    def register():
        return redirect("/?auth=register", code=303 if request.method == "POST" else 302)

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
        from backend.security.audit_log import AuditEvents, log_auth_event
        from backend.security.brute_force import brute_force_protection, record_login_attempt
        from backend.security.session_security import regenerate_session

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
                from backend.config import TURNSTILE_SITE_KEY

                return render_template("login.html", turnstile_site_key=TURNSTILE_SITE_KEY)
            turnstile_response = request.form.get("cf-turnstile-response")
            if not verify_turnstile(turnstile_response):
                flash(
                    "Ошибка проверки Cloudflare Turnstile. Пожалуйста, подтвердите, что вы не робот.",
                    "danger",
                )
                from backend.config import TURNSTILE_SITE_KEY

                return render_template("login.html", turnstile_site_key=TURNSTILE_SITE_KEY)
            try:
                email = InputValidator.validate_email(email)
            except ValidationError:
                record_login_attempt(email, False)
                log_auth_event(AuditEvents.AUTH_LOGIN_FAILED, email, False, "invalid_email")
                flash("Неверный email или пароль", "danger")
                from backend.config import TURNSTILE_SITE_KEY

                return render_template("login.html", turnstile_site_key=TURNSTILE_SITE_KEY)

            user = User.query.filter_by(email=email).first()
            password_valid = _verify_user_password(user, password)

            if not user or not password_valid:
                record_login_attempt(email, False)
                log_auth_event(AuditEvents.AUTH_LOGIN_FAILED, email, False, "invalid_credentials")
                flash("Неверный email или пароль", "danger")
                from backend.config import TURNSTILE_SITE_KEY

                return render_template("login.html", turnstile_site_key=TURNSTILE_SITE_KEY)

            if is_account_disabled(user):
                record_login_attempt(email, False)
                log_auth_event(AuditEvents.AUTH_LOGIN_FAILED, email, False, "account_disabled")
                flash(format_account_restriction_message(user), "danger")
                from backend.config import TURNSTILE_SITE_KEY

                return render_template("login.html", turnstile_site_key=TURNSTILE_SITE_KEY)

            if not user.is_confirmed:
                log_auth_event(AuditEvents.AUTH_LOGIN_FAILED, email, False, "email_not_confirmed")
                flash("Пожалуйста, подтвердите ваш email перед входом", "warning")
                from backend.config import TURNSTILE_SITE_KEY

                return render_template("login.html", turnstile_site_key=TURNSTILE_SITE_KEY)
            record_login_attempt(email, True)
            log_auth_event(AuditEvents.AUTH_LOGIN_SUCCESS, email, True)
            session.clear()
            session["user_id"] = user.id
            session["username"] = InputValidator.sanitize_output(user.username)
            session["_auth_version"] = int(user.auth_version or 0)
            regenerate_session()

            if remember:
                session.permanent = True

            return redirect(url_for("good"))
        try:
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
                app.logger.warning("OAuth provider returned an error on /login")
                flash(
                    f"Ошибка авторизации: {oauth_error_description or oauth_error}",
                    "danger",
                )
        except Exception as _e:
            app.logger.debug(f"Failed to log login route args: {_e}")

        from backend.config import TURNSTILE_SITE_KEY

        return render_template("login.html", turnstile_site_key=TURNSTILE_SITE_KEY)

    @app.route("/good")
    def good():
        return redirect("/", code=303)

    @app.route("/forgot_password", methods=["GET", "POST"])
    def forgot_password():
        if request.method == "POST":
            email = request.form.get("email")
            user = User.query.filter_by(email=email).first()
            if user:
                reset_token = secrets.token_urlsafe(32)
                user.reset_token = reset_token
                user.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
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
            user.auth_version = int(user.auth_version or 0) + 1
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
        from backend.security.audit_log import AuditEvents, log_audit_event
        from backend.security.session_security import invalidate_session

        user_id = session.get("user_id")
        if user_id:
            _revoke_pending_apple_link_challenges(user_id)
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

        return redirect("/#settings/account", code=302)

    @app.route("/login/apple")
    @rate_limit(login_limiter, "Too many login attempts")
    def login_apple():
        from backend.config import (
            ALLOWED_HOSTS,
            APPLE_CLIENT_SECRET,
            APPLE_KEY_ID,
            APPLE_PRIVATE_KEY,
            APPLE_PRIVATE_KEY_PATH,
            APPLE_SERVICE_ID,
            APPLE_TEAM_ID,
            APPLE_WEB_REDIRECT_URI,
            SECRET_KEY,
            SESSION_COOKIE_DOMAIN,
        )

        callback_uri = _valid_apple_web_redirect_uri(
            APPLE_WEB_REDIRECT_URI,
            ALLOWED_HOSTS,
        )
        if not callback_uri or not _apple_web_client_credentials_available(
            service_id=APPLE_SERVICE_ID,
            client_secret=APPLE_CLIENT_SECRET,
            team_id=APPLE_TEAM_ID,
            key_id=APPLE_KEY_ID,
            private_key=APPLE_PRIVATE_KEY,
            private_key_path=APPLE_PRIVATE_KEY_PATH,
        ):
            return make_error(
                "apple_web_unavailable",
                status=503,
                code="apple_web_unavailable",
            )

        mode = "link" if request.args.get("mode") == "link" else "login"
        link_user_id = None
        if mode == "link":
            raw_user_id = session.get("user_id")
            link_user = db.session.get(User, raw_user_id) if raw_user_id else None
            if not link_user:
                return make_error("auth_required", status=401, code="auth_required")
            link_user_id = link_user.id

        redirect_candidate = request.args.get("redirect_to") or request.headers.get("Referer") or ""
        redirect_to = _normalize_redirect_target(redirect_candidate, ALLOWED_HOSTS)
        try:
            challenge, raw_nonce = _issue_apple_auth_challenge(
                flow="web",
                mode=mode,
                link_user_id=link_user_id,
                redirect_to=redirect_to,
            )
        except Exception as exc:
            db.session.rollback()
            app.logger.error("Apple web auth challenge creation failed (%s)", type(exc).__name__)
            return make_error(
                "apple_auth_unavailable",
                status=503,
                code="apple_auth_unavailable",
            )

        query = urlencode(
            {
                "client_id": APPLE_SERVICE_ID,
                "redirect_uri": callback_uri,
                "response_type": "code",
                "response_mode": "form_post",
                "scope": "name email",
                "state": challenge,
                "nonce": _sha256_text(raw_nonce),
            }
        )
        response = redirect(f"{APPLE_AUTHORIZE_URL}?{query}")
        cookie_domain = resolve_cookie_domain(SESSION_COOKIE_DOMAIN, request.host)
        response.set_cookie(
            APPLE_OAUTH_BINDING_COOKIE,
            _encode_apple_web_binding(SECRET_KEY, challenge),
            max_age=APPLE_AUTH_CHALLENGE_TTL_SECONDS,
            httponly=True,
            secure=True,
            samesite="None",
            domain=cookie_domain,
            path=url_for("authorize_apple"),
        )
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.route("/login/apple/callback", methods=["POST"])
    @rate_limit(login_limiter, "Too many login attempts")
    def authorize_apple():
        from backend.config import (
            ALLOWED_HOSTS,
            APPLE_CLIENT_SECRET,
            APPLE_KEY_ID,
            APPLE_PRIVATE_KEY,
            APPLE_PRIVATE_KEY_PATH,
            APPLE_SERVICE_ID,
            APPLE_TEAM_ID,
            APPLE_WEB_REDIRECT_URI,
            SECRET_KEY,
            SESSION_COOKIE_DOMAIN,
        )
        from backend.security.session_security import regenerate_session

        state = request.form.get("state", "")
        authorization_code = request.form.get("code", "")
        apple_error = request.form.get("error", "")
        metadata = None

        def finish_apple_redirect(location: str):
            if metadata and metadata.get("mode") == "link":
                try:
                    link_user = db.session.get(User, metadata.get("link_user_id"))
                    if link_user and not is_account_disabled(link_user):
                        session.clear()
                        session["user_id"] = link_user.id
                        session["username"] = InputValidator.sanitize_output(link_user.username)
                        session["_auth_version"] = int(link_user.auth_version or 0)
                        regenerate_session()
                        session.permanent = True
                except Exception as restore_exc:
                    db.session.rollback()
                    app.logger.error(
                        "Apple link session restoration failed (%s)",
                        type(restore_exc).__name__,
                    )
            response = redirect(location)
            cookie_domain = resolve_cookie_domain(SESSION_COOKIE_DOMAIN, request.host)
            response.delete_cookie(
                APPLE_OAUTH_BINDING_COOKIE,
                domain=cookie_domain,
                path=url_for("authorize_apple"),
                secure=True,
                samesite="None",
            )
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response

        try:
            bound_state = _decode_apple_web_binding(
                SECRET_KEY,
                request.cookies.get(APPLE_OAUTH_BINDING_COOKIE, ""),
            )
            if (
                not bound_state
                or not isinstance(state, str)
                or not secrets.compare_digest(bound_state, state)
            ):
                raise AppleAuthError("invalid_apple_web_binding")
            metadata = _consume_apple_auth_challenge(state, flow="web")
            if apple_error or not authorization_code:
                raise AppleAuthError("apple_authorization_cancelled")
            identity_token = _exchange_apple_authorization_code(
                authorization_code,
                client_id=APPLE_SERVICE_ID,
                redirect_uri=_valid_apple_web_redirect_uri(
                    APPLE_WEB_REDIRECT_URI,
                    ALLOWED_HOSTS,
                ),
                configured_secret=APPLE_CLIENT_SECRET,
                team_id=APPLE_TEAM_ID,
                key_id=APPLE_KEY_ID,
                private_key=APPLE_PRIVATE_KEY,
                private_key_path=APPLE_PRIVATE_KEY_PATH,
            )
            claims = _verify_apple_identity_token(
                identity_token,
                audience=APPLE_SERVICE_ID,
                expected_nonce_hash=metadata["nonce_hash"],
            )
            _consume_apple_token_replay(identity_token, claims)
            display_name = _apple_display_name(request.form.get("user"))

            if metadata["mode"] == "link":
                user = db.session.get(User, metadata["link_user_id"])
                if not user or is_account_disabled(user):
                    raise AppleAuthError("auth_required")
                _link_apple_identity(user, claims)
                return finish_apple_redirect("/?auth_link=apple_linked#settings/account")

            user = _find_or_create_apple_user(claims, display_name)
            if is_account_disabled(user):
                raise AppleAuthError("account_disabled")
            session.clear()
            session["user_id"] = user.id
            session["username"] = InputValidator.sanitize_output(user.username)
            session["_auth_version"] = int(user.auth_version or 0)
            regenerate_session()
            session.permanent = True
            return finish_apple_redirect(metadata["redirect_to"] or "/")
        except AuthIdentityConflictError as exc:
            db.session.rollback()
            result = "email_in_use" if str(exc) == "email_in_use" else "identity_in_use"
            if metadata and metadata.get("mode") == "link":
                return finish_apple_redirect(f"/?auth_link={result}#settings/account")
            return finish_apple_redirect(f"/?auth=login&auth_error={result}")
        except (AppleAuthError, jwt.PyJWTError, IntegrityError) as exc:
            db.session.rollback()
            app.logger.warning("Apple web authentication rejected (%s)", type(exc).__name__)
            if metadata and metadata.get("mode") == "link":
                return finish_apple_redirect("/?auth_link=apple_failed#settings/account")
            return finish_apple_redirect("/?auth=login&auth_error=apple_failed")
        except Exception as exc:
            db.session.rollback()
            app.logger.error("Apple web authentication failed (%s)", type(exc).__name__)
            if metadata and metadata.get("mode") == "link":
                return finish_apple_redirect("/?auth_link=apple_failed#settings/account")
            return finish_apple_redirect("/?auth=login&auth_error=apple_failed")

    @app.route("/login/google")
    def login_google():
        from backend.config import (
            ALLOWED_HOSTS,
            BACKEND_URL,
            IOS_OAUTH_REDIRECT_URI,
            SECRET_KEY,
            SESSION_COOKIE_DOMAIN,
        )

        link_requested = request.args.get("mode") == "link"
        link_user = None
        if link_requested:
            link_user_id = session.get("user_id")
            link_user = db.session.get(User, link_user_id) if link_user_id else None
            if not link_user:
                return make_error("auth_required", status=401, code="auth_required")
            session["oauth_link_user_id"] = link_user.id

        mobile_redirect_uri = ""
        mobile_requested = request.args.get("client") == "ios" or bool(
            request.args.get("mobile_redirect_uri")
        )
        if link_requested and mobile_requested:
            return make_error(
                "mobile_link_unsupported",
                status=400,
                code="mobile_link_unsupported",
            )
        if mobile_requested:
            mobile_redirect_uri = request.args.get("mobile_redirect_uri") or IOS_OAUTH_REDIRECT_URI
            if not _is_allowed_mobile_oauth_redirect_uri(
                mobile_redirect_uri, IOS_OAUTH_REDIRECT_URI
            ):
                return make_error(
                    "Invalid mobile OAuth redirect URI",
                    status=400,
                    code="invalid_mobile_oauth_redirect",
                )
            session["oauth_mobile_redirect_uri"] = mobile_redirect_uri
            safe_redirect_path = ""
        else:
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
                if mobile_redirect_uri:
                    fallback_payload["mobile_redirect_uri"] = mobile_redirect_uri
                if link_user:
                    fallback_payload["link_user_id"] = link_user.id
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
            app.logger.error("Failed to start Google OAuth redirect (%s)", type(exc).__name__)
            return make_error("Failed to start Google OAuth", status=500, code="oauth_start_failed")

    @app.route("/login/google/callback")
    def authorize_google():
        mobile_redirect_uri = None
        link_user_id = session.pop("oauth_link_user_id", None)
        try:
            app.logger.info("Processing Google OAuth callback")
            from backend.config import ALLOWED_HOSTS, SESSION_COOKIE_DOMAIN

            def finish_google_redirect(location: str):
                response = redirect(location)
                cookie_domain = resolve_cookie_domain(SESSION_COOKIE_DOMAIN, request.host)
                response.delete_cookie(
                    OAUTH_FALLBACK_STATE_COOKIE,
                    domain=cookie_domain,
                    path=url_for("authorize_google"),
                )
                return response

            redirect_to = session.pop("oauth_redirect_to", None)
            mobile_redirect_uri = session.pop("oauth_mobile_redirect_uri", None)
            try:
                app.logger.info("Attempting to exchange code for access token...")
                token = oauth.google.authorize_access_token()
                app.logger.debug("Token obtained successfully")
            except MismatchingStateError:
                from backend.config import SECRET_KEY

                app.logger.warning("OAuth state mismatch. Trying signed fallback state cookie.")
                fallback_state_raw = request.cookies.get(OAUTH_FALLBACK_STATE_COOKIE, "")
                fallback_state = _decode_oauth_fallback_state(SECRET_KEY, fallback_state_raw)
                request_state = request.args.get("state", "")
                request_code = request.args.get("code", "")
                fallback_state_value = str((fallback_state or {}).get("state", ""))
                fallback_redirect_uri = str((fallback_state or {}).get("redirect_uri", ""))
                fallback_mobile_redirect_uri = str(
                    (fallback_state or {}).get("mobile_redirect_uri", "")
                )
                fallback_link_user_id = (fallback_state or {}).get("link_user_id")
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
                    if not mobile_redirect_uri and fallback_mobile_redirect_uri:
                        mobile_redirect_uri = fallback_mobile_redirect_uri
                    if not link_user_id and isinstance(fallback_link_user_id, int):
                        link_user_id = fallback_link_user_id
                    token = oauth.google.fetch_access_token(
                        code=request_code,
                        redirect_uri=fallback_redirect_uri or request.base_url,
                    )
                    app.logger.debug("Token obtained successfully via fallback state cookie")
                else:
                    app.logger.error("Fallback state validation failed")
                    raise
            except Exception as token_err:
                app.logger.error("Failed to get Google access token (%s)", type(token_err).__name__)
                raise
            if not isinstance(token, dict) or not token.get("access_token"):
                app.logger.error(
                    "Google token exchange returned no access_token. "
                    f"Token keys: {list(token.keys()) if isinstance(token, dict) else type(token)}"
                )
                raise RuntimeError("google_oauth_missing_access_token")

            oauth.google.token = token
            resp = oauth.google.get("https://www.googleapis.com/oauth2/v3/userinfo", token=token)
            user_info = resp.json()
            app.logger.debug("Google user info obtained")
            if (
                not user_info.get("email")
                or not user_info.get("sub")
                or user_info.get("email_verified") is not True
            ):
                flash("Не удалось получить email из Google аккаунта", "danger")
                return redirect(url_for("login"))
            google_id = str(user_info["sub"])
            email = str(user_info["email"]).strip().lower()

            if link_user_id:
                user = db.session.get(User, link_user_id)
                if not user or session.get("user_id") != user.id:
                    app.logger.warning("Rejected Google link callback without matching session")
                    return finish_google_redirect("/?auth_link=auth_required#settings/account")

                linked_identity = _find_auth_identity("google", google_id)
                if linked_identity and linked_identity.user_id != user.id:
                    return finish_google_redirect("/?auth_link=identity_in_use#settings/account")

                email_owner = User.query.filter(func.lower(User.email) == email).first()
                if email_owner and email_owner.id != user.id:
                    return finish_google_redirect("/?auth_link=email_in_use#settings/account")

                try:
                    _link_auth_identity(user, "google", google_id)
                except AuthIdentityConflictError:
                    db.session.rollback()
                    return finish_google_redirect("/?auth_link=identity_in_use#settings/account")
                if is_telegram_placeholder_email(user):
                    user.email = email
                user.is_confirmed = True
                if not user.name:
                    user.name = (
                        user_info.get("name") or user_info.get("given_name") or user.username
                    )
                db.session.commit()
                return finish_google_redirect("/?auth_link=google_linked#settings/account")

            identity = _find_auth_identity("google", google_id)
            user = identity.user if identity else None
            if not user:
                user = User.query.filter(func.lower(User.email) == email).first()

            if not user:
                account_name = (
                    user_info.get("name") or user_info.get("given_name") or email.split("@")[0]
                )
                username = _build_unique_username(
                    user_info.get("preferred_username"),
                    user_info.get("given_name"),
                    user_info.get("name"),
                    email.split("@")[0],
                )
                new_user = User(
                    username=username,
                    name=account_name,
                    email=email,
                    is_confirmed=True,
                    oauth_provider="google",
                    oauth_id=google_id,
                )
                db.session.add(new_user)
                db.session.flush()
                _link_auth_identity(new_user, "google", google_id)
                db.session.commit()
                user = new_user
                flash("Аккаунт создан с помощью Google авторизации", "success")
            else:
                _link_auth_identity(user, "google", google_id)
                user.is_confirmed = True
                if not user.name:
                    user.name = (
                        user_info.get("name") or user_info.get("given_name") or user.username
                    )
                db.session.commit()
                if not identity:
                    flash("Ваш аккаунт связан с Google", "success")

            if mobile_redirect_uri:
                from backend.config import IOS_OAUTH_REDIRECT_URI, SECRET_KEY, SESSION_COOKIE_DOMAIN

                if not _is_allowed_mobile_oauth_redirect_uri(
                    mobile_redirect_uri, IOS_OAUTH_REDIRECT_URI
                ):
                    app.logger.warning("Blocked Google mobile OAuth callback redirect")
                    return redirect(url_for("login"))

                mobile_token = _encode_mobile_google_oauth_token(SECRET_KEY, user.id)
                response = redirect(_append_url_query(mobile_redirect_uri, {"token": mobile_token}))
                cookie_domain = resolve_cookie_domain(SESSION_COOKIE_DOMAIN, request.host)
                response.delete_cookie(
                    OAUTH_FALLBACK_STATE_COOKIE,
                    domain=cookie_domain,
                    path=url_for("authorize_google"),
                )
                return response

            from backend.security.session_security import regenerate_session

            session.clear()
            session["user_id"] = user.id
            session["username"] = InputValidator.sanitize_output(user.username)
            session["_auth_version"] = int(user.auth_version or 0)
            regenerate_session()
            session.permanent = True
            from backend.config import SESSION_COOKIE_DOMAIN

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
            db.session.rollback()
            app.logger.error("OAuth error in authorize_google() (%s)", type(e).__name__)
            flash("Ошибка при входе через Google", "danger")
            if link_user_id:
                from backend.config import SESSION_COOKIE_DOMAIN

                response = redirect("/?auth_link=google_failed#settings/account")
                cookie_domain = resolve_cookie_domain(SESSION_COOKIE_DOMAIN, request.host)
                response.delete_cookie(
                    OAUTH_FALLBACK_STATE_COOKIE,
                    domain=cookie_domain,
                    path=url_for("authorize_google"),
                )
                return response
            if mobile_redirect_uri:
                response = redirect(
                    _append_url_query(mobile_redirect_uri, {"error": "oauth_failed"})
                )
                from backend.config import SESSION_COOKIE_DOMAIN

                cookie_domain = resolve_cookie_domain(SESSION_COOKIE_DOMAIN, request.host)
                response.delete_cookie(
                    OAUTH_FALLBACK_STATE_COOKIE,
                    domain=cookie_domain,
                    path=url_for("authorize_google"),
                )
                return response

            response = redirect(url_for("login"))
            from backend.config import SESSION_COOKIE_DOMAIN

            cookie_domain = resolve_cookie_domain(SESSION_COOKIE_DOMAIN, request.host)
            response.delete_cookie(
                OAUTH_FALLBACK_STATE_COOKIE,
                domain=cookie_domain,
                path=url_for("authorize_google"),
            )
            return response
