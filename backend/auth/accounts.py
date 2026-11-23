from __future__ import annotations

import os
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.db.models import User


DEFAULT_ROOT_ADMIN_USER_IDS = frozenset({1})


TELEGRAM_BOT_USER_ID_MAX = (1 << 52) - 1


SUPPORTED_AUTH_PROVIDERS = frozenset({"apple", "google", "telegram"})


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
