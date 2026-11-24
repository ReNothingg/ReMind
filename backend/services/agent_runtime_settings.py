from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from backend.agent_profile import normalize_agent_runtime, supports_delegation
from backend.ai_engine.compaction import supports_summary_model
from backend.db.models import AgentProviderKey, UserSettings, db
from backend.errors import ApiError
from backend.security.provider_secrets import decrypt_provider_data, encrypt_provider_data
from backend.services.model_access import can_user_access_model

RUNTIME_PROFILE_ID = "agent-runtime"


def _runtime_profile(owner, *, lock=False, fresh=False):
    return db.session.get(
        AgentProviderKey,
        (owner, RUNTIME_PROFILE_ID),
        with_for_update=lock,
        populate_existing=lock or fresh,
    )


def _current(owner, profile):
    if profile:
        return normalize_agent_runtime(decrypt_provider_data(profile.secret))
    legacy = UserSettings.query.filter_by(user_id=owner).first()
    runtime = normalize_agent_runtime(legacy.get_settings().get("agentRuntime") if legacy else None)
    runtime.update(
        shellEnabled=False,
        subagentMaxDepth=0,
        subagentModel="",
        subagentModelSelection=False,
        subagentAllowedModels=[],
        contextSummaryMode="excerpts",
        contextSummaryModel="",
        modelReplayEnabled=False,
    )
    return runtime


def load_agent_runtime(owner, *, fresh=False):
    if not owner:
        return normalize_agent_runtime(None)
    return _current(owner, _runtime_profile(owner, fresh=fresh))


def _validate_subagent_models(owner, current, updated):
    default = updated["subagentModel"]
    allowed = updated["subagentAllowedModels"]
    added = set(allowed) - set(current["subagentAllowedModels"])
    examined = set(added)
    if default and default != current["subagentModel"]:
        examined.add(default)
    if any(
        not supports_delegation(model) or not can_user_access_model(model, owner)
        for model in examined
    ):
        error = "subagent_model_unavailable"
        raise ApiError(error, status=400, code=error)
    if updated["subagentModelSelection"] and (
        not allowed
        or (
            not current["subagentModelSelection"]
            and not added
            and not any(can_user_access_model(model, owner) for model in allowed)
        )
    ):
        error = "subagent_allowed_models_required"
        raise ApiError(error, status=400, code=error)


def replay_profile_version(owner, *, lock=False):
    if not owner:
        return None
    profile = db.session.get(
        AgentProviderKey,
        (owner, RUNTIME_PROFILE_ID),
        with_for_update={"nowait": True} if lock else None,
        populate_existing=lock,
    )
    if not profile or decrypt_provider_data(profile.secret).get("modelReplayEnabled") is not True:
        return None
    return profile.updated_at.isoformat()


def save_agent_runtime(owner, body):
    if not isinstance(body, dict) or not body:
        raise ApiError("agent_runtime_invalid", status=400, code="agent_runtime_invalid")
    profile = _runtime_profile(owner, lock=True)
    current = _current(owner, profile)
    options = {**current, **body}
    sanitized = normalize_agent_runtime(options)
    if sanitized != options or any(
        type(sanitized[key]) is not type(value) for key, value in body.items()
    ):
        raise ApiError("agent_runtime_invalid", status=400, code="agent_runtime_invalid")
    _validate_subagent_models(owner, current, sanitized)
    summary_model = sanitized["contextSummaryModel"]
    if (
        summary_model
        and summary_model != current["contextSummaryModel"]
        and (
            not supports_summary_model(summary_model)
            or not can_user_access_model(summary_model, owner)
        )
    ):
        raise ApiError(
            "context_summary_model_unavailable",
            status=400,
            code="context_summary_model_unavailable",
        )
    secret = encrypt_provider_data(sanitized)
    if profile:
        profile.secret = secret
        profile.updated_at = datetime.now(timezone.utc)
    else:
        db.session.add(
            AgentProviderKey(user_id=owner, provider=RUNTIME_PROFILE_ID, secret=secret, catalog=[])
        )
    try:
        if current["modelReplayEnabled"] and not sanitized["modelReplayEnabled"]:
            from backend.services.chat.provider_replay import delete_owner_replays

            delete_owner_replays(owner)
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        raise ApiError(
            "provider_connection_changed", status=409, code="provider_connection_changed"
        ) from error
    return sanitized
