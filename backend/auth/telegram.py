from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from datetime import datetime
from typing import Any

import jwt
from flask import session
from sqlalchemy.exc import IntegrityError

from backend.auth.accounts import (
    TELEGRAM_BOT_USER_ID_MAX,
    _telegram_placeholder_email,
    is_account_disabled,
)
from backend.auth.identities import (
    AuthIdentityConflictError,
    _build_unique_username,
    _discard_orphan_auth_identity,
    _find_auth_identity,
    _link_auth_identity,
)
from backend.db.models import AuthIdentity, TelegramLinkRequest, User, UserSettings, db

TELEGRAM_ISSUER = "https://oauth.telegram.org"


TELEGRAM_JWKS_URL = "https://oauth.telegram.org/.well-known/jwks.json"


TELEGRAM_LOGIN_NONCE_SESSION_KEY = "telegram_login_nonce"


TELEGRAM_LOGIN_NONCE_TTL_SECONDS = 600


TELEGRAM_ID_TOKEN_MAX_LENGTH = 16_384


TELEGRAM_ALLOWED_SIGNING_ALGORITHMS = ("RS256", "ES256")


TELEGRAM_LINK_TOKEN_TTL_SECONDS = 600


TELEGRAM_LINK_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32}$")


TELEGRAM_LINK_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{24}$")


_telegram_jwks_client = None


class TelegramNonceMismatchError(jwt.InvalidTokenError):
    pass


class TelegramSubjectError(jwt.InvalidTokenError):
    pass


def _telegram_link_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _fail_telegram_link_request(request_id: int, code: str, now: datetime) -> str:
    db.session.rollback()
    link_request = db.session.get(TelegramLinkRequest, request_id)
    if link_request and link_request.consumed_at is None:
        link_request.consumed_at = now
        link_request.failure_code = code
        db.session.commit()
    return code


def consume_telegram_link_token(token: str, telegram_user_id: str) -> str:

    normalized_token = str(token or "").strip()
    normalized_telegram_id = str(telegram_user_id or "").strip()
    if not TELEGRAM_LINK_TOKEN_RE.fullmatch(normalized_token):
        return "invalid"
    if not re.fullmatch(r"[0-9]{1,16}", normalized_telegram_id):
        return "invalid"
    if not 1 <= int(normalized_telegram_id) <= TELEGRAM_BOT_USER_ID_MAX:
        return "invalid"

    link_request = (
        TelegramLinkRequest.query.filter_by(token_hash=_telegram_link_token_hash(normalized_token))
        .with_for_update()
        .first()
    )
    now = datetime.utcnow()
    if not link_request or link_request.consumed_at is not None:
        return "invalid"
    if link_request.expires_at <= now:
        return "expired"
    link_request_id = link_request.id

    user = db.session.get(User, link_request.user_id)
    if not user or is_account_disabled(user):
        return _fail_telegram_link_request(link_request_id, "restricted", now)
    try:
        current_identity = AuthIdentity.query.filter_by(
            user_id=user.id, provider="telegram"
        ).first()
        if current_identity and not secrets.compare_digest(
            current_identity.provider_user_id, normalized_telegram_id
        ):
            current_value = str(current_identity.provider_user_id or "").strip()
            if re.fullmatch(r"[0-9]{1,16}", current_value):
                return _fail_telegram_link_request(link_request_id, "already_linked", now)
            claimed_identity = _discard_orphan_auth_identity(
                _find_auth_identity("telegram", normalized_telegram_id)
            )
            if claimed_identity and claimed_identity.user_id != user.id:
                return _fail_telegram_link_request(link_request_id, "identity_in_use", now)
            previous_value = current_identity.provider_user_id
            current_identity.provider_user_id = normalized_telegram_id
            if user.oauth_provider == "telegram" and user.oauth_id == previous_value:
                user.oauth_id = normalized_telegram_id
        else:
            _link_auth_identity(user, "telegram", normalized_telegram_id)
        link_request.consumed_at = now
        db.session.commit()
    except AuthIdentityConflictError as exc:
        code = str(exc)
        if code == "auth_identity_in_use":
            return _fail_telegram_link_request(link_request_id, "identity_in_use", now)
        if code == "auth_provider_already_linked":
            return _fail_telegram_link_request(link_request_id, "already_linked", now)
        return _fail_telegram_link_request(link_request_id, "invalid", now)
    except IntegrityError:
        return _fail_telegram_link_request(link_request_id, "identity_in_use", now)
    return "linked"


def _issue_telegram_login_nonce() -> str:
    existing_nonce = _current_telegram_login_nonce()
    if existing_nonce:
        return existing_nonce

    nonce = secrets.token_urlsafe(32)
    session[TELEGRAM_LOGIN_NONCE_SESSION_KEY] = {
        "value": nonce,
        "issued_at": int(datetime.utcnow().timestamp()),
    }
    session.modified = True
    return nonce


def _current_telegram_login_nonce() -> str | None:
    payload = session.get(TELEGRAM_LOGIN_NONCE_SESSION_KEY)
    if not isinstance(payload, dict):
        return None

    nonce = payload.get("value")
    issued_at = payload.get("issued_at")
    if not isinstance(nonce, str) or not nonce or not isinstance(issued_at, int):
        return None

    now = int(datetime.utcnow().timestamp())
    if issued_at > now + 60 or now - issued_at > TELEGRAM_LOGIN_NONCE_TTL_SECONDS:
        session.pop(TELEGRAM_LOGIN_NONCE_SESSION_KEY, None)
        return None
    return nonce


def _get_telegram_jwks_client():
    global _telegram_jwks_client
    if _telegram_jwks_client is None:
        _telegram_jwks_client = jwt.PyJWKClient(
            TELEGRAM_JWKS_URL,
            cache_keys=True,
            cache_jwk_set=True,
            lifespan=300,
            timeout=5,
        )
    return _telegram_jwks_client


def _verify_telegram_id_token(id_token: str, client_id: str, expected_nonce: str) -> dict:
    unverified_header = jwt.get_unverified_header(id_token)
    algorithm = unverified_header.get("alg")
    if algorithm not in TELEGRAM_ALLOWED_SIGNING_ALGORITHMS:
        raise jwt.InvalidAlgorithmError("Unsupported Telegram signing algorithm")

    signing_key = _get_telegram_jwks_client().get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        key=signing_key.key,
        algorithms=list(TELEGRAM_ALLOWED_SIGNING_ALGORITHMS),
        audience=client_id,
        issuer=TELEGRAM_ISSUER,
        leeway=30,
        options={
            "require": ["aud", "exp", "iat", "iss", "nonce", "sub"],
        },
    )

    token_nonce = claims.get("nonce")
    if not isinstance(token_nonce, str) or not secrets.compare_digest(token_nonce, expected_nonce):
        raise TelegramNonceMismatchError("Invalid Telegram login nonce")

    _telegram_oidc_subject(claims)
    if claims.get("id") is not None:
        _telegram_bot_user_id(claims)

    return claims


def _telegram_oidc_subject(claims: dict) -> str:
    subject = str(claims.get("sub") or "").strip()
    if not re.fullmatch(r"[0-9]{1,32}", subject):
        raise TelegramSubjectError("Invalid Telegram subject")
    return subject


def _telegram_bot_user_id(claims: dict) -> str:
    raw_user_id = claims.get("id")
    if isinstance(raw_user_id, bool):
        raise TelegramSubjectError("Invalid Telegram user ID")
    user_id = str(raw_user_id or "").strip()
    if not re.fullmatch(r"[0-9]{1,16}", user_id):
        raise TelegramSubjectError("Invalid Telegram user ID")
    numeric_user_id = int(user_id)
    if numeric_user_id < 1 or numeric_user_id > TELEGRAM_BOT_USER_ID_MAX:
        raise TelegramSubjectError("Invalid Telegram user ID")
    return user_id


def _telegram_provider_user_id(claims: dict) -> str:
    if claims.get("id") is not None:
        return _telegram_bot_user_id(claims)
    return _telegram_oidc_subject(claims)


def _sync_telegram_identity(user: User, claims: dict) -> AuthIdentity:
    subject = _telegram_oidc_subject(claims)
    telegram_user_id = _telegram_provider_user_id(claims)
    current_identity = AuthIdentity.query.filter_by(
        user_id=user.id,
        provider="telegram",
    ).first()
    claimed_identity = _discard_orphan_auth_identity(
        _find_auth_identity("telegram", telegram_user_id)
    )

    if claimed_identity and claimed_identity.user_id != user.id:
        raise AuthIdentityConflictError("auth_identity_in_use")
    if current_identity and current_identity.provider_user_id not in {
        subject,
        telegram_user_id,
    }:
        raise AuthIdentityConflictError("auth_provider_already_linked")

    identity = claimed_identity or current_identity
    if identity:
        identity.provider_user_id = telegram_user_id
    else:
        identity = _link_auth_identity(user, "telegram", telegram_user_id)

    if user.oauth_provider == "telegram" and user.oauth_id in {subject, telegram_user_id}:
        user.oauth_id = telegram_user_id
    legacy_email = _telegram_placeholder_email(subject)
    if subject != telegram_user_id and user.email == legacy_email:
        user.email = _telegram_placeholder_email(telegram_user_id)
    return identity


def _clean_telegram_profile_name(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = "".join(char for char in value.strip() if unicodedata.category(char)[0] != "C")
    return cleaned[:100] or fallback


def _find_or_create_telegram_user(claims: dict) -> User:
    subject = _telegram_oidc_subject(claims)
    telegram_user_id = _telegram_provider_user_id(claims)
    identity = _discard_orphan_auth_identity(_find_auth_identity("telegram", telegram_user_id))
    if not identity and subject != telegram_user_id:
        identity = _discard_orphan_auth_identity(_find_auth_identity("telegram", subject))
    user = identity.user if identity else None
    if not user:
        user = User.query.filter_by(oauth_provider="telegram", oauth_id=telegram_user_id).first()
    if not user and subject != telegram_user_id:
        user = User.query.filter_by(oauth_provider="telegram", oauth_id=subject).first()
    if user:
        _sync_telegram_identity(user, claims)
        if not user.name:
            user.name = _clean_telegram_profile_name(claims.get("name"), user.username)
        db.session.commit()
        return user

    username = _build_unique_username(
        claims.get("preferred_username"),
        claims.get("given_name"),
        claims.get("name"),
        f"telegram_{telegram_user_id[-8:]}",
    )
    account_name = _clean_telegram_profile_name(claims.get("name"), username)
    placeholder_email = _telegram_placeholder_email(telegram_user_id)
    user = User(
        username=username,
        name=account_name,
        email=placeholder_email,
        password=None,
        is_confirmed=True,
        oauth_provider="telegram",
        oauth_id=telegram_user_id,
    )

    try:
        db.session.add(user)
        db.session.flush()
        _sync_telegram_identity(user, claims)
        db.session.add(UserSettings(user_id=user.id))
        db.session.commit()
        return user
    except IntegrityError:
        db.session.rollback()
        raced_identity = _find_auth_identity("telegram", telegram_user_id)
        if raced_identity:
            return raced_identity.user
        raise
