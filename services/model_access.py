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

MODEL_METADATA: dict[str, dict[str, str]] = {
    "gemini": {
        "title": "Gemini",
        "subtitle": "Основная модель ReMind",
    },
    "demo_image": {
        "title": "Image",
        "subtitle": "Внутренняя модель для проверки изображений",
    },
    "echo": {
        "title": "Echo",
        "subtitle": "Внутренняя тестовая модель",
    },
    "echo_stream": {
        "title": "Echo Stream",
        "subtitle": "Внутренняя потоковая тестовая модель",
    },
    "mindart": {
        "title": "MindArt",
        "subtitle": "Экспериментальная генерация изображений",
    },
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


def list_released_models() -> list[dict[str, str]]:
    models = []
    for model_id, stage in MODEL_STAGES.items():
        if stage != ModelStage.RELEASE:
            continue
        metadata = MODEL_METADATA.get(model_id, {})
        models.append(
            {
                "id": model_id,
                "title": metadata.get("title") or model_id,
                "subtitle": metadata.get("subtitle") or "Релизная модель",
                "stage": stage.value,
            }
        )
    return models
