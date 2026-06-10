import json
import re
import secrets
import unicodedata
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from authlib.integrations.base_client.errors import MismatchingStateError
from authlib.integrations.flask_client import OAuth
from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from itsdangerous import BadData, URLSafeTimedSerializer
from sqlalchemy import func, inspect, text
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
ROOT_ADMIN_USER_ID = 1


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

    def __repr__(self):
        return f"<User {self.username}>"

    def to_dict(self):
        is_super_admin = self.id == ROOT_ADMIN_USER_ID
        restriction = get_account_restriction(self)
        return {
            "id": self.id,
            "username": self.username,
            "name": self.name,
            "email": self.email,
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
        }


def is_super_admin_user(user: User | None) -> bool:
    return bool(user and user.id == ROOT_ADMIN_USER_ID)


def is_admin_user(user: User | None) -> bool:
    return bool(user and (user.id == ROOT_ADMIN_USER_ID or user.is_admin))


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
    automatic_web_search = db.Column(db.Boolean, default=False, nullable=False)
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
            "automatic_web_search": bool(self.automatic_web_search),
            "settings_data": self.get_settings(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class UserChatHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    session_id = db.Column(db.String(100), nullable=False)
    mind_id = db.Column(db.Integer, db.ForeignKey("mind.id", ondelete="SET NULL"), nullable=True, index=True)
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
            "mind_id": self.mind_id,
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
    __table_args__ = (
        db.UniqueConstraint("user_id", "mind_id", name="uq_mind_pin_user_mind"),
    )

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
        minds = (
            Mind.query.filter(
                Mind.public_id.in_(LEGACY_DEFAULT_MIND_PUBLIC_IDS),
                Mind.is_system.is_(True),
            )
            .all()
        )
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

    @app.route("/login/google")
    def login_google():
        from config import (
            ALLOWED_HOSTS,
            BACKEND_URL,
            IOS_OAUTH_REDIRECT_URI,
            SECRET_KEY,
            SESSION_COOKIE_DOMAIN,
        )

        mobile_redirect_uri = ""
        mobile_requested = request.args.get("client") == "ios" or bool(
            request.args.get("mobile_redirect_uri")
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
        mobile_redirect_uri = None
        try:
            app.logger.debug(f"authorize_google request args: {request.args}")
            app.logger.debug(f"authorize_google request url: {request.url}")
            app.logger.info(f"authorize_google Host: {request.host}")
            app.logger.info(f"authorize_google Scheme: {request.scheme}")
            app.logger.info(f"authorize_google Base URL: {request.base_url}")
            from config import ALLOWED_HOSTS

            redirect_to = session.pop("oauth_redirect_to", None)
            mobile_redirect_uri = session.pop("oauth_mobile_redirect_uri", None)
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
                fallback_mobile_redirect_uri = str(
                    (fallback_state or {}).get("mobile_redirect_uri", "")
                )
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
                account_name = (
                    user_info.get("name")
                    or user_info.get("given_name")
                    or email.split("@")[0]
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
                db.session.commit()
                user = new_user
                flash("Аккаунт создан с помощью Google авторизации", "success")
            elif not user.oauth_id:
                user.oauth_provider = "google"
                user.oauth_id = google_id
                user.is_confirmed = True
                if not user.name:
                    user.name = (
                        user_info.get("name")
                        or user_info.get("given_name")
                        or user.username
                    )
                db.session.commit()
                flash("Ваш аккаунт связан с Google", "success")

            if mobile_redirect_uri:
                from config import IOS_OAUTH_REDIRECT_URI, SECRET_KEY, SESSION_COOKIE_DOMAIN

                if not _is_allowed_mobile_oauth_redirect_uri(
                    mobile_redirect_uri, IOS_OAUTH_REDIRECT_URI
                ):
                    app.logger.warning("Blocked Google mobile OAuth callback redirect")
                    return redirect(url_for("login"))

                mobile_token = _encode_mobile_google_oauth_token(SECRET_KEY, user.id)
                response = redirect(
                    _append_url_query(mobile_redirect_uri, {"token": mobile_token})
                )
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
            app.logger.exception(f"OAuth error in authorize_google(): {e}")
            flash("Ошибка при входе через Google", "danger")
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

    @app.route("/api/auth/config", methods=["GET"])
    def api_auth_config():

        from config import (
            GOOGLE_CLIENT_ID,
            IOS_OAUTH_CALLBACK_SCHEME,
            IOS_OAUTH_REDIRECT_URI,
            LOCALHOST_MODE,
            TURNSTILE_SITE_KEY,
        )

        return (
            jsonify(
                {
                    "turnstile_site_key": TURNSTILE_SITE_KEY,
                    "turnstile_required": bool(TURNSTILE_SITE_KEY) and not LOCALHOST_MODE,
                    "gauth_available": bool(GOOGLE_CLIENT_ID),
                    "google_login_url": url_for("login_google"),
                    "google_mobile_login_url": url_for("login_google", client="ios"),
                    "mobile_oauth_redirect_uri": IOS_OAUTH_REDIRECT_URI,
                    "mobile_oauth_callback_scheme": IOS_OAUTH_CALLBACK_SCHEME,
                }
            ),
            200,
        )

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
                user.username = _validate_unique_username(
                    data["username"], exclude_user_id=user.id
                )
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
            if "automatic_web_search" in data:
                settings.automatic_web_search = bool(data["automatic_web_search"])
            if "settings_data" in data:
                settings.settings_data = json.dumps(data["settings_data"], ensure_ascii=False)
            elif data:
                current_settings = settings.get_settings()
                for key, value in data.items():
                    if key not in ["theme", "language", "automatic_web_search"]:
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
        _remove_legacy_default_minds(app)
        inspector = inspect(db.engine)
        date_time_type = (
            "TIMESTAMP"
            if db.engine.dialect.name in {"postgresql", "postgres"}
            else "DATETIME"
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
            settings_columns = {
                column["name"] for column in inspector.get_columns("user_settings")
            }
            if "automatic_web_search" not in settings_columns:
                with db.engine.begin() as connection:
                    connection.execute(
                        text(
                            "ALTER TABLE user_settings "
                            "ADD COLUMN automatic_web_search BOOLEAN DEFAULT FALSE NOT NULL"
                        )
                    )
                app.logger.info("Added missing user_settings.automatic_web_search column")
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
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_mind_is_banned "
                            "ON mind (is_banned)"
                        )
                    )
                app.logger.info("Added missing mind admin/moderation columns")
        if "user_chat_history" in inspector.get_table_names():
            chat_columns = {column["name"] for column in inspector.get_columns("user_chat_history")}
            if "mind_id" not in chat_columns:
                with db.engine.begin() as connection:
                    connection.execute(text('ALTER TABLE user_chat_history ADD COLUMN mind_id INTEGER'))
                    connection.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_user_chat_history_mind_id "
                            "ON user_chat_history (mind_id)"
                        )
                    )
                app.logger.info("Added missing user_chat_history.mind_id column")
        app.logger.info("Database tables created successfully")
    register_auth_routes(app)
