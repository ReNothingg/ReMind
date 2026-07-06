from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from importlib.util import find_spec


class ModelStage(StrEnum):
    RELEASE = "release"
    BETA = "beta"
    DEV = "dev"
    ALPHA = "alpha"


@dataclass(frozen=True)
class ModelDefinition:
    id: str
    title: str
    subtitle: str
    stage: ModelStage
    module: str
    handler: str
    runtime_required: bool = True


DEFAULT_MODEL_ID = "base"
MODEL_ALIASES: dict[str, str] = {
    "gemini": DEFAULT_MODEL_ID,
}

MODEL_DEFINITIONS: tuple[ModelDefinition, ...] = (
    ModelDefinition(
        id=DEFAULT_MODEL_ID,
        title="Gemini 3.1 flash lite ",
        subtitle="Модель от Google, использующая инструменты ReMind",
        stage=ModelStage.RELEASE,
        module="ai_engine.base",
        handler="base_stream",
    ),
    ModelDefinition(
        id="demo_image",
        title="Image",
        subtitle="Внутренняя модель для проверки изображений",
        stage=ModelStage.DEV,
        module="ai_engine.demo_image",
        handler="demo_image_stream",
    ),
    ModelDefinition(
        id="echo",
        title="Echo",
        subtitle="Внутренняя тестовая модель",
        stage=ModelStage.DEV,
        module="ai_engine.echo",
        handler="echo",
    ),
    ModelDefinition(
        id="echo_stream",
        title="Echo Stream",
        subtitle="Внутренняя потоковая тестовая модель",
        stage=ModelStage.DEV,
        module="ai_engine.echo",
        handler="echo_stream",
    ),
    ModelDefinition(
        id="mindart",
        title="MindArt",
        subtitle="Экспериментальная генерация изображений",
        stage=ModelStage.DEV,
        module="ai_engine.MindArt",
        handler="MindArt_stream",
        runtime_required=False,
    ),
)

_MODEL_BY_ID = {definition.id: definition for definition in MODEL_DEFINITIONS}


def normalize_model_name(model_name: str | None) -> str:
    return (model_name or "").strip().lower()


def get_model_definition(model_name: str | None) -> ModelDefinition | None:
    model_id = normalize_model_name(model_name)
    return _MODEL_BY_ID.get(MODEL_ALIASES.get(model_id, model_id))


def canonical_model_id(model_name: str | None) -> str | None:
    definition = get_model_definition(model_name)
    return definition.id if definition else None


def model_exists(model_name: str | None) -> bool:
    return get_model_definition(model_name) is not None


def iter_model_definitions() -> tuple[ModelDefinition, ...]:
    return MODEL_DEFINITIONS


def model_runtime_available(definition: ModelDefinition) -> bool:
    try:
        return find_spec(definition.module) is not None
    except (ImportError, AttributeError, ValueError):
        return False
