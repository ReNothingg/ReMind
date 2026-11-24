from __future__ import annotations

from backend.ai_engine.registry import (
    ModelStage,
    get_model_definition,
    iter_model_definitions,
    model_expired,
    model_runtime_available,
    normalize_model_name,
)
from backend.auth.accounts import is_admin_user
from backend.db.models import User, db
from backend.services import agent_models, chatgpt_account, codex_account

BETA_PERCENT = 50


def model_exists(model_name: str | None) -> bool:
    if model_name and model_name.startswith("codex/"):
        return bool(agent_models.MODEL_ID.fullmatch(model_name[6:]))
    if model_name and agent_models.KEY_ROUTE.fullmatch(model_name):
        return True
    if model_name and model_name.startswith(chatgpt_account.MODEL_PREFIX):
        return bool(
            chatgpt_account.MODEL_SLUG.fullmatch(model_name[len(chatgpt_account.MODEL_PREFIX) :])
        )
    return get_model_definition(model_name) is not None


def get_model_stage(model_name: str | None) -> ModelStage:
    if model_name and (
        model_name.startswith("codex/") or agent_models.KEY_ROUTE.fullmatch(model_name)
    ):
        return ModelStage.RELEASE
    if model_name and model_name.startswith(chatgpt_account.MODEL_PREFIX):
        return ModelStage.RELEASE
    definition = get_model_definition(model_name)
    return definition.stage if definition else ModelStage.DEV


def _stable_bucket(model_name: str, user_id: int) -> int:
    value = f"{normalize_model_name(model_name)}:{user_id}"
    hash_value = 2166136261
    for char in value:
        hash_value ^= ord(char)
        hash_value = (hash_value * 16777619) & 0xFFFFFFFF
    return hash_value % 100


def can_user_access_model(model_name: str | None, user_id: int | None) -> bool:
    if model_name and model_name.startswith("codex/"):
        return any(entry["id"] == model_name for entry in codex_account.catalog(user_id))
    if model_name and model_name.startswith("key/"):
        return agent_models.key_route(user_id, model_name) is not None
    if model_name and model_name.startswith(chatgpt_account.MODEL_PREFIX):
        return any(model["id"] == model_name for model in chatgpt_account.list_models(user_id))
    definition = get_model_definition(model_name)
    if definition is None or model_expired(definition):
        return False

    user = db.session.get(User, user_id) if user_id is not None else None
    if definition.requires_auth and user is None:
        return False
    if definition.id == "harness":
        return agent_models.platform_route("harness").provider == "deepseek"

    stage = get_model_stage(model_name)
    if stage == ModelStage.RELEASE:
        return True

    if stage in {ModelStage.DEV, ModelStage.ALPHA}:
        return is_admin_user(user)

    if stage == ModelStage.BETA:
        if user is None:
            return False
        return _stable_bucket(normalize_model_name(model_name), user.id) < BETA_PERCENT

    return False


def _serialize_model(model) -> dict[str, object]:
    serialized = {
        "id": model.id,
        "title": model.title,
        "subtitle": model.subtitle,
        "stage": model.stage.value,
    }
    if model.title_key:
        serialized["titleKey"] = model.title_key
    if model.subtitle_key:
        serialized["subtitleKey"] = model.subtitle_key
    if model.thinking_levels:
        serialized["thinkingLevels"] = list(model.thinking_levels)
    if model.default_thinking_level:
        serialized["defaultThinkingLevel"] = model.default_thinking_level
    if model.available_until:
        serialized["availableUntil"] = model.available_until.isoformat()
    if model.id in {"base", "harness"}:
        route = agent_models.platform_route(model.id)
        serialized.update(
            title={"gemini-3.1-flash-lite":"Gemini 3.1 Flash Lite","deepseek-v4-pro":"DeepSeek-V4-Pro"}.get(route.model,route.model),
            provider=route.provider,
            source="platform",
            subtitle=agent_models.PROVIDERS[route.provider].title,
        )
        serialized["thinkingLevels"] = agent_models.native_efforts(route.provider)
        if route.provider == "deepseek":
            serialized["defaultThinkingLevel"] = "high"
        serialized.pop("titleKey", None)
        serialized.pop("subtitleKey", None)
    return serialized


def list_accessible_models(user_id: int | None) -> list[dict[str, object]]:
    models: list[dict[str, object]] = []
    for model in iter_model_definitions():
        if not model_runtime_available(model):
            continue
        if not can_user_access_model(model.id, user_id):
            continue
        entry = _serialize_model(model)
        if model.id == "harness" and agent_models.platform_route("harness").provider == "google":
            continue
        models.append(entry)
    return (
        models
        + chatgpt_account.list_models(user_id)
        + agent_models.list_key_models(user_id)
        + codex_account.catalog(user_id)
    )


def list_released_models() -> list[dict[str, object]]:
    return [
        _serialize_model(model)
        for model in iter_model_definitions()
        if model.stage == ModelStage.RELEASE
        and not model.requires_auth
        and not model_expired(model)
        and model_runtime_available(model)
    ]
