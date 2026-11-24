from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_LOCALES_DIR = Path(__file__).resolve().parents[2] / "i18n" / "telegram"
SUPPORTED_LANGUAGES = frozenset({"ar", "bn", "en", "es", "fr", "hi", "pt", "ru", "zh"})


def language_from_telegram(value: Any) -> str:
    language = str(value or "").strip().lower().split("-", 1)[0]
    return language if language in SUPPORTED_LANGUAGES else "en"


@lru_cache(maxsize=9)
def _catalog(language: str) -> dict[str, str]:
    safe_language = language if language in SUPPORTED_LANGUAGES else "en"
    try:
        parsed = json.loads((_LOCALES_DIR / f"{safe_language}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def telegram_text(language: Any, key: str, **values: Any) -> str:
    normalized = language_from_telegram(language)
    template = _catalog(normalized).get(key) or _catalog("en").get(key) or key
    try:
        return template.format(**values)
    except (KeyError, ValueError):
        return template
