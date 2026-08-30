import json
from functools import lru_cache
from pathlib import Path

SUPPORTED_EMAIL_LOCALES = frozenset({"ar", "bn", "en", "es", "fr", "hi", "pt", "ru", "zh"})
LOCALE_ROOT = Path(__file__).resolve().parent.parent / "src" / "i18n" / "locales"


def normalize_email_locale(language: object) -> str:
    locale = str(language or "en").strip().lower().replace("_", "-").split("-", 1)[0]
    return locale if locale in SUPPORTED_EMAIL_LOCALES else "en"


@lru_cache(maxsize=len(SUPPORTED_EMAIL_LOCALES))
def _load_password_reset_copy(locale: str) -> dict[str, str]:
    path = LOCALE_ROOT / locale / "common.json"
    with path.open("r", encoding="utf-8") as locale_file:
        payload = json.load(locale_file)
    raw_copy = payload["authModal"]["passwordReset"]["email"]
    return {key: str(value) for key, value in raw_copy.items()}


def password_reset_email_copy(language: object, username: str) -> dict[str, str]:
    locale = normalize_email_locale(language)
    try:
        copy = dict(_load_password_reset_copy(locale))
    except (KeyError, OSError, TypeError, ValueError):
        copy = dict(_load_password_reset_copy("en"))
    copy["greeting"] = copy["greeting"].replace("{{username}}", username)
    return copy
