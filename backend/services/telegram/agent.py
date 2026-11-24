from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError

from backend.config import TELEGRAM_BOT_USERNAME
from backend.db.models import (
    AuthIdentity,
    TelegramAgentSettings,
    TelegramBusinessDelivery,
    TelegramBusinessLink,
    User,
    db,
)
from backend.errors import ApiError
from backend.services.minds import require_portable_mind, resolve_mind_context_for_chat
from backend.services.model_access import can_user_access_model, list_accessible_models


def preferences(owner):
    row = db.session.get(TelegramAgentSettings, owner)
    return {
        "model": row.model if row else "base",
        "mind_id": row.mind_id if row else None,
        "serviceTier": row.service_tier if row else "standard",
        "webSearch": row.web_search if row else False,
        "secretaryMode": row.secretary_mode if row else "off",
    }


def connection_status(owner):
    user = db.session.get(User, owner)
    identity = AuthIdentity.query.filter_by(user_id=owner, provider="telegram").first()
    link = TelegramBusinessLink.query.filter_by(user_id=owner, enabled=True).first()
    return {
        **preferences(owner),
        "linked": bool(identity or user and user.oauth_provider == "telegram"),
        "bot": TELEGRAM_BOT_USERNAME or None,
        "businessConnected": bool(link),
        "canReply": bool(link and link.can_reply),
    }


def update_preferences(owner, data):
    if not isinstance(data, dict) or set(data) - {
        "model",
        "mind_id",
        "serviceTier",
        "webSearch",
        "secretaryMode",
    }:
        raise ApiError("invalid_agent_settings", status=400, code="invalid_agent_settings")
    settings = {**preferences(owner), **data}
    model = settings["model"]
    if not isinstance(model, str) or not can_user_access_model(model, owner):
        raise ApiError("model_access_denied", status=403, code="model_access_denied")
    if settings["mind_id"] is not None:
        if not isinstance(settings["mind_id"], str):
            raise ApiError("invalid_mind_id", status=400, code="invalid_mind_id")
        profile = resolve_mind_context_for_chat(settings["mind_id"], owner)
        if model.startswith(("codex/", "key/", "chatgpt/")):
            require_portable_mind(profile, owner)
    if (
        settings["secretaryMode"] not in ("off", "mentions", "all")
        or type(settings["webSearch"]) is not bool
    ):
        raise ApiError("invalid_agent_settings", status=400, code="invalid_agent_settings")
    speed = settings["serviceTier"]
    if speed != "standard" and not any(
        entry["id"] == model and speed in entry.get("serviceTiers", [])
        for entry in list_accessible_models(owner)
    ):
        raise ApiError("model_speed_unavailable", status=400, code="model_speed_unavailable")
    row = db.session.get(TelegramAgentSettings, owner) or TelegramAgentSettings(user_id=owner)
    row.model, row.mind_id, row.service_tier, row.web_search, row.secretary_mode = (
        model,
        settings["mind_id"],
        speed,
        settings["webSearch"],
        settings["secretaryMode"],
    )
    db.session.add(row)
    db.session.commit()
    return connection_status(owner)


def bind_business(linked, payload, update_id):
    identifier = payload.get("id")
    if not isinstance(identifier, str) or not 1 <= len(identifier) <= 200:
        return
    row = db.session.get(TelegramBusinessLink, identifier)
    if row and (row.user_id != linked.user.id or row.last_update >= update_id):
        return
    if not row:
        row = TelegramBusinessLink(
            connection_id=identifier,
            user_id=linked.user.id,
            telegram_user_id=str(linked.telegram_profile["id"]),
        )
        db.session.add(row)
    row.enabled = payload.get("is_enabled") is True
    row.can_reply = (payload.get("rights") or {}).get("can_reply") is True
    row.last_update = update_id
    db.session.commit()


def claim_delivery(link, chat_id, message_id):
    try:
        db.session.add(
            TelegramBusinessDelivery(
                connection_id=link.connection_id, chat_id=chat_id, message_id=message_id
            )
        )
        db.session.commit()
        return True
    except IntegrityError:
        db.session.rollback()
        return False


def prune_receipts():
    TelegramBusinessDelivery.query.filter(
        TelegramBusinessDelivery.created_at < datetime.now(timezone.utc) - timedelta(days=2)
    ).delete()


def forget(owner):
    links = db.select(TelegramBusinessLink.connection_id).where(
        TelegramBusinessLink.user_id == owner
    )
    TelegramBusinessDelivery.query.filter(TelegramBusinessDelivery.connection_id.in_(links)).delete(
        synchronize_session=False
    )
    TelegramBusinessLink.query.filter_by(user_id=owner).delete()
    TelegramAgentSettings.query.filter_by(user_id=owner).delete()
