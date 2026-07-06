from __future__ import annotations

import logging
from importlib import import_module
from typing import Any, Callable

from ai_engine.registry import get_model_definition

logger = logging.getLogger(__name__)

ModelFunction = Callable[..., Any]


def _load_model_function(module_name: str, attr_name: str) -> ModelFunction | None:
    try:
        module = import_module(module_name)
        handler = getattr(module, attr_name)
    except (ImportError, AttributeError) as exc:
        logger.warning("Model import failed for %s.%s: %s", module_name, attr_name, exc)
        return None

    return handler if callable(handler) else None


def get_model_function(model_name: str) -> ModelFunction | None:
    definition = get_model_definition(model_name)
    if not definition:
        return None

    return _load_model_function(definition.module, definition.handler)
