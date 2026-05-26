from __future__ import annotations

from enum import StrEnum

from utils.auth import User, db, is_admin_user


class ModelStage(StrEnum):
    RELEASE = "release"
    BETA = "beta"
    DEV = "dev"
    ALPHA = "alpha"


MODEL_STAGES: dict[str, ModelStage] = {
    "gemini": ModelStage.RELEASE,
    "demo_image": ModelStage.DEV,
    "echo": ModelStage.DEV,
    "echo_stream": ModelStage.DEV,
    "mindart": ModelStage.DEV,
}

BETA_PERCENT = 50


def normalize_model_name(model_name: str | None) -> str:
    return (model_name or "").strip().lower()


def get_model_stage(model_name: str | None) -> ModelStage:
    return MODEL_STAGES.get(normalize_model_name(model_name), ModelStage.RELEASE)


def _stable_bucket(model_name: str, user_id: int) -> int:
    value = f"{normalize_model_name(model_name)}:{user_id}"
    hash_value = 2166136261
    for char in value:
        hash_value ^= ord(char)
        hash_value = (hash_value * 16777619) & 0xFFFFFFFF
    return hash_value % 100


def can_user_access_model(model_name: str | None, user_id: int | None) -> bool:
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
