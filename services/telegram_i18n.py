from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_LOCALES_DIR = Path(__file__).resolve().parent.parent / "i18n" / "telegram"
_SUPPORTED = frozenset({"en", "ru"})


def language_from_telegram(value: Any) -> str:
    language = str(value or "").strip().lower().split("-", 1)[0]
    return language if language in _SUPPORTED else "en"


@lru_cache(maxsize=2)
def _catalog(language: str) -> dict[str, str]:
    safe_language = language if language in _SUPPORTED else "en"
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
