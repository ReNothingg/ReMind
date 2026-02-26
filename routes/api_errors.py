from __future__ import annotations

import json
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Optional

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from utils.input_validation import ValidationError
from utils.responses import logger, make_error


@dataclass
class ApiError(Exception):
    message: str
    status: int = 400
    code: str = "bad_request"
    extra: Optional[dict[str, Any]] = None


def _map_exception(error: Exception, fallback_code: str) -> ApiError:
    if isinstance(error, ApiError):
        return error
    if isinstance(error, ValidationError):
        return ApiError(str(error), status=400, code="validation_error")
    if isinstance(error, json.JSONDecodeError):
        return ApiError("Invalid JSON payload", status=400, code="invalid_json")
    if isinstance(error, RequestEntityTooLarge):
        return ApiError("File too large.", status=413, code="request_entity_too_large")
    if isinstance(error, BadRequest):
        return ApiError("Bad request", status=400, code="bad_request")
    if isinstance(error, SQLAlchemyError):
        return ApiError("Database operation failed", status=500, code="database_error")
    return ApiError("Internal server error.", status=500, code=fallback_code)


def api_error_boundary(fallback_code: str) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapped(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as exc:  # Centralized exception mapping for API routes
                mapped = _map_exception(exc, fallback_code=fallback_code)
                if mapped.status >= 500:
                    logger.exception("API error (%s): %s", fallback_code, exc)
                else:
                    logger.warning("API error (%s): %s", fallback_code, exc)
                return make_error(
                    mapped.message,
                    status=mapped.status,
                    code=mapped.code,
                    extra=mapped.extra,
                )

        return wrapped

    return decorator


def require_authenticated_user_id() -> int:
    from flask import session

    raw = session.get("user_id")
    if raw is None:
        raise ApiError("Authentication required", status=401, code="auth_required")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ApiError("Authentication required", status=401, code="auth_required") from exc
