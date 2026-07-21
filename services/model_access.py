from __future__ import annotations

from ai_engine.registry import (
    ModelStage,
    get_model_definition,
    iter_model_definitions,
    model_runtime_available,
    normalize_model_name,
)
from utils.auth import User, db, is_admin_user

BETA_PERCENT = 50


def model_exists(model_name: str | None) -> bool:
    return get_model_definition(model_name) is not None


def get_model_stage(model_name: str | None) -> ModelStage:
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
    definition = get_model_definition(model_name)
    if definition is None:
        return False

    stage = get_model_stage(model_name)
    if stage == ModelStage.RELEASE:
        return True

    user = db.session.get(User, user_id) if user_id is not None else None
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
    return serialized


def list_accessible_models(user_id: int | None) -> list[dict[str, object]]:
    models: list[dict[str, object]] = []
    for model in iter_model_definitions():
        if not model_runtime_available(model):
            continue
        if not can_user_access_model(model.id, user_id):
            continue
        models.append(_serialize_model(model))
    return models


def list_released_models() -> list[dict[str, object]]:
    return [
        _serialize_model(model)
        for model in iter_model_definitions()
        if model.stage == ModelStage.RELEASE and model_runtime_available(model)
    ]
