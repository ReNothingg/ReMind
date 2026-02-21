import secrets
import json
from flask import session, request, current_app
from functools import wraps

CSRF_TOKEN_LENGTH = 32
CSRF_SESSION_KEY = '_csrf_token'
CSRF_COOKIE_KEY = 'csrf_token'


def generate_csrf_token():

    if CSRF_SESSION_KEY not in session:
        session[CSRF_SESSION_KEY] = secrets.token_urlsafe(CSRF_TOKEN_LENGTH)
    return session[CSRF_SESSION_KEY]


def get_csrf_token():

    return session.get(CSRF_SESSION_KEY, '')


def validate_csrf_token(token):
    if not token or not isinstance(token, str):
        return False

    expected_token = session.get(CSRF_SESSION_KEY)
    if not expected_token:
        return False
    return secrets.compare_digest(token, expected_token)


def get_csrf_token_from_request():
    token = request.headers.get('X-CSRF-Token')
    if token:
        return token
    token = request.form.get('csrf_token')
    if token:
        return token
    try:
        if request.is_json:
            data = request.get_json(silent=True) or {}
            token = data.get('csrf_token') or data.get('_csrf_token')
            if token:
                return token
    except Exception:
        pass

    return None


def csrf_exempt(view_func):
    @wraps(view_func)
    def decorated_function(*args, **kwargs):
        request.environ['csrf_exempt'] = True
        return view_func(*args, **kwargs)
    return decorated_function


def require_csrf_token(view_func):
    @wraps(view_func)
    def decorated_function(*args, **kwargs):
        if request.method in ['GET', 'HEAD', 'OPTIONS']:
            return view_func(*args, **kwargs)
        if request.environ.get('csrf_exempt'):
            return view_func(*args, **kwargs)
        token = get_csrf_token_from_request()
        if not token or not validate_csrf_token(token):
            from utils.responses import make_error
            return make_error(
                'CSRF token validation failed',
                status=403,
                code='csrf_validation_failed'
            )

        return view_func(*args, **kwargs)

    return decorated_function


def setup_csrf_protection(app):
    @app.before_request
    def before_request():
        generate_csrf_token()
        if request.method in ['GET', 'HEAD', 'OPTIONS']:
            return

        if request.environ.get('csrf_exempt'):
            return

        if session.get('user_id') is None:
            return

        token = get_csrf_token_from_request()
        if not token or not validate_csrf_token(token):
            from utils.responses import make_error
            return make_error(
                'CSRF token validation failed',
                status=403,
                code='csrf_validation_failed'
            )

    @app.context_processor
    def inject_csrf_token():

        return {'csrf_token': generate_csrf_token}


def add_csrf_token_to_response(response):
    if 'X-CSRF-Token' not in response.headers:
        token = get_csrf_token()
        if token:
            response.headers['X-CSRF-Token'] = token
            try:
                secure_cookie = bool(current_app.config.get('SESSION_COOKIE_SECURE', False))
                samesite = current_app.config.get('SESSION_COOKIE_SAMESITE', 'Lax')
                response.set_cookie(
                    CSRF_COOKIE_KEY,
                    token,
                    secure=secure_cookie,
                    httponly=False,
                    samesite=samesite,
                    path='/',
                )
            except Exception:
                pass
    return response
