from __future__ import annotations

import re
import secrets
import unicodedata

from flask import current_app
from sqlalchemy import func

from backend.auth.accounts import SUPPORTED_AUTH_PROVIDERS
from backend.db.models import AuthIdentity, User, db
from backend.security.input_validation import InputValidator, ValidationError


class AuthIdentityConflictError(ValueError):
    pass


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


def backfill_legacy_identities(app) -> None:
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
