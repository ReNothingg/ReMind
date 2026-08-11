import hashlib
import json
import os
import re
import secrets
import unicodedata
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import jwt
import requests
from authlib.integrations.base_client.errors import MismatchingStateError
from authlib.integrations.flask_client import OAuth
from flask import (
    Response,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from itsdangerous import BadData, URLSafeTimedSerializer
from sqlalchemy import bindparam, func, inspect, text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from .input_validation import InputValidator, ValidationError
from .mailer import send_email
from .rate_limiting import login_limiter, rate_limit
from .responses import make_error
from .session_security import is_loopback_hostname, resolve_cookie_domain

db: Any = SQLAlchemy()
oauth = OAuth()
OAUTH_FALLBACK_STATE_COOKIE = "oauth_state_fallback"
OAUTH_FALLBACK_STATE_TTL_SECONDS = 900
MOBILE_GOOGLE_OAUTH_TOKEN_TTL_SECONDS = 180
DEFAULT_ROOT_ADMIN_USER_IDS = frozenset({1})
REMOVED_SETTINGS_DATA_KEYS = frozenset(
    {
        "personalization_nickname",
        "autocomplete",
        "autoscroll",
        "renderUserMarkdown",
        "autoSave",
    }
)
CHAT_SESSION_UNIQUE_INDEX = "uq_user_chat_history_user_session"
TELEGRAM_ISSUER = "https://oauth.telegram.org"
TELEGRAM_JWKS_URL = "https://oauth.telegram.org/.well-known/jwks.json"
TELEGRAM_LOGIN_NONCE_SESSION_KEY = "telegram_login_nonce"
TELEGRAM_LOGIN_NONCE_TTL_SECONDS = 600
TELEGRAM_ID_TOKEN_MAX_LENGTH = 16_384
TELEGRAM_ALLOWED_SIGNING_ALGORITHMS = ("RS256", "ES256")
TELEGRAM_BOT_USER_ID_MAX = (1 << 52) - 1
TELEGRAM_LINK_TOKEN_TTL_SECONDS = 600
TELEGRAM_LINK_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32}$")
TELEGRAM_LINK_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{24}$")
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
SUPPORTED_AUTH_PROVIDERS = frozenset({"apple", "google", "telegram"})
_telegram_jwks_client = None
_apple_jwks_client = None


class TelegramNonceMismatchError(jwt.InvalidTokenError):
    pass


class TelegramSubjectError(jwt.InvalidTokenError):
    pass


class AuthIdentityConflictError(ValueError):
    pass


class AppleAuthError(ValueError):
    pass


class AppleNonceMismatchError(jwt.InvalidTokenError):
    pass


class AppleReplayError(jwt.InvalidTokenError):
    pass


def sanitize_settings_data(raw_settings: Any) -> dict[str, Any]:
    if not isinstance(raw_settings, dict):
        return {}
    return {
        key: value for key, value in raw_settings.items() if key not in REMOVED_SETTINGS_DATA_KEYS
    }


def ensure_chat_session_uniqueness(engine) -> None:
    inspector = inspect(engine)
    if "user_chat_history" not in inspector.get_table_names():
        return

    unique_columns = {"user_id", "session_id"}
    constraint_exists = any(
        set(constraint.get("column_names") or []) == unique_columns
        for constraint in inspector.get_unique_constraints("user_chat_history")
    )
    index_exists = any(
        bool(index.get("unique")) and set(index.get("column_names") or []) == unique_columns
        for index in inspector.get_indexes("user_chat_history")
    )
    if constraint_exists or index_exists:
        return

    from migrations.versions.dedupe_chat_sessions import _merged_messages

    with engine.begin() as connection:
        duplicate_keys = (
            connection.execute(
                text(
                    "SELECT user_id, session_id FROM user_chat_history "
                    "GROUP BY user_id, session_id HAVING COUNT(*) > 1"
                )
            )
            .mappings()
            .all()
        )
        for key in duplicate_keys:
            duplicates = [
                dict(row)
                for row in connection.execute(
                    text(
                        "SELECT id, user_id, session_id, title, messages_data, mind_id, "
                        "created_at, updated_at FROM user_chat_history "
                        "WHERE user_id=:user_id AND session_id=:session_id "
                        "ORDER BY updated_at DESC, id DESC"
                    ),
                    {"user_id": key["user_id"], "session_id": key["session_id"]},
                )
                .mappings()
                .all()
            ]
            keeper = duplicates[0]
            best_title = next(
                (
                    row.get("title")
                    for row in duplicates
                    if row.get("title") and row.get("title") != "Новый чат"
                ),
                keeper.get("title") or "Новый чат",
            )
            mind_id = next(
                (row.get("mind_id") for row in duplicates if row.get("mind_id")),
                None,
            )
            connection.execute(
                text(
                    "UPDATE user_chat_history SET title=:title, messages_data=:messages_data, "
                    "mind_id=:mind_id WHERE id=:keeper_id"
                ),
                {
                    "title": best_title,
                    "messages_data": _merged_messages(duplicates),
                    "mind_id": mind_id,
                    "keeper_id": keeper["id"],
                },
            )
            duplicate_ids = [row["id"] for row in duplicates[1:]]
            connection.execute(
                text("DELETE FROM user_chat_history WHERE id IN :ids").bindparams(
                    bindparam("ids", expanding=True)
                ),
                {"ids": duplicate_ids},
            )

    with engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {CHAT_SESSION_UNIQUE_INDEX} "
                "ON user_chat_history (user_id, session_id)"
            )
        )


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=True)
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
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_banned = db.Column(db.Boolean, default=False, nullable=False)
    is_blocked = db.Column(db.Boolean, default=False, nullable=False)
    moderation_reason = db.Column(db.String(280), nullable=True)
    ban_reason = db.Column(db.String(280), nullable=True)
    block_reason = db.Column(db.String(280), nullable=True)
    banned_until = db.Column(db.DateTime, nullable=True)
    blocked_until = db.Column(db.DateTime, nullable=True)
    auth_identities = db.relationship(
        "AuthIdentity",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )
    telegram_link_requests = db.relationship(
        "TelegramLinkRequest",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self):
        return f"<User {self.username}>"

    def to_dict(self):
        is_super_admin = is_super_admin_user(self)
        restriction = get_account_restriction(self)
        return {
            "id": self.id,
            "username": self.username,
            "name": self.name,
            "email": None if is_telegram_placeholder_email(self) else self.email,
            "is_confirmed": self.is_confirmed,
            "is_admin": bool(self.is_admin or is_super_admin),
            "is_super_admin": is_super_admin,
            "is_banned": bool(restriction and restriction["type"] == "ban"),
            "is_blocked": bool(restriction and restriction["type"] == "block"),
            "moderation_reason": restriction["reason"] if restriction else None,
            "ban_reason": self.ban_reason,
            "block_reason": self.block_reason,
            "banned_until": self.banned_until.isoformat() if self.banned_until else None,
            "blocked_until": self.blocked_until.isoformat() if self.blocked_until else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "oauth_provider": self.oauth_provider,
            "auth_methods": _user_auth_methods(self),
            "telegram_bot_ready": _telegram_bot_ready(self),
        }


class AuthIdentity(db.Model):
    __tablename__ = "auth_identity"
    __table_args__ = (
        db.UniqueConstraint(
            "provider", "provider_user_id", name="uq_auth_identity_provider_subject"
        ),
        db.UniqueConstraint("user_id", "provider", name="uq_auth_identity_user_provider"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    provider = db.Column(db.String(20), nullable=False)
    provider_user_id = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user = db.relationship("User", back_populates="auth_identities")


class AppleAuthChallenge(db.Model):
    """Short-lived one-time challenge. Raw state and nonce values are never persisted."""

    __tablename__ = "apple_auth_challenge"

    id = db.Column(db.Integer, primary_key=True)
    challenge_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    nonce_hash = db.Column(db.String(64), nullable=False)
    flow = db.Column(db.String(12), nullable=False)
    mode = db.Column(db.String(12), nullable=False)
    link_user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=True
    )
    redirect_to = db.Column(db.String(500), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    consumed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class AppleTokenReplay(db.Model):
    """Digest-only replay ledger for verified Apple identity tokens."""

    __tablename__ = "apple_token_replay"

    token_hash = db.Column(db.String(64), primary_key=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class TelegramLinkRequest(db.Model):
    __tablename__ = "telegram_link_request"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.String(24), unique=True, nullable=False, index=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    consumed_at = db.Column(db.DateTime, nullable=True)
    failure_code = db.Column(db.String(32), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user = db.relationship("User", back_populates="telegram_link_requests")


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
    """Consume an opaque bot deep-link token and attach the Telegram identity."""
    normalized_token = str(token or "").strip()
    normalized_telegram_id = str(telegram_user_id or "").strip()
    if not TELEGRAM_LINK_TOKEN_RE.fullmatch(normalized_token):
        return "invalid"
    if not re.fullmatch(r"[0-9]{1,16}", normalized_telegram_id):
        return "invalid"
    if not 1 <= int(normalized_telegram_id) <= TELEGRAM_BOT_USER_ID_MAX:
        return "invalid"

    link_request = (
        TelegramLinkRequest.query.filter_by(
            token_hash=_telegram_link_token_hash(normalized_token)
        )
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


def _user_auth_methods(user: User | None) -> list[str]:
    if not user:
        return []
    methods = {
        identity.provider
        for identity in user.auth_identities
        if identity.provider in SUPPORTED_AUTH_PROVIDERS
    }
    if user.oauth_provider in SUPPORTED_AUTH_PROVIDERS and user.oauth_id:
        methods.add(user.oauth_provider)
    if user.password:
        methods.add("password")
    return sorted(methods)


def _telegram_bot_ready(user: User | None) -> bool:
    if not user:
        return False
    telegram_id = next(
        (
            identity.provider_user_id
            for identity in user.auth_identities
            if identity.provider == "telegram"
        ),
        None,
    )
    if not telegram_id and user.oauth_provider == "telegram":
        telegram_id = user.oauth_id
    normalized = str(telegram_id or "").strip()
    if not re.fullmatch(r"[0-9]{1,16}", normalized):
        return False
    return 1 <= int(normalized) <= TELEGRAM_BOT_USER_ID_MAX


def _find_auth_identity(provider: str, provider_user_id: str) -> AuthIdentity | None:
    return AuthIdentity.query.filter_by(
        provider=provider,
        provider_user_id=str(provider_user_id),
    ).first()


def _discard_orphan_auth_identity(identity: AuthIdentity | None) -> AuthIdentity | None:
    if not identity or identity.user is not None:
        return identity
    current_app.logger.warning(
        "Discarding orphan auth identity provider=%s identity_id=%s user_id=%s",
        identity.provider,
        identity.id,
        identity.user_id,
    )
    db.session.delete(identity)
    db.session.flush()
    return None


def _link_auth_identity(user: User, provider: str, provider_user_id: str) -> AuthIdentity:
    normalized_subject = str(provider_user_id or "").strip()
    if provider not in SUPPORTED_AUTH_PROVIDERS or not normalized_subject:
        raise ValueError("invalid_auth_identity")

    existing_identity = _discard_orphan_auth_identity(
        _find_auth_identity(provider, normalized_subject)
    )
    if existing_identity:
        if existing_identity.user_id != user.id:
            raise AuthIdentityConflictError("auth_identity_in_use")
        return existing_identity

    provider_identity = AuthIdentity.query.filter_by(
        user_id=user.id,
        provider=provider,
    ).first()
    if provider_identity:
        if secrets.compare_digest(provider_identity.provider_user_id, normalized_subject):
            return provider_identity
        raise AuthIdentityConflictError("auth_provider_already_linked")

    identity = AuthIdentity(
        user_id=user.id,
        provider=provider,
        provider_user_id=normalized_subject,
    )
    db.session.add(identity)
    if not user.oauth_provider or not user.oauth_id:
        user.oauth_provider = provider
        user.oauth_id = normalized_subject
    return identity


def _ensure_auth_identity_backfill(app) -> None:
    changed = False
    for user in User.query.order_by(User.id.asc()).all():
        if user.oauth_provider not in SUPPORTED_AUTH_PROVIDERS or not user.oauth_id:
            continue
        try:
            identity = _link_auth_identity(user, user.oauth_provider, str(user.oauth_id))
            changed = changed or identity in db.session.new
        except AuthIdentityConflictError:
            app.logger.error(
                "Skipped conflicting legacy auth identity for user_id=%s provider=%s",
                user.id,
                user.oauth_provider,
            )
    if changed:
        db.session.commit()


def _parse_admin_user_ids(raw_value: str | None) -> frozenset[int]:
    if raw_value is None:
        return DEFAULT_ROOT_ADMIN_USER_IDS

    admin_ids: set[int] = set()
    for part in raw_value.split(","):
        candidate = part.strip()
        if not candidate:
            continue
        try:
            user_id = int(candidate)
        except ValueError:
            continue
        if user_id > 0:
            admin_ids.add(user_id)
    return frozenset(admin_ids)


def configured_root_admin_user_ids() -> frozenset[int]:
    raw_value = os.getenv("ADMIN_USER_IDS")
    if raw_value is None:
        raw_value = os.getenv("ROOT_ADMIN_USER_IDS")
    return _parse_admin_user_ids(raw_value)


def is_super_admin_user(user: User | None) -> bool:
    return bool(user and user.id in configured_root_admin_user_ids())


def is_admin_user(user: User | None) -> bool:
    return bool(user and (is_super_admin_user(user) or user.is_admin))


def _restriction_is_active(enabled: bool | None, expires_at: datetime | None) -> bool:
    if not enabled:
        return False
    return expires_at is None or expires_at > datetime.utcnow()


def get_account_restriction(user: User | None) -> dict[str, Any] | None:
    if not user:
        return None
    if _restriction_is_active(user.is_banned, user.banned_until):
        return {
            "type": "ban",
            "label": "бан",
            "reason": user.ban_reason or user.moderation_reason,
            "until": user.banned_until,
        }
    if _restriction_is_active(user.is_blocked, user.blocked_until):
        return {
            "type": "block",
            "label": "блокировка",
            "reason": user.block_reason or user.moderation_reason,
            "until": user.blocked_until,
        }
    return None


def format_account_restriction_message(user: User | None) -> str:
    restriction = get_account_restriction(user)
    if not restriction:
        return "Аккаунт ограничен администратором"

    parts = [f"Аккаунт ограничен администратором: {restriction['label']}."]
    reason = restriction.get("reason")
    if reason:
        parts.append(f"Причина: {reason}.")
    until = restriction.get("until")
    if isinstance(until, datetime):
        parts.append(f"Срок: до {until.strftime('%Y-%m-%d %H:%M UTC')}.")
    else:
        parts.append("Срок: бессрочно.")
    return " ".join(parts)


def is_account_disabled(user: User | None) -> bool:
    return get_account_restriction(user) is not None


class UserSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    theme = db.Column(db.String(20), default="dark")
    language = db.Column(db.String(10), default="ru")
    automatic_web_search = db.Column(
        db.Boolean,
        default=True,
        server_default=text("TRUE"),
        nullable=False,
    )
    settings_data = db.Column(db.Text, default="{}")  # JSON for additional settings
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<UserSettings {self.user_id}>"

    def get_settings(self):
        try:
            parsed = json.loads(self.settings_data) if self.settings_data else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return sanitize_settings_data(parsed)

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "theme": self.theme,
            "language": self.language,
            "automatic_web_search": bool(self.automatic_web_search),
            "settings_data": self.get_settings(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class UserChatHistory(db.Model):
    __table_args__ = (
        db.UniqueConstraint("user_id", "session_id", name="uq_user_chat_history_user_session"),
        db.UniqueConstraint(
            "user_id",
            "external_ref_hash",
            name="uq_user_chat_history_user_external_ref",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    session_id = db.Column(db.String(100), nullable=False)
    mind_id = db.Column(
        db.Integer, db.ForeignKey("mind.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title = db.Column(db.String(200), default="Новый чат")
    source = db.Column(
        db.String(32), default="web", server_default="web", nullable=False, index=True
    )
    external_ref_hash = db.Column(db.String(64), nullable=True, index=True)
    source_context_data = db.Column(db.Text, default="{}", nullable=False)
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

    def get_source_context(self):
        try:
            parsed = json.loads(self.source_context_data) if self.source_context_data else {}
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def set_source_context(self, value):
        self.source_context_data = json.dumps(
            value if isinstance(value, dict) else {}, ensure_ascii=False
        )

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "mind_id": self.mind_id,
            "title": self.title,
            "source": self.source or "web",
            "messages": self.get_messages(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TelegramInlineResult(db.Model):
    __tablename__ = "telegram_inline_result"

    id = db.Column(db.Integer, primary_key=True)
    result_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    telegram_user_id = db.Column(db.String(32), nullable=False, index=True)
    query_text = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)
    language = db.Column(db.String(12), nullable=True)
    selected_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class AIResponseFeedback(db.Model):
    __tablename__ = "ai_response_feedback"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    session_id = db.Column(db.String(100), nullable=False, index=True)
    message_client_id = db.Column(db.String(120), nullable=True)
    response_hash = db.Column(db.String(64), nullable=False, index=True)
    rating = db.Column(db.String(12), nullable=False, index=True)
    reason_codes_data = db.Column(db.Text, default="[]", nullable=False)
    comment = db.Column(db.Text, nullable=True)
    prompt_text = db.Column(db.Text, nullable=True)
    response_text = db.Column(db.Text, nullable=True)
    service_improvement_opt_in = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "session_id",
            "response_hash",
            name="uq_ai_feedback_user_session_response",
        ),
    )

    def get_reason_codes(self):
        try:
            parsed = json.loads(self.reason_codes_data) if self.reason_codes_data else []
            return parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    def set_reason_codes(self, reason_codes):
        self.reason_codes_data = json.dumps(reason_codes or [], ensure_ascii=False)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "message_client_id": self.message_client_id,
            "response_hash": self.response_hash,
            "rating": self.rating,
            "reason_codes": self.get_reason_codes(),
            "comment": self.comment,
            "prompt_text": self.prompt_text,
            "response_text": self.response_text,
            "service_improvement_opt_in": bool(self.service_improvement_opt_in),
            "created_at": self.created_at.isoformat() if self.created_at else None,
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


class Mind(db.Model):
    __tablename__ = "mind"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(128), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.String(280), nullable=False)
    instructions = db.Column(db.Text, nullable=False)
    starters_data = db.Column(db.Text, default="[]", nullable=False)
    category = db.Column(db.String(50), default="general", nullable=False, index=True)
    visibility = db.Column(db.String(20), default="private", nullable=False, index=True)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    is_system = db.Column(db.Boolean, default=False, nullable=False)
    is_featured = db.Column(db.Boolean, default=False, nullable=False, index=True)
    is_banned = db.Column(db.Boolean, default=False, nullable=False, index=True)
    moderation_reason = db.Column(db.String(280), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_starters(self):
        try:
            parsed = json.loads(self.starters_data) if self.starters_data else []
            return parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    def set_starters(self, starters):
        self.starters_data = json.dumps(starters or [], ensure_ascii=False)

    def to_dict(self, viewer_id=None, pinned=False):
        is_owner = bool(viewer_id is not None and self.user_id == viewer_id)
        return {
            "id": self.id,
            "public_id": self.public_id,
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions if is_owner else "",
            "starters": self.get_starters(),
            "category": self.category,
            "visibility": self.visibility,
            "is_verified": bool(self.is_verified),
            "is_system": bool(self.is_system),
            "is_featured": bool(self.is_featured),
            "is_banned": bool(self.is_banned),
            "moderation_reason": self.moderation_reason if is_owner else None,
            "is_owner": is_owner,
            "can_edit": is_owner and not self.is_system,
            "is_pinned": bool(pinned),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class MindPin(db.Model):
    __tablename__ = "mind_pin"
    __table_args__ = (db.UniqueConstraint("user_id", "mind_id", name="uq_mind_pin_user_mind"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    mind_id = db.Column(db.Integer, db.ForeignKey("mind.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class GitHubInstallation(db.Model):
    __tablename__ = "github_installation"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "installation_id",
            name="uq_github_installation_user_installation",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    installation_id = db.Column(db.BigInteger, nullable=False, index=True)
    account_login = db.Column(db.String(120), nullable=False)
    account_html_url = db.Column(db.String(500), nullable=True)
    account_avatar_url = db.Column(db.String(500), nullable=True)
    target_type = db.Column(db.String(40), nullable=True)
    repository_selection = db.Column(db.String(40), nullable=True)
    permissions_data = db.Column(db.Text, default="{}", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_permissions(self):
        try:
            parsed = json.loads(self.permissions_data) if self.permissions_data else {}
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def set_permissions(self, permissions):
        self.permissions_data = json.dumps(permissions or {}, ensure_ascii=False)

    def to_dict(self):
        return {
            "id": self.id,
            "installation_id": self.installation_id,
            "account_login": self.account_login,
            "account_html_url": self.account_html_url,
            "account_avatar_url": self.account_avatar_url,
            "target_type": self.target_type,
            "repository_selection": self.repository_selection,
            "permissions": self.get_permissions(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class GitHubAgentTask(db.Model):
    __tablename__ = "github_agent_task"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(128), nullable=False, unique=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    installation_id = db.Column(db.BigInteger, nullable=False, index=True)
    repo_full_name = db.Column(db.String(260), nullable=False, index=True)
    base_branch = db.Column(db.String(260), nullable=False)
    branch_name = db.Column(db.String(260), nullable=True)
    task = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(40), default="planned", nullable=False, index=True)
    plan_data = db.Column(db.Text, default="{}", nullable=False)
    edits_data = db.Column(db.Text, default="{}", nullable=False)
    diff = db.Column(db.Text, nullable=True)
    pull_request_number = db.Column(db.Integer, nullable=True)
    pull_request_url = db.Column(db.String(500), nullable=True)
    error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_plan(self):
        try:
            parsed = json.loads(self.plan_data) if self.plan_data else {}
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def set_plan(self, plan):
        self.plan_data = json.dumps(plan or {}, ensure_ascii=False)

    def get_edits(self):
        try:
            parsed = json.loads(self.edits_data) if self.edits_data else {}
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def set_edits(self, edits):
        self.edits_data = json.dumps(edits or {}, ensure_ascii=False)

    def to_dict(self, include_details=True):
        payload = {
            "id": self.public_id,
            "installation_id": self.installation_id,
            "repo_full_name": self.repo_full_name,
            "base_branch": self.base_branch,
            "branch_name": self.branch_name,
            "task": self.task,
            "status": self.status,
            "pull_request_number": self.pull_request_number,
            "pull_request_url": self.pull_request_url,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_details:
            payload["plan"] = self.get_plan()
            payload["edits"] = self.get_edits()
            payload["diff"] = self.diff
        return payload


LEGACY_DEFAULT_MIND_PUBLIC_IDS = (
    "mind_study_coach",
    "mind_code_reviewer",
    "mind_product_strategist",
    "mind_security_auditor",
)


def _remove_legacy_default_minds(app):
    try:
        minds = Mind.query.filter(
            Mind.public_id.in_(LEGACY_DEFAULT_MIND_PUBLIC_IDS),
            Mind.is_system.is_(True),
        ).all()
        if not minds:
            return

        mind_ids = [mind.id for mind in minds]
        MindPin.query.filter(MindPin.mind_id.in_(mind_ids)).delete(synchronize_session=False)
        for mind in minds:
            db.session.delete(mind)
        db.session.commit()
        app.logger.info("Removed %s legacy default minds", len(minds))
    except Exception:
        db.session.rollback()
        app.logger.exception("Failed to remove legacy default minds")


def is_valid_password(password):

    if len(password) < 8:
        return False
    if not re.search(r"\d", password):
        return False
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False
    return True


def _is_username_taken(username: str, exclude_user_id: int | None = None) -> bool:
    query = User.query.filter(func.lower(User.username) == username.lower())
    if exclude_user_id is not None:
        query = query.filter(User.id != exclude_user_id)
    return query.first() is not None


def _validate_unique_username(username: str, exclude_user_id: int | None = None) -> str:
    normalized = InputValidator.validate_username(username)
    if _is_username_taken(normalized, exclude_user_id=exclude_user_id):
        raise ValidationError("Username is already taken")
    return normalized


def _normalize_username_candidate(value: str | None) -> str:
    if not value:
        return ""

    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    candidate = re.sub(r"[^a-z0-9_-]+", "_", ascii_value)
    candidate = re.sub(r"_+", "_", candidate).strip("_-")

    if len(candidate) < 3:
        return ""

    return candidate[:50].strip("_-")


def _build_unique_username(*candidates: str | None) -> str:
    normalized_candidates = []
    for candidate in candidates:
        normalized = _normalize_username_candidate(candidate)
        if normalized and normalized not in normalized_candidates:
            normalized_candidates.append(normalized)

    if not normalized_candidates:
        normalized_candidates = [f"user_{secrets.token_hex(4)}"]

    for base in normalized_candidates:
        for suffix_index in range(1000):
            suffix = "" if suffix_index == 0 else f"_{suffix_index}"
            trimmed_base = base[: max(3, 50 - len(suffix))].strip("_-")
            candidate = f"{trimmed_base}{suffix}".strip("_-")
            if len(candidate) < 3:
                continue
            if not _is_username_taken(candidate):
                return candidate

    return f"user_{secrets.token_hex(6)}"[:50]


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
    # Keep the two digest-only tables bounded without retaining stale authentication data.
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
    name = raw_value.get("name") if isinstance(raw_value.get("name"), dict) else raw_value
    parts = [
        name.get("firstName") or name.get("first_name"),
        name.get("middleName") or name.get("middle_name"),
        name.get("lastName") or name.get("last_name"),
    ]
    combined = " ".join(
        part.strip()[:100] for part in parts if isinstance(part, str) and part.strip()
    )
    return _clean_apple_profile_name(combined, "") or None


def _telegram_placeholder_email(telegram_subject: str) -> str:
    return f"telegram-{telegram_subject}@users.remind.invalid"


def is_telegram_placeholder_email(user: User | None) -> bool:
    if not user:
        return False
    telegram_subject = next(
        (
            identity.provider_user_id
            for identity in user.auth_identities
            if identity.provider == "telegram"
        ),
        None,
    )
    if not telegram_subject and user.oauth_provider == "telegram" and user.oauth_id:
        telegram_subject = str(user.oauth_id)
    return bool(telegram_subject and user.email == _telegram_placeholder_email(telegram_subject))


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
    identity = _discard_orphan_auth_identity(
        _find_auth_identity("telegram", telegram_user_id)
    )
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
    return is_loopback_hostname(hostname)


def _is_safe_redirect_target(target: str, allowed_hosts) -> bool:
    if not target or not isinstance(target, str):
        return False
    if "\\" in target or any(ord(char) < 32 or ord(char) == 127 for char in target):
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


def _mobile_google_oauth_serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="google-mobile-oauth")


def _encode_mobile_google_oauth_token(secret_key: str, user_id: int) -> str:
    serializer = _mobile_google_oauth_serializer(secret_key)
    return serializer.dumps(
        {
            "aud": "remind-ios-google",
            "user_id": user_id,
            "nonce": secrets.token_urlsafe(16),
        }
    )


def _decode_mobile_google_oauth_token(
    secret_key: str,
    raw_value: str,
    max_age: int = MOBILE_GOOGLE_OAUTH_TOKEN_TTL_SECONDS,
):
    if not raw_value or not secret_key:
        return None
    serializer = _mobile_google_oauth_serializer(secret_key)
    try:
        data = serializer.loads(raw_value, max_age=max_age)
    except BadData:
        return None
    if not isinstance(data, dict) or data.get("aud") != "remind-ios-google":
        return None
    return data


def _is_allowed_mobile_oauth_redirect_uri(raw_value: str, configured_uri: str) -> bool:
    candidate = (raw_value or "").strip()
    configured = (configured_uri or "").strip()
    if not candidate or candidate != configured:
        return False

    parsed = urlparse(candidate)
    return bool(parsed.scheme and parsed.netloc == "auth" and parsed.path.rstrip("/") == "/google")


def _append_url_query(raw_url: str, params: dict[str, str]) -> str:
    parsed = urlparse(raw_url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.extend((key, value) for key, value in params.items() if value is not None)
    return urlunparse(parsed._replace(query=urlencode(query)))


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

            if is_account_disabled(user):
                record_login_attempt(email, False)
                log_auth_event(AuditEvents.AUTH_LOGIN_FAILED, email, False, "account_disabled")
                flash(format_account_restriction_message(user), "danger")
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

        from config import TURNSTILE_SITE_KEY

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
        from config import (
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
        from config import (
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
        from utils.session_security import regenerate_session

        state = request.form.get("state", "")
        authorization_code = request.form.get("code", "")
        apple_error = request.form.get("error", "")
        metadata = None

        def finish_apple_redirect(location: str):
            if metadata and metadata.get("mode") == "link":
                try:
                    link_user = db.session.get(User, metadata.get("link_user_id"))
                    if link_user and not is_account_disabled(link_user):
                        # Apple's required form_post callback is cross-site, so the
                        # SameSite=Lax session cookie is absent. Restore only the
                        # account captured by the signed, one-time link challenge.
                        session.clear()
                        session["user_id"] = link_user.id
                        session["username"] = InputValidator.sanitize_output(link_user.username)
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
        from config import (
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
            from config import ALLOWED_HOSTS, SESSION_COOKIE_DOMAIN

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
                from config import SECRET_KEY

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

            # When token is obtained via fallback flow, Authlib may not populate client token state.
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
                from config import IOS_OAUTH_REDIRECT_URI, SECRET_KEY, SESSION_COOKIE_DOMAIN

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
            db.session.rollback()
            app.logger.error("OAuth error in authorize_google() (%s)", type(e).__name__)
            flash("Ошибка при входе через Google", "danger")
            if link_user_id:
                from config import SESSION_COOKIE_DOMAIN

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
                from config import SESSION_COOKIE_DOMAIN

                cookie_domain = resolve_cookie_domain(SESSION_COOKIE_DOMAIN, request.host)
                response.delete_cookie(
                    OAUTH_FALLBACK_STATE_COOKIE,
                    domain=cookie_domain,
                    path=url_for("authorize_google"),
                )
                return response

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
            user = db.session.get(User, session["user_id"])
            if user:
                return jsonify({"authenticated": True, "user": user.to_dict()}), 200
        return jsonify({"authenticated": False, "user": None}), 200

    @app.route("/api/auth/turnstile/mobile", methods=["GET"])
    def api_mobile_turnstile():
        """Serve a minimal, first-party Turnstile shell for native app authentication."""
        from config import LOCALHOST_MODE, TURNSTILE_SITE_KEY

        nonce = getattr(g, "csp_nonce", "") or secrets.token_urlsafe(24)
        site_key = TURNSTILE_SITE_KEY if TURNSTILE_SITE_KEY and not LOCALHOST_MODE else ""
        site_key_literal = json.dumps(site_key)
        document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
  <style nonce="{nonce}">
    :root {{ color-scheme: light dark; }}
    html, body {{ margin: 0; min-height: 74px; background: transparent; overflow: hidden; }}
    body {{ display: flex; align-items: center; justify-content: center; }}
    #challenge {{ min-height: 70px; width: 100%; display: flex; align-items: center; justify-content: center; }}
  </style>
  <script nonce="{nonce}">
    (() => {{
      const siteKey = {site_key_literal};
      const post = (payload) => {{
        try {{ window.webkit?.messageHandlers?.turnstile?.postMessage(payload); }} catch (_) {{}}
      }};
      let timeout = setTimeout(() => post({{ state: "failed" }}), 20000);
      window.remindTurnstileBoot = () => {{
        if (!siteKey) {{
          clearTimeout(timeout);
          post({{ state: "disabled" }});
          return;
        }}
        if (!window.turnstile) {{
          clearTimeout(timeout);
          post({{ state: "failed" }});
          return;
        }}
        try {{
          window.turnstile.render("#challenge", {{
            sitekey: siteKey,
            theme: "auto",
            callback: (token) => {{ clearTimeout(timeout); post({{ state: "solved", token }}); }},
            "expired-callback": () => post({{ state: "expired" }}),
            "error-callback": () => {{ clearTimeout(timeout); post({{ state: "failed" }}); }}
          }});
          post({{ state: "ready" }});
        }} catch (_) {{
          clearTimeout(timeout);
          post({{ state: "failed" }});
        }}
      }};
    }})();
  </script>
  <script nonce="{nonce}" defer src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&amp;onload=remindTurnstileBoot"></script>
</head>
<body><main id="challenge"></main></body>
</html>"""
        response = Response(document, content_type="text/html; charset=utf-8")
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            f"script-src 'nonce-{nonce}' https://challenges.cloudflare.com; "
            f"style-src 'nonce-{nonce}'; "
            "frame-src https://challenges.cloudflare.com; "
            "connect-src https://challenges.cloudflare.com; "
            "img-src data: https://challenges.cloudflare.com; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        )
        return response

    @app.route("/api/auth/config", methods=["GET"])
    def api_auth_config():

        from config import (
            ALLOWED_HOSTS,
            APPLE_APP_BUNDLE_ID,
            APPLE_CLIENT_SECRET,
            APPLE_KEY_ID,
            APPLE_PRIVATE_KEY,
            APPLE_PRIVATE_KEY_PATH,
            APPLE_SERVICE_ID,
            APPLE_TEAM_ID,
            APPLE_WEB_REDIRECT_URI,
            GOOGLE_CLIENT_ID,
            IOS_OAUTH_CALLBACK_SCHEME,
            IOS_OAUTH_REDIRECT_URI,
            LOCALHOST_MODE,
            TELEGRAM_BOT_USERNAME,
            TELEGRAM_CLIENT_ID,
            TURNSTILE_SITE_KEY,
        )

        telegram_nonce = _issue_telegram_login_nonce() if TELEGRAM_CLIENT_ID else None
        apple_web_available = bool(
            _valid_apple_web_redirect_uri(APPLE_WEB_REDIRECT_URI, ALLOWED_HOSTS)
            and _apple_web_client_credentials_available(
                service_id=APPLE_SERVICE_ID,
                client_secret=APPLE_CLIENT_SECRET,
                team_id=APPLE_TEAM_ID,
                key_id=APPLE_KEY_ID,
                private_key=APPLE_PRIVATE_KEY,
                private_key_path=APPLE_PRIVATE_KEY_PATH,
            )
        )

        return (
            jsonify(
                {
                    "turnstile_site_key": TURNSTILE_SITE_KEY,
                    "turnstile_required": bool(TURNSTILE_SITE_KEY) and not LOCALHOST_MODE,
                    "gauth_available": bool(GOOGLE_CLIENT_ID),
                    "google_login_url": url_for("login_google"),
                    "google_mobile_login_url": url_for("login_google", client="ios"),
                    "apple_native_available": bool(APPLE_APP_BUNDLE_ID),
                    "apple_web_available": apple_web_available,
                    "apple_login_url": url_for("login_apple") if apple_web_available else None,
                    "telegram_available": bool(TELEGRAM_CLIENT_ID),
                    "telegram_client_id": TELEGRAM_CLIENT_ID or None,
                    "telegram_nonce": telegram_nonce,
                    "telegram_bot_link_available": bool(TELEGRAM_BOT_USERNAME),
                    "mobile_oauth_redirect_uri": IOS_OAUTH_REDIRECT_URI,
                    "mobile_oauth_callback_scheme": IOS_OAUTH_CALLBACK_SCHEME,
                }
            ),
            200,
        )

    @app.route("/api/auth/apple/nonce", methods=["GET"])
    @rate_limit(login_limiter, "Too many login attempts")
    def api_apple_nonce():
        from config import APPLE_APP_BUNDLE_ID

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
        from config import APPLE_APP_BUNDLE_ID
        from utils.session_security import regenerate_session

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
        regenerate_session()
        session.permanent = True
        return jsonify({"message": "apple_authenticated", "user": user.to_dict()}), 200

    @app.route("/api/auth/telegram", methods=["POST"])
    @rate_limit(login_limiter, "Too many login attempts")
    def api_telegram_login():
        from config import TELEGRAM_CLIENT_ID
        from utils.session_security import regenerate_session

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
        regenerate_session()
        session.permanent = True

        return jsonify({"message": "telegram_authenticated", "user": user.to_dict()}), 200

    @app.route("/api/auth/telegram/link", methods=["POST"])
    @rate_limit(login_limiter, "Too many link attempts")
    def api_create_telegram_link():
        from config import TELEGRAM_BOT_USERNAME

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

        return jsonify(
            {
                "url": f"https://t.me/{bot_username}?start=connect_{raw_token}",
                "request_id": request_id,
                "expires_in": TELEGRAM_LINK_TOKEN_TTL_SECONDS,
            }
        ), 201

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
                return jsonify(
                    {"status": "failed", "code": link_request.failure_code}
                ), 200
            return jsonify({"status": "linked", "user": user.to_dict()}), 200
        if link_request.expires_at <= datetime.utcnow():
            return jsonify({"status": "expired"}), 200
        return jsonify({"status": "pending"}), 200

    @app.route("/api/auth/mobile/google/complete", methods=["POST"])
    @rate_limit(login_limiter, "Too many login attempts")
    def api_mobile_google_complete():
        try:
            from config import SECRET_KEY
            from utils.session_security import regenerate_session

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
            regenerate_session()
            session.permanent = True

            return jsonify({"message": "Успешный вход через Google", "user": user.to_dict()}), 200
        except Exception as e:
            app.logger.exception(f"Mobile Google OAuth complete error: {e}")
            return jsonify({"error": "Ошибка при входе через Google"}), 500

    @app.route("/api/auth/register", methods=["POST"])
    @rate_limit(login_limiter, "Too many registration attempts")
    def api_register():

        try:
            data = request.get_json(silent=True) or {}
            username = data.get("username", "")
            name = data.get("name", "")
            email = data.get("email", "")
            password = data.get("password", "")
            from config import TURNSTILE_SITE_KEY

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
            regenerate_session()
            session.permanent = True

            return jsonify({"message": "Успешный вход", "user": user.to_dict()}), 200

        except Exception as e:
            app.logger.exception(f"API login error: {e}")
            return jsonify({"error": "Ошибка при входе"}), 500

    @app.route("/api/auth/logout", methods=["POST"])
    def api_logout():

        from utils.session_security import invalidate_session

        _revoke_pending_apple_link_challenges(session.get("user_id"))
        invalidate_session()
        return jsonify({"message": "Успешный выход"}), 200

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
        inspector = inspect(db.engine)
        date_time_type = (
            "TIMESTAMP" if db.engine.dialect.name in {"postgresql", "postgres"} else "DATETIME"
        )
        if "user" in inspector.get_table_names():
            user_columns = {column["name"] for column in inspector.get_columns("user")}
            if "name" not in user_columns:
                with db.engine.begin() as connection:
                    connection.execute(text('ALTER TABLE "user" ADD COLUMN name VARCHAR(100)'))
                    connection.execute(
                        text(
                            'UPDATE "user" SET name = username '
                            "WHERE name IS NULL OR TRIM(name) = ''"
                        )
                    )
                app.logger.info("Added missing user.name column to existing database")
            user_admin_columns = {
                "is_admin": 'ALTER TABLE "user" ADD COLUMN is_admin BOOLEAN DEFAULT FALSE NOT NULL',
                "is_banned": 'ALTER TABLE "user" ADD COLUMN is_banned BOOLEAN DEFAULT FALSE NOT NULL',
                "is_blocked": 'ALTER TABLE "user" ADD COLUMN is_blocked BOOLEAN DEFAULT FALSE NOT NULL',
                "moderation_reason": 'ALTER TABLE "user" ADD COLUMN moderation_reason VARCHAR(280)',
                "ban_reason": 'ALTER TABLE "user" ADD COLUMN ban_reason VARCHAR(280)',
                "block_reason": 'ALTER TABLE "user" ADD COLUMN block_reason VARCHAR(280)',
                "banned_until": f'ALTER TABLE "user" ADD COLUMN banned_until {date_time_type}',
                "blocked_until": f'ALTER TABLE "user" ADD COLUMN blocked_until {date_time_type}',
            }
            missing_user_admin_columns = [
                (column_name, ddl)
                for column_name, ddl in user_admin_columns.items()
                if column_name not in user_columns
            ]
            if missing_user_admin_columns:
                with db.engine.begin() as connection:
                    for _column_name, ddl in missing_user_admin_columns:
                        connection.execute(text(ddl))
                app.logger.info("Added missing user admin/moderation columns")
        if "user_settings" in inspector.get_table_names():
            settings_columns = {column["name"] for column in inspector.get_columns("user_settings")}
            if "automatic_web_search" not in settings_columns:
                with db.engine.begin() as connection:
                    connection.execute(
                        text(
                            "ALTER TABLE user_settings "
                            "ADD COLUMN automatic_web_search BOOLEAN DEFAULT TRUE NOT NULL"
                        )
                    )
                app.logger.info("Added missing user_settings.automatic_web_search column")
        if "user_chat_history" in inspector.get_table_names():
            chat_columns = {column["name"] for column in inspector.get_columns("user_chat_history")}
            chat_source_columns = {
                "source": (
                    "ALTER TABLE user_chat_history "
                    "ADD COLUMN source VARCHAR(32) DEFAULT 'web' NOT NULL"
                ),
                "external_ref_hash": (
                    "ALTER TABLE user_chat_history ADD COLUMN external_ref_hash VARCHAR(64)"
                ),
                "source_context_data": (
                    "ALTER TABLE user_chat_history "
                    "ADD COLUMN source_context_data TEXT DEFAULT '{}' NOT NULL"
                ),
            }
            missing_chat_source_columns = [
                ddl
                for column_name, ddl in chat_source_columns.items()
                if column_name not in chat_columns
            ]
            if missing_chat_source_columns:
                with db.engine.begin() as connection:
                    for ddl in missing_chat_source_columns:
                        connection.execute(text(ddl))
                app.logger.info("Added missing Telegram chat source columns")
            with db.engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS "
                        "uq_user_chat_history_user_external_ref "
                        "ON user_chat_history (user_id, external_ref_hash)"
                    )
                )
        if "mind" in inspector.get_table_names():
            mind_columns = {column["name"] for column in inspector.get_columns("mind")}
            mind_admin_columns = {
                "is_featured": "ALTER TABLE mind ADD COLUMN is_featured BOOLEAN DEFAULT FALSE NOT NULL",
                "is_banned": "ALTER TABLE mind ADD COLUMN is_banned BOOLEAN DEFAULT FALSE NOT NULL",
                "moderation_reason": "ALTER TABLE mind ADD COLUMN moderation_reason VARCHAR(280)",
            }
            missing_mind_admin_columns = [
                (column_name, ddl)
                for column_name, ddl in mind_admin_columns.items()
                if column_name not in mind_columns
            ]
            if missing_mind_admin_columns:
                with db.engine.begin() as connection:
                    for _column_name, ddl in missing_mind_admin_columns:
                        connection.execute(text(ddl))
                    connection.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_mind_is_featured "
                            "ON mind (is_featured)"
                        )
                    )
                    connection.execute(
                        text("CREATE INDEX IF NOT EXISTS ix_mind_is_banned " "ON mind (is_banned)")
                    )
                app.logger.info("Added missing mind admin/moderation columns")
        if "user_chat_history" in inspector.get_table_names():
            chat_columns = {column["name"] for column in inspector.get_columns("user_chat_history")}
            if "mind_id" not in chat_columns:
                with db.engine.begin() as connection:
                    connection.execute(
                        text("ALTER TABLE user_chat_history ADD COLUMN mind_id INTEGER")
                    )
                    connection.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_user_chat_history_mind_id "
                            "ON user_chat_history (mind_id)"
                        )
                    )
                app.logger.info("Added missing user_chat_history.mind_id column")
            ensure_chat_session_uniqueness(db.engine)
        # ORM backfills must run only after every compatibility column above exists.
        # Otherwise SQLAlchemy selects the full current model from a legacy table and
        # fails before the schema upgrader gets a chance to add missing columns.
        _ensure_auth_identity_backfill(app)
        _remove_legacy_default_minds(app)
        app.logger.info("Database tables created successfully")
    register_auth_routes(app)
