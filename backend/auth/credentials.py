from __future__ import annotations

import hashlib
import hmac
import re

import requests
from flask import (
    current_app,
    request,
)
from werkzeug.security import check_password_hash

from backend.db.models import db

PASSWORD_RESET_CODE_TTL_SECONDS = 600


PASSWORD_RESET_CODE_MAX_ATTEMPTS = 5


PASSWORD_RESET_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{24}$")


PASSWORD_RESET_CODE_RE = re.compile(r"^\d{6}$")


def _password_reset_code_hash(request_id: str, code: str) -> str:
    secret = str(current_app.config["SECRET_KEY"]).encode("utf-8")
    payload = f"{request_id}:{code}".encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


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


def verify_turnstile(turnstile_response):

    from flask import current_app

    from backend.config import LOCALHOST_MODE, TURNSTILE_SECRET_KEY, TURNSTILE_VERIFY_URL

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
