import logging
import logging.handlers
import re
from pathlib import Path
from config import LOGS_FOLDER, IS_PRODUCTION


class PIIFilter(logging.Filter):
    PII_PATTERNS = [
        (r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[EMAIL]'),
        (r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '[IP]'),
        (r'\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b', '[IP]'),
        (r'\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b', '[PHONE]'),
        (r'\b(?:\d{4}[-\s]?){3}\d{4}\b', '[CARD]'),
        (r'password[=:]\S+', 'password=[REDACTED]'),
        (r'(?:api[_-]?key|token|secret|auth)[=:]\S+', '[API_KEY]'),
        (r'session[_-]?id[=:]\S+', 'session_id=[REDACTED]'),
    ]

    def __init__(self, name=''):
        super().__init__(name)
        self.compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), replacement)
            for pattern, replacement in self.PII_PATTERNS
        ]

    def filter(self, record):
        if record.msg:
            msg = str(record.msg)
            for pattern, replacement in self.compiled_patterns:
                msg = pattern.sub(replacement, msg)
            record.msg = msg

        if record.args:
            args = []
            for arg in record.args:
                if isinstance(arg, str):
                    for pattern, replacement in self.compiled_patterns:
                        arg = pattern.sub(replacement, arg)
                args.append(arg)
            record.args = tuple(args)

        return True


def setup_logging(app):
    LOGS_FOLDER.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('remind')
    logger.setLevel(logging.DEBUG if not IS_PRODUCTION else logging.INFO)
    pii_filter = PIIFilter()
    all_logs_handler = logging.handlers.RotatingFileHandler(
        str(LOGS_FOLDER / 'app.log'),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=10,
    )
    all_logs_handler.setLevel(logging.DEBUG)
    all_logs_handler.addFilter(pii_filter)
    security_handler = logging.handlers.RotatingFileHandler(
        str(LOGS_FOLDER / 'security.log'),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=20,
    )
    security_handler.setLevel(logging.WARNING)
    security_handler.addFilter(pii_filter)
    error_handler = logging.handlers.RotatingFileHandler(
        str(LOGS_FOLDER / 'error.log'),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=20,
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.addFilter(pii_filter)
    access_handler = logging.handlers.RotatingFileHandler(
        str(LOGS_FOLDER / 'access.log'),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=10,
    )
    access_handler.setLevel(logging.INFO)
    access_handler.addFilter(pii_filter)
    model_handler = logging.handlers.RotatingFileHandler(
        str(LOGS_FOLDER / 'model.log'),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=10,
    )
    model_handler.setLevel(logging.INFO)
    model_handler.addFilter(pii_filter)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO if IS_PRODUCTION else logging.DEBUG)
    console_handler.addFilter(pii_filter)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    for handler in [all_logs_handler, security_handler, error_handler, access_handler, model_handler, console_handler]:
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    app.logger.handlers = logger.handlers
    app.logger.setLevel(logger.level)
    for handler in app.logger.handlers:
        handler.addFilter(pii_filter)

    return logger


def get_model_logger():

    return logging.getLogger('remind.model')


def log_model_request(model_name, latency_ms, tokens_in=None, tokens_out=None, success=True):

    logger = get_model_logger()
    logger.info(
        f"Model: {model_name}, Latency: {latency_ms}ms, "
        f"Tokens: {tokens_in or 'N/A'}/{tokens_out or 'N/A'}, "
        f"Status: {'OK' if success else 'ERROR'}"
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
    message = f"Suspicious activity detected - User: {user_id}, Type: {activity_type}, IP: {ip_address}, Details: {details}"
    log_security_event(logger, 'SUSPICIOUS_ACTIVITY', message, logging.WARNING)


def log_auth_attempt(logger, email, success, ip_address, reason=None):
    status = 'SUCCESS' if success else 'FAILED'
    message = f"Auth attempt ({status}) - Email: {email}, IP: {ip_address}"
    if reason:
        message += f", Reason: {reason}"
    level = logging.INFO if success else logging.WARNING
    log_security_event(logger, 'AUTH_ATTEMPT', message, level)


def log_file_upload(logger, user_id, filename, size, mime_type, success, error=None):
    status = 'SUCCESS' if success else 'FAILED'
    message = f"File upload ({status}) - User: {user_id}, File: {filename}, Size: {size}, MIME: {mime_type}"
    if error:
        message += f", Error: {error}"
    level = logging.INFO if success else logging.WARNING
    log_security_event(logger, 'FILE_UPLOAD', message, level)


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
    message = f"Suspicious activity detected - User: {user_id}, Type: {activity_type}, IP: {ip_address}, Details: {details}"
    log_security_event(logger, 'SUSPICIOUS_ACTIVITY', message, logging.WARNING)


def log_auth_attempt(logger, email, success, ip_address, reason=None):
    status = 'SUCCESS' if success else 'FAILED'
    message = f"Auth attempt ({status}) - Email: {email}, IP: {ip_address}"
    if reason:
        message += f", Reason: {reason}"
    level = logging.INFO if success else logging.WARNING
    log_security_event(logger, 'AUTH_ATTEMPT', message, level)


def log_file_upload(logger, user_id, filename, size, mime_type, success, error=None):
    status = 'SUCCESS' if success else 'FAILED'
    message = f"File upload ({status}) - User: {user_id}, File: {filename}, Size: {size}, MIME: {mime_type}"
    if error:
        message += f", Error: {error}"
    level = logging.INFO if success else logging.WARNING
    log_security_event(logger, 'FILE_UPLOAD', message, level)
