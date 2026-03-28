from __future__ import annotations

import logging
from importlib import import_module
from typing import Any, Callable

logger = logging.getLogger(__name__)

ModelFunction = Callable[..., Any]

_MODEL_IMPORTS: dict[str, tuple[str, str]] = {
    "demo_image": ("ai_engine.demo_image", "demo_image_stream"),
    "echo": ("ai_engine.echo", "echo"),
    "echo_stream": ("ai_engine.echo", "echo_stream"),
    "gemini": ("ai_engine.gemini", "gemini_stream"),
}

_OPTIONAL_MODEL_IMPORTS: dict[str, tuple[str, str]] = {
    "mindart": ("ai_engine.MindArt", "MindArt_stream"),
}


def _load_model_function(module_name: str, attr_name: str) -> ModelFunction | None:
    try:
        module = import_module(module_name)
        handler = getattr(module, attr_name)
    except (ImportError, AttributeError) as exc:
        logger.warning("Model import failed for %s.%s: %s", module_name, attr_name, exc)
        return None

    return handler if callable(handler) else None


def get_model_function(model_name: str) -> ModelFunction | None:
    model_name_lower = (model_name or "").strip().lower()
    if not model_name_lower:
        return None

    registry_entry = _MODEL_IMPORTS.get(model_name_lower) or _OPTIONAL_MODEL_IMPORTS.get(
        model_name_lower
    )
    if not registry_entry:
        return None

    module_name, attr_name = registry_entry
    return _load_model_function(module_name, attr_name)
