import json
import logging
import logging.handlers
import os
import re
from datetime import datetime, timezone

from flask import has_request_context, request

from config import IS_PRODUCTION, LOGS_FOLDER
from utils.observability import get_request_id


class PIIFilter(logging.Filter):
    PII_PATTERNS = [
        (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[EMAIL]"),
        (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP]"),
        (r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b", "[IP]"),
        (
            r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
            "[PHONE]",
        ),
        (r"\b(?:\d{4}[-\s]?){3}\d{4}\b", "[CARD]"),
        (r"password[=:]\S+", "password=[REDACTED]"),
        (r"(?:api[_-]?key|token|secret|auth)[=:]\S+", "[API_KEY]"),
        (r"session[_-]?id[=:]\S+", "session_id=[REDACTED]"),
    ]

    def __init__(self, name=""):
        super().__init__(name)
        self.compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), replacement)
            for pattern, replacement in self.PII_PATTERNS
        ]

    def _sanitize(self, value: str) -> str:
        text = value
        for pattern, replacement in self.compiled_patterns:
            text = pattern.sub(replacement, text)
        return text

    def filter(self, record):
        if record.msg:
            record.msg = self._sanitize(str(record.msg))

        if record.args:
            sanitized = []
            for arg in record.args:
                if isinstance(arg, str):
                    sanitized.append(self._sanitize(arg))
                else:
                    sanitized.append(arg)
            record.args = tuple(sanitized)

        return True


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "logger": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        request_id = get_request_id()
        if request_id:
            payload["request_id"] = request_id

        if has_request_context():
            payload["path"] = request.path
            payload["method"] = request.method
            payload["remote_addr"] = request.remote_addr

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=True)


def _build_formatter() -> logging.Formatter:
    json_default = "true" if IS_PRODUCTION else "false"
    use_json = os.getenv("LOG_JSON", json_default).lower() in ("1", "true", "yes")
    if use_json:
        return JsonFormatter()
    return logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def setup_logging(app):
    LOGS_FOLDER.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("remind")
    logger.setLevel(logging.DEBUG if not IS_PRODUCTION else logging.INFO)
    logger.propagate = False

    # Prevent duplicate handlers when app factory is reused (tests/CLI).
    if getattr(logger, "_remind_configured", False):
        app.logger.handlers = logger.handlers
        app.logger.setLevel(logger.level)
        return logger

    pii_filter = PIIFilter()
    formatter = _build_formatter()

    handlers = [
        logging.handlers.RotatingFileHandler(
            str(LOGS_FOLDER / "app.log"), maxBytes=10 * 1024 * 1024, backupCount=10
        ),
        logging.handlers.RotatingFileHandler(
            str(LOGS_FOLDER / "security.log"), maxBytes=10 * 1024 * 1024, backupCount=20
        ),
        logging.handlers.RotatingFileHandler(
            str(LOGS_FOLDER / "error.log"), maxBytes=10 * 1024 * 1024, backupCount=20
        ),
        logging.handlers.RotatingFileHandler(
            str(LOGS_FOLDER / "access.log"), maxBytes=10 * 1024 * 1024, backupCount=10
        ),
        logging.handlers.RotatingFileHandler(
            str(LOGS_FOLDER / "model.log"), maxBytes=10 * 1024 * 1024, backupCount=10
        ),
        logging.StreamHandler(),
    ]

    levels = [
        logging.DEBUG,
        logging.WARNING,
        logging.ERROR,
        logging.INFO,
        logging.INFO,
        logging.INFO if IS_PRODUCTION else logging.DEBUG,
    ]

    for handler, level in zip(handlers, levels):
        handler.setLevel(level)
        handler.addFilter(pii_filter)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    app.logger.handlers = logger.handlers
    app.logger.setLevel(logger.level)
    for handler in app.logger.handlers:
        handler.addFilter(pii_filter)

    logger._remind_configured = True
    return logger


def get_model_logger():
    return logging.getLogger("remind.model")


def log_model_request(model_name, latency_ms, tokens_in=None, tokens_out=None, success=True):
    logger = get_model_logger()
    logger.info(
        "Model: %s, Latency: %sms, Tokens: %s/%s, Status: %s",
        model_name,
        latency_ms,
        tokens_in or "N/A",
        tokens_out or "N/A",
        "OK" if success else "ERROR",
    )


def log_security_event(logger, event_type, details, level=logging.WARNING):
    if not logger:
        return

    message = f"[{event_type}] {details}"
    if level == logging.CRITICAL:
        logger.critical(message)
    elif level == logging.ERROR:
        logger.error(message)
    elif level == logging.WARNING:
        logger.warning(message)
    else:
        logger.info(message)


def log_suspicious_activity(logger, user_id, activity_type, ip_address, details):
    message = (
        "Suspicious activity detected - "
        f"User: {user_id}, Type: {activity_type}, IP: {ip_address}, Details: {details}"
    )
    log_security_event(logger, "SUSPICIOUS_ACTIVITY", message, logging.WARNING)


def log_auth_attempt(logger, email, success, ip_address, reason=None):
    status = "SUCCESS" if success else "FAILED"
    message = f"Auth attempt ({status}) - Email: {email}, IP: {ip_address}"
    if reason:
        message += f", Reason: {reason}"
    level = logging.INFO if success else logging.WARNING
    log_security_event(logger, "AUTH_ATTEMPT", message, level)


def log_file_upload(logger, user_id, filename, size, mime_type, success, error=None):
    status = "SUCCESS" if success else "FAILED"
    message = (
        "File upload "
        f"({status}) - User: {user_id}, File: {filename}, Size: {size}, MIME: {mime_type}"
    )
    if error:
        message += f", Error: {error}"
    level = logging.INFO if success else logging.WARNING
    log_security_event(logger, "FILE_UPLOAD", message, level)
