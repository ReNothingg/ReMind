import json
import hashlib
import logging
import logging.handlers
from datetime import datetime
from pathlib import Path
from functools import wraps
from flask import request, session, g, has_request_context

from config import LOGS_FOLDER, IS_PRODUCTION
audit_logger = logging.getLogger('remind.audit')
audit_logger.setLevel(logging.INFO)
_audit_handler = logging.handlers.RotatingFileHandler(
    str(LOGS_FOLDER / 'audit.log'),
    maxBytes=50 * 1024 * 1024,  # 50 MB
    backupCount=30,  # Keep 30 files (about 1 month if daily rotation)
)
_audit_handler.setFormatter(logging.Formatter(
    '%(asctime)s - AUDIT - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
audit_logger.addHandler(_audit_handler)


def _hash_identifier(identifier):
    if not identifier:
        return None
    return hashlib.sha256(str(identifier).encode()).hexdigest()[:16]


def _get_client_info():
    if not has_request_context():
        return {}

    info = {
        'ip_hash': _hash_identifier(request.remote_addr),
        'endpoint': request.endpoint,
        'method': request.method,
    }
    ua = request.headers.get('User-Agent', '')
    if 'Mobile' in ua:
        info['client_type'] = 'mobile'
    elif 'Tablet' in ua:
        info['client_type'] = 'tablet'
    else:
        info['client_type'] = 'desktop'

    return info


def log_audit_event(event_type, details=None, user_id=None, severity='INFO'):
    try:
        event = {
            'timestamp': datetime.utcnow().isoformat(),
            'event_type': event_type,
            'user_hash': _hash_identifier(user_id) if user_id else None,
            'session_hash': _hash_identifier(session.get('user_id')) if has_request_context() and session else None,
        }
        event.update(_get_client_info())
        if details:
            safe_details = {}
            for key, value in details.items():
                if key.lower() in ('password', 'token', 'secret', 'api_key', 'credit_card'):
                    safe_details[key] = '[REDACTED]'
                elif key.lower() in ('email', 'phone', 'ip', 'ip_address'):
                    safe_details[key] = _hash_identifier(value)
                else:
                    safe_details[key] = value
            event['details'] = safe_details

        log_message = json.dumps(event, ensure_ascii=False)

        if severity == 'CRITICAL':
            audit_logger.critical(log_message)
        elif severity == 'ERROR':
            audit_logger.error(log_message)
        elif severity == 'WARNING':
            audit_logger.warning(log_message)
        else:
            audit_logger.info(log_message)

    except Exception as e:
        if not IS_PRODUCTION:
            print(f"Audit log error: {e}")
class AuditEvents:
    AUTH_LOGIN_SUCCESS = 'AUTH_LOGIN_SUCCESS'
    AUTH_LOGIN_FAILED = 'AUTH_LOGIN_FAILED'
    AUTH_LOGOUT = 'AUTH_LOGOUT'
    AUTH_REGISTER = 'AUTH_REGISTER'
    AUTH_PASSWORD_RESET_REQUEST = 'AUTH_PASSWORD_RESET_REQUEST'
    AUTH_PASSWORD_RESET_COMPLETE = 'AUTH_PASSWORD_RESET_COMPLETE'
    AUTH_EMAIL_CONFIRMED = 'AUTH_EMAIL_CONFIRMED'
    AUTH_2FA_ENABLED = 'AUTH_2FA_ENABLED'
    AUTH_2FA_DISABLED = 'AUTH_2FA_DISABLED'
    AUTH_OAUTH_LOGIN = 'AUTH_OAUTH_LOGIN'
    SESSION_CREATED = 'SESSION_CREATED'
    SESSION_INVALIDATED = 'SESSION_INVALIDATED'
    SESSION_FIXATION_ATTEMPT = 'SESSION_FIXATION_ATTEMPT'
    ACCESS_CHAT_VIEW = 'ACCESS_CHAT_VIEW'
    ACCESS_CHAT_EXPORT = 'ACCESS_CHAT_EXPORT'
    ACCESS_USER_DATA = 'ACCESS_USER_DATA'
    ACCESS_DENIED = 'ACCESS_DENIED'
    MODIFY_USER_SETTINGS = 'MODIFY_USER_SETTINGS'
    MODIFY_CHAT_SHARE = 'MODIFY_CHAT_SHARE'
    MODIFY_PASSWORD = 'MODIFY_PASSWORD'
    DELETE_CHAT = 'DELETE_CHAT'
    DELETE_ACCOUNT = 'DELETE_ACCOUNT'
    DELETE_USER_DATA = 'DELETE_USER_DATA'
    SECURITY_RATE_LIMIT = 'SECURITY_RATE_LIMIT'
    SECURITY_CSRF_FAILURE = 'SECURITY_CSRF_FAILURE'
    SECURITY_INVALID_TOKEN = 'SECURITY_INVALID_TOKEN'
    SECURITY_SUSPICIOUS_UA = 'SECURITY_SUSPICIOUS_UA'
    SECURITY_BRUTE_FORCE = 'SECURITY_BRUTE_FORCE'
    SECURITY_IDOR_ATTEMPT = 'SECURITY_IDOR_ATTEMPT'
    FILE_UPLOAD = 'FILE_UPLOAD'
    FILE_UPLOAD_BLOCKED = 'FILE_UPLOAD_BLOCKED'
    FILE_DELETE = 'FILE_DELETE'
    ADMIN_USER_MODIFY = 'ADMIN_USER_MODIFY'
    ADMIN_CONFIG_CHANGE = 'ADMIN_CONFIG_CHANGE'


def audit_action(event_type, include_request_data=False):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user_id = None
            details = {'function': func.__name__}
            if has_request_context():
                user_id = session.get('user_id')

                if include_request_data:
                    details['content_type'] = request.content_type
                    details['content_length'] = request.content_length

            try:
                result = func(*args, **kwargs)
                details['status'] = 'success'
                log_audit_event(event_type, details, user_id)
                return result
            except Exception as e:
                details['status'] = 'error'
                details['error_type'] = type(e).__name__
                log_audit_event(event_type, details, user_id, severity='ERROR')
                raise

        return wrapper
    return decorator


def log_auth_event(event_type, email=None, success=True, reason=None):
    details = {
        'success': success,
    }
    if reason:
        details['reason'] = reason
    if email:
        details['email_hash'] = _hash_identifier(email)

    severity = 'INFO' if success else 'WARNING'
    log_audit_event(event_type, details, severity=severity)


def log_security_event(event_type, details=None):
    log_audit_event(event_type, details, severity='WARNING')
