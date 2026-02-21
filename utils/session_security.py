import secrets
from functools import wraps
from flask import session, request, current_app
import hashlib
import time


def regenerate_session():
    session_data = dict(session)
    session.clear()
    session.modified = True
    for key, value in session_data.items():
        if key not in ('_id', '_fresh'):
            session[key] = value
    session['_created_at'] = time.time()
    session['_last_activity'] = time.time()
    session['_fingerprint'] = _generate_session_fingerprint()


def _generate_session_fingerprint():
    components = [
        request.headers.get('User-Agent', ''),
        request.headers.get('Accept-Language', ''),
    ]

    fingerprint_string = '|'.join(components)
    return hashlib.sha256(fingerprint_string.encode()).hexdigest()[:16]


def verify_session_fingerprint():
    stored_fingerprint = session.get('_fingerprint')
    if not stored_fingerprint:
        return True

    current_fingerprint = _generate_session_fingerprint()
    return secrets.compare_digest(stored_fingerprint, current_fingerprint)


def update_session_activity():
    session['_last_activity'] = time.time()
    session.modified = True


def check_session_timeout(max_inactive_seconds=3600):
    last_activity = session.get('_last_activity', 0)
    if last_activity == 0:
        return True

    return (time.time() - last_activity) < max_inactive_seconds


def invalidate_session():
    session.clear()
    session.modified = True


def secure_session_required(check_fingerprint=True, max_inactive_seconds=3600):
    def decorator(view_func):
        @wraps(view_func)
        def decorated_function(*args, **kwargs):
            from utils.responses import make_error
            from utils.audit_log import log_security_event, AuditEvents
            if 'user_id' not in session:
                return make_error(
                    "Authentication required",
                    status=401,
                    code='auth_required'
                )
            if not check_session_timeout(max_inactive_seconds):
                log_security_event(AuditEvents.SESSION_INVALIDATED, {
                    'reason': 'timeout'
                })
                invalidate_session()
                return make_error(
                    "Session expired",
                    status=401,
                    code='session_expired'
                )
            if check_fingerprint and not verify_session_fingerprint():
                log_security_event(AuditEvents.SESSION_FIXATION_ATTEMPT, {
                    'reason': 'fingerprint_mismatch'
                })
                current_app.logger.warning(
                    f"Session fingerprint mismatch for user {session.get('user_id')}"
                )
            update_session_activity()

            return view_func(*args, **kwargs)

        return decorated_function
    return decorator


class SessionConfig:
    COOKIE_SECURE = True  # Only send over HTTPS
    COOKIE_HTTPONLY = True  # No JavaScript access
    COOKIE_SAMESITE = 'Lax'  # CSRF protection
    PERMANENT_SESSION_LIFETIME = 7 * 24 * 3600  # 7 days
    SESSION_REFRESH_EACH_REQUEST = True
    MAX_INACTIVE_SECONDS = 3600  # 1 hour
    SESSION_KEY_BITS = 256  # Entropy for session ID


def configure_session(app):
    from config import IS_PRODUCTION
    app.config['SESSION_COOKIE_SECURE'] = IS_PRODUCTION
    app.config['SESSION_COOKIE_HTTPONLY'] = SessionConfig.COOKIE_HTTPONLY
    app.config['SESSION_COOKIE_SAMESITE'] = SessionConfig.COOKIE_SAMESITE
    app.config['PERMANENT_SESSION_LIFETIME'] = SessionConfig.PERMANENT_SESSION_LIFETIME
    app.config['SESSION_REFRESH_EACH_REQUEST'] = SessionConfig.SESSION_REFRESH_EACH_REQUEST
    app.config['SESSION_COOKIE_NAME'] = 'remind_session'
    @app.before_request
    def make_session_permanent():
        session.permanent = True
