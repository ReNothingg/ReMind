from __future__ import annotations

import os
from urllib.parse import unquote, urlparse


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _validate_service_url(
    name: str,
    *,
    schemes: set[str],
    host: str,
    password: str,
    database_path: str,
) -> None:
    parsed = urlparse(_required(name))
    if parsed.scheme not in schemes or parsed.hostname != host:
        raise RuntimeError(f"{name} must target the internal {host} service")
    if unquote(parsed.password or "") != password:
        raise RuntimeError(f"{name} must contain the URL-encoded service password")
    if parsed.path != database_path:
        raise RuntimeError(f"{name} must target database {database_path}")


def validate_production_environment() -> None:
    db_password = _required("DB_PASSWORD")
    redis_password = _required("REDIS_PASSWORD")
    for required_name in (
        "SECRET_KEY",
        "AI_PROVIDER_API_KEY",
        "AI_PROVIDER_MODEL_NAME",
        "BACKEND_URL",
        "EMAIL_SENDER",
        "EMAIL_PASSWORD",
    ):
        _required(required_name)

    _validate_service_url(
        "DATABASE_URL",
        schemes={"postgresql", "postgres"},
        host="db",
        password=db_password,
        database_path="/remind_db",
    )
    _validate_service_url(
        "REDIS_URL",
        schemes={"redis", "rediss"},
        host="redis",
        password=redis_password,
        database_path="/0",
    )
    for name in ("CELERY_BROKER_URL", "CELERY_RESULT_BACKEND"):
        _validate_service_url(
            name,
            schemes={"redis", "rediss"},
            host="redis",
            password=redis_password,
            database_path="/1",
        )


if __name__ == "__main__":
    validate_production_environment()

    from app_factory import create_app

    create_app()
