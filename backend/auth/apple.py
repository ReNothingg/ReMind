from __future__ import annotations

import hashlib
import json
import re
import secrets
import unicodedata
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import jwt
import requests
from itsdangerous import BadData, URLSafeTimedSerializer
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from backend.auth.identities import (
    AuthIdentityConflictError,
    _build_unique_username,
    _discard_orphan_auth_identity,
    _find_auth_identity,
    _link_auth_identity,
)
from backend.auth.oauth import _is_allowed_hostname
from backend.db.models import AppleAuthChallenge, AppleTokenReplay, User, UserSettings, db
from backend.security.input_validation import InputValidator, ValidationError

APPLE_ISSUER = "https://appleid.apple.com"


APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"


APPLE_AUTHORIZE_URL = "https://appleid.apple.com/auth/authorize"


APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"


APPLE_AUTH_CHALLENGE_TTL_SECONDS = 600


APPLE_ID_TOKEN_MAX_LENGTH = 16_384


APPLE_TOKEN_MAX_AGE_SECONDS = 86_400


APPLE_ALLOWED_SIGNING_ALGORITHMS = ("RS256",)


APPLE_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


APPLE_SUBJECT_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


APPLE_OAUTH_BINDING_COOKIE = "__Secure-remind_apple_oauth"


_apple_jwks_client = None


class AppleAuthError(ValueError):
    pass


class AppleNonceMismatchError(jwt.InvalidTokenError):
    pass


class AppleReplayError(jwt.InvalidTokenError):
    pass


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _valid_apple_web_redirect_uri(
    raw_value: str | None,
    allowed_hosts: Any = None,
) -> str:
    candidate = str(raw_value or "").strip()
    parsed = urlparse(candidate)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path != "/login/apple/callback"
        or parsed.params
        or parsed.query
        or parsed.fragment
        or (allowed_hosts is not None and not _is_allowed_hostname(parsed.hostname, allowed_hosts))
    ):
        return ""
    return candidate


def _apple_web_client_credentials_available(
    *,
    service_id: str,
    client_secret: str,
    team_id: str,
    key_id: str,
    private_key: str,
    private_key_path: str,
) -> bool:
    if not service_id or not re.fullmatch(r"[A-Za-z0-9.-]{3,255}", service_id):
        return False
    if client_secret:
        return len(client_secret) <= 8_192
    return bool(
        re.fullmatch(r"[A-Z0-9]{10}", team_id or "")
        and re.fullmatch(r"[A-Z0-9]{10}", key_id or "")
        and (private_key or private_key_path)
    )


def _read_apple_private_key(raw_key: str, key_path: str) -> str:
    candidate = str(raw_key or "").replace("\\n", "\n").strip()
    if not candidate and key_path:
        from pathlib import Path

        path = Path(key_path).expanduser()
        if not path.is_file() or path.stat().st_size > 65_536:
            raise AppleAuthError("apple_client_secret_unavailable")
        candidate = path.read_text(encoding="utf-8").strip()
    if (
        not candidate.startswith("-----BEGIN PRIVATE KEY-----")
        or not candidate.endswith("-----END PRIVATE KEY-----")
        or len(candidate) > 65_536
    ):
        raise AppleAuthError("apple_client_secret_unavailable")
    return candidate


def _apple_client_secret(
    *,
    client_id: str,
    configured_secret: str,
    team_id: str,
    key_id: str,
    private_key: str,
    private_key_path: str,
) -> str:
    if configured_secret:
        if len(configured_secret) > 8_192:
            raise AppleAuthError("apple_client_secret_unavailable")
        return configured_secret
    if not re.fullmatch(r"[A-Z0-9]{10}", team_id or "") or not re.fullmatch(
        r"[A-Z0-9]{10}", key_id or ""
    ):
        raise AppleAuthError("apple_client_secret_unavailable")
    now = int(datetime.now().timestamp())
    return jwt.encode(
        {
            "iss": team_id,
            "iat": now,
            "exp": now + 600,
            "aud": APPLE_ISSUER,
            "sub": client_id,
        },
        _read_apple_private_key(private_key, private_key_path),
        algorithm="ES256",
        headers={"kid": key_id},
    )


def _exchange_apple_authorization_code(
    code: str,
    *,
    client_id: str,
    redirect_uri: str,
    configured_secret: str,
    team_id: str,
    key_id: str,
    private_key: str,
    private_key_path: str,
) -> str:
    if not isinstance(code, str) or not code or len(code) > 4_096:
        raise AppleAuthError("invalid_apple_authorization_code")
    client_secret = _apple_client_secret(
        client_id=client_id,
        configured_secret=configured_secret,
        team_id=team_id,
        key_id=key_id,
        private_key=private_key,
        private_key_path=private_key_path,
    )
    try:
        response = requests.post(
            APPLE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
            timeout=10,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise AppleAuthError("apple_token_exchange_unavailable") from exc
    if response.status_code != 200:
        raise AppleAuthError("apple_authorization_code_rejected")
    try:
        payload = response.json()
    except ValueError as exc:
        raise AppleAuthError("apple_token_exchange_unavailable") from exc
    identity_token = payload.get("id_token") if isinstance(payload, dict) else None
    if (
        not isinstance(identity_token, str)
        or not identity_token
        or len(identity_token) > APPLE_ID_TOKEN_MAX_LENGTH
    ):
        raise AppleAuthError("apple_token_exchange_unavailable")
    return identity_token


def _apple_web_binding_serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="apple-web-oauth-binding")


def _encode_apple_web_binding(secret_key: str, challenge: str) -> str:
    return _apple_web_binding_serializer(secret_key).dumps(
        {"aud": "remind-apple-web", "challenge": challenge}
    )


def _decode_apple_web_binding(secret_key: str, token: str) -> str | None:
    if not secret_key or not token:
        return None
    try:
        payload = _apple_web_binding_serializer(secret_key).loads(
            token, max_age=APPLE_AUTH_CHALLENGE_TTL_SECONDS
        )
    except BadData:
        return None
    if not isinstance(payload, dict) or payload.get("aud") != "remind-apple-web":
        return None
    challenge = payload.get("challenge")
    return challenge if isinstance(challenge, str) else None


def _issue_apple_auth_challenge(
    *,
    flow: str,
    mode: str,
    link_user_id: int | None = None,
    redirect_to: str = "",
) -> tuple[str, str]:
    if flow not in {"native", "web"} or mode not in {"login", "link"}:
        raise AppleAuthError("invalid_apple_auth_flow")
    if mode == "link" and not link_user_id:
        raise AppleAuthError("auth_required")

    now = datetime.utcnow()
    AppleAuthChallenge.query.filter(AppleAuthChallenge.expires_at <= now).delete(
        synchronize_session=False
    )
    AppleTokenReplay.query.filter(AppleTokenReplay.expires_at <= now).delete(
        synchronize_session=False
    )

    challenge = secrets.token_urlsafe(32)
    raw_nonce = secrets.token_urlsafe(32)
    record = AppleAuthChallenge(
        challenge_hash=_sha256_text(challenge),
        nonce_hash=_sha256_text(raw_nonce),
        flow=flow,
        mode=mode,
        link_user_id=link_user_id,
        redirect_to=(redirect_to or "")[:500],
        expires_at=now + timedelta(seconds=APPLE_AUTH_CHALLENGE_TTL_SECONDS),
    )
    db.session.add(record)
    db.session.commit()
    return challenge, raw_nonce


def _consume_apple_auth_challenge(challenge: str, *, flow: str) -> dict[str, Any]:
    normalized = str(challenge or "").strip()
    if flow not in {"native", "web"} or not APPLE_CHALLENGE_RE.fullmatch(normalized):
        raise AppleAuthError("invalid_or_expired_challenge")

    now = datetime.utcnow()
    record = AppleAuthChallenge.query.filter_by(
        challenge_hash=_sha256_text(normalized),
        flow=flow,
    ).first()
    if not record or record.consumed_at is not None or record.expires_at <= now:
        raise AppleAuthError("invalid_or_expired_challenge")

    snapshot = {
        "nonce_hash": record.nonce_hash,
        "mode": record.mode,
        "link_user_id": record.link_user_id,
        "redirect_to": record.redirect_to or "",
    }
    updated = AppleAuthChallenge.query.filter(
        AppleAuthChallenge.id == record.id,
        AppleAuthChallenge.consumed_at.is_(None),
        AppleAuthChallenge.expires_at > now,
    ).update({"consumed_at": now}, synchronize_session=False)
    if updated != 1:
        db.session.rollback()
        raise AppleAuthError("invalid_or_expired_challenge")
    db.session.commit()
    return snapshot


def _revoke_pending_apple_link_challenges(user_id: int | None) -> None:
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        return
    AppleAuthChallenge.query.filter(
        AppleAuthChallenge.link_user_id == user_id,
        AppleAuthChallenge.mode == "link",
        AppleAuthChallenge.consumed_at.is_(None),
    ).delete(synchronize_session=False)
    db.session.commit()


def _get_apple_jwks_client():
    global _apple_jwks_client
    if _apple_jwks_client is None:
        _apple_jwks_client = jwt.PyJWKClient(
            APPLE_JWKS_URL,
            cache_keys=True,
            cache_jwk_set=True,
            lifespan=300,
            timeout=5,
        )
    return _apple_jwks_client


def _apple_subject(claims: dict) -> str:
    subject = str(claims.get("sub") or "").strip()
    if not APPLE_SUBJECT_RE.fullmatch(subject):
        raise jwt.InvalidTokenError("Invalid Apple subject")
    return subject


def _verify_apple_identity_token(
    id_token: str,
    *,
    audience: str,
    expected_nonce_hash: str,
) -> dict:
    if not isinstance(id_token, str) or not id_token or len(id_token) > APPLE_ID_TOKEN_MAX_LENGTH:
        raise jwt.InvalidTokenError("Invalid Apple identity token")
    if not audience:
        raise jwt.InvalidAudienceError("Apple audience is not configured")

    unverified_header = jwt.get_unverified_header(id_token)
    algorithm = unverified_header.get("alg")
    key_id = unverified_header.get("kid")
    if algorithm not in APPLE_ALLOWED_SIGNING_ALGORITHMS:
        raise jwt.InvalidAlgorithmError("Unsupported Apple signing algorithm")
    if not isinstance(key_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", key_id):
        raise jwt.InvalidTokenError("Invalid Apple signing key identifier")

    signing_key = _get_apple_jwks_client().get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        key=signing_key.key,
        algorithms=list(APPLE_ALLOWED_SIGNING_ALGORITHMS),
        audience=audience,
        issuer=APPLE_ISSUER,
        leeway=30,
        options={"require": ["aud", "exp", "iat", "iss", "nonce", "sub"]},
    )

    token_audience = claims.get("aud")
    if not isinstance(token_audience, str) or not secrets.compare_digest(token_audience, audience):
        raise jwt.InvalidAudienceError("Invalid Apple audience")

    now = int(datetime.now().timestamp())
    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    if (
        isinstance(issued_at, bool)
        or not isinstance(issued_at, int)
        or isinstance(expires_at, bool)
        or not isinstance(expires_at, int)
        or issued_at > now + 30
        or now - issued_at > APPLE_TOKEN_MAX_AGE_SECONDS
        or expires_at <= issued_at
        or expires_at - issued_at > APPLE_TOKEN_MAX_AGE_SECONDS
    ):
        raise jwt.InvalidTokenError("Invalid Apple token lifetime")

    token_nonce = claims.get("nonce")
    if (
        not isinstance(token_nonce, str)
        or not re.fullmatch(r"[a-f0-9]{64}", token_nonce)
        or not secrets.compare_digest(token_nonce, expected_nonce_hash)
    ):
        raise AppleNonceMismatchError("Invalid Apple login nonce")
    _apple_subject(claims)
    return claims


def _consume_apple_token_replay(id_token: str, claims: dict) -> None:
    token_hash = hashlib.sha256(id_token.encode("utf-8")).hexdigest()
    expires_at = datetime.utcfromtimestamp(int(claims["exp"]))
    db.session.add(AppleTokenReplay(token_hash=token_hash, expires_at=expires_at))
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise AppleReplayError("Apple identity token was already used") from exc


def _apple_email_is_verified(claims: dict) -> bool:
    value = claims.get("email_verified")
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _clean_apple_profile_name(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = "".join(char for char in value.strip() if unicodedata.category(char)[0] != "C")
    return cleaned[:100] or fallback


def _find_or_create_apple_user(claims: dict, display_name: str | None = None) -> User:
    subject = _apple_subject(claims)
    identity = _discard_orphan_auth_identity(_find_auth_identity("apple", subject))
    user = identity.user if identity else None
    if not user:
        user = User.query.filter_by(oauth_provider="apple", oauth_id=subject).first()
    if user:
        _link_auth_identity(user, "apple", subject)
        if not user.name and display_name:
            user.name = _clean_apple_profile_name(display_name, user.username)
        db.session.commit()
        return user

    raw_email = claims.get("email")
    if (
        not isinstance(raw_email, str)
        or not raw_email.strip()
        or not _apple_email_is_verified(claims)
    ):
        raise AppleAuthError("apple_email_required")
    try:
        email = InputValidator.validate_email(raw_email.strip().lower())
    except ValidationError as exc:
        raise AppleAuthError("apple_email_required") from exc
    if User.query.filter(func.lower(User.email) == email.lower()).first():
        raise AuthIdentityConflictError("email_in_use")

    email_prefix = email.split("@", 1)[0]
    username = _build_unique_username(email_prefix, display_name, f"apple_{subject[-8:]}")
    account_name = _clean_apple_profile_name(display_name, username)
    user = User(
        username=username,
        name=account_name,
        email=email,
        password=None,
        is_confirmed=True,
        oauth_provider="apple",
        oauth_id=subject,
    )
    db.session.add(user)
    db.session.flush()
    _link_auth_identity(user, "apple", subject)
    db.session.add(UserSettings(user_id=user.id))
    db.session.commit()
    return user


def _link_apple_identity(user: User, claims: dict) -> User:
    _link_auth_identity(user, "apple", _apple_subject(claims))
    db.session.commit()
    return user


def _apple_display_name(raw_value: Any) -> str | None:
    if isinstance(raw_value, str):
        value = raw_value
        if len(value) > 4_096:
            return None
        try:
            raw_value = json.loads(value)
        except (TypeError, ValueError):
            return _clean_apple_profile_name(value, "") or None
    if not isinstance(raw_value, dict):
        return None
    raw_name = raw_value.get("name")
    name = raw_name if isinstance(raw_name, dict) else raw_value
    parts = [
        name.get("firstName") or name.get("first_name"),
        name.get("middleName") or name.get("middle_name"),
        name.get("lastName") or name.get("last_name"),
    ]
    combined = " ".join(
        part.strip()[:100] for part in parts if isinstance(part, str) and part.strip()
    )
    return _clean_apple_profile_name(combined, "") or None
