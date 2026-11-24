from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from backend.db.models import AgentProviderKey, db
from backend.errors import ApiError
from backend.security.provider_secrets import decrypt_provider_data, encrypt_provider_data
from backend.services.agent_models import uses_public_endpoint

WEB_PROFILE_ID = "web-deepseek"
DEFAULT_WEB_PROFILE = {
    "searchProvider": "remind",
    "fetchProvider": "remind",
    "searchBilling": "linked",
    "fetchBilling": "linked",
    "searchCount": 10,
    "legacyMaxUses": 5,
}


@dataclass(frozen=True)
class WebResearchSettings:
    search_provider: str = "remind"
    fetch_provider: str = "remind"
    count: int = 10
    max_uses: int = 5
    search_key: str | None = field(default=None, repr=False)
    fetch_key: str | None = field(default=None, repr=False)


def _profile(user_id, *, lock=False):
    if not user_id:
        return None
    return db.session.get(AgentProviderKey, (user_id, WEB_PROFILE_ID), with_for_update=lock)


def _linked_key(user_id):
    if not user_id:
        return None
    model_provider = db.session.get(AgentProviderKey, (user_id, "deepseek"))
    profile = decrypt_provider_data(model_provider.secret) if model_provider else {}
    return None if uses_public_endpoint("deepseek", profile.get("base")) else profile.get("key")


def _state(row):
    stored = decrypt_provider_data(row.secret) if row else {}
    return {**DEFAULT_WEB_PROFILE, **stored}


def _public_state(state, linked):
    return {
        **{key: state[key] for key in DEFAULT_WEB_PROFILE},
        "hasLinkedKey": bool(linked),
        "hasDedicatedKey": bool(state.get("key")),
    }


def web_research_status(user_id):
    return _public_state(_state(_profile(user_id)), _linked_key(user_id))


def save_web_research(user_id, body):
    if not isinstance(body, dict) or set(body) - {*DEFAULT_WEB_PROFILE, "key", "clearKey"}:
        raise ApiError("web_settings_invalid", status=400, code="web_settings_invalid")
    row = _profile(user_id, lock=True)
    state = _state(row)
    state.update({key: body[key] for key in DEFAULT_WEB_PROFILE if key in body})
    clear_key, new_key = body.get("clearKey", False), body.get("key")
    if (
        state["searchProvider"] not in ("remind", "deepseek-search-api", "deepseek-legacy")
        or state["fetchProvider"] not in ("remind", "deepseek-fetch-api")
        or state["searchBilling"] not in ("linked", "dedicated")
        or state["fetchBilling"] not in ("linked", "dedicated")
        or type(state["searchCount"]) is not int
        or not 1 <= state["searchCount"] <= 50
        or type(state["legacyMaxUses"]) is not int
        or not 1 <= state["legacyMaxUses"] <= 5
        or not isinstance(clear_key, bool)
        or (clear_key and "key" in body)
    ):
        raise ApiError("web_settings_invalid", status=400, code="web_settings_invalid")
    if "key" in body:
        if (
            not isinstance(new_key, str)
            or not 4 <= len(new_key) <= 4096
            or not new_key.isascii()
            or not new_key.isprintable()
            or any(char.isspace() for char in new_key)
        ):
            raise ApiError("provider_key_invalid", status=400, code="provider_key_invalid")
        state["key"] = new_key
    if clear_key:
        state.pop("key", None)
    linked = _linked_key(user_id)
    for capability in ("search", "fetch"):
        if state[capability + "Provider"] == "remind":
            continue
        key = linked if state[capability + "Billing"] == "linked" else state.get("key")
        if not key:
            raise ApiError("web_key_required", status=400, code="web_key_required")
    encrypted = encrypt_provider_data(state)
    if row:
        row.secret = encrypted
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.session.add(
            AgentProviderKey(user_id=user_id, provider=WEB_PROFILE_ID, secret=encrypted, catalog=[])
        )
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ApiError(
            "provider_connection_changed", status=409, code="provider_connection_changed"
        ) from exc
    return _public_state(state, linked)


def load_web_research(user_id):
    row = _profile(user_id)
    if not row:
        return WebResearchSettings()
    state = _state(row)
    search, fetch = state["searchProvider"], state["fetchProvider"]
    needs_linked = any(
        state[capability + "Provider"] != "remind" and state[capability + "Billing"] == "linked"
        for capability in ("search", "fetch")
    )
    linked = _linked_key(user_id) if needs_linked else None
    return WebResearchSettings(
        search_provider=search,
        fetch_provider=fetch,
        count=state["searchCount"],
        max_uses=state["legacyMaxUses"],
        search_key=linked if state["searchBilling"] == "linked" else state.get("key"),
        fetch_key=linked if state["fetchBilling"] == "linked" else state.get("key"),
    )
