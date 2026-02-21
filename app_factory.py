import os
from datetime import timedelta
from flask import Flask, request, g
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from config import (
    BASE_PATH,
    UPLOAD_FOLDER,
    CHATS_FOLDER,
    CREATE_IMAGE_FOLDER,
    MAX_CONTENT_LENGTH,
    SECRET_KEY,
    CORS_ORIGINS,
    CORS_ALLOW_HEADERS,
    CORS_EXPOSE_HEADERS,
    CORS_METHODS,
    CORS_MAX_AGE,
    CORS_ALLOW_CREDENTIALS,
    CORS_SEND_WILDCARD,
    CORS_ALWAYS_SEND,
    VALIDATE_USER_AGENT,
    ALLOWED_USER_AGENT_PATTERNS,
    BYPASS_USER_AGENT_VALIDATION_ROUTES,
    IS_PRODUCTION,
    ALLOWED_HOSTS,
)
from utils.auth import setup_auth
from utils.user_agent_validator import UserAgentValidator, log_suspicious_user_agent
from utils.responses import make_error, logger
from utils.csrf_protection import setup_csrf_protection, add_csrf_token_to_response
from utils.logger_config import setup_logging
from utils.security_headers import apply_security_headers, get_safe_error_response
from utils.session_security import configure_session, update_session_activity
from utils.audit_log import log_audit_event, AuditEvents
from utils.privacy import anonymize_ip
from routes.api import api_bp

def create_app():
    is_production = IS_PRODUCTION or not os.environ.get("FLASK_ENV")
    dist_dir = BASE_PATH / "dist"
    public_dir = BASE_PATH / "public"
    if dist_dir.exists():
        static_folder = str(dist_dir)
    elif public_dir.exists():
        static_folder = str(public_dir)
    else:
        static_folder = str(dist_dir)

    app = Flask(
        __name__,
        static_folder=static_folder,
        static_url_path="",
        template_folder="templates",
    )
    app.config.from_mapping(
        UPLOAD_FOLDER=str(UPLOAD_FOLDER),
        CHATS_FOLDER=str(CHATS_FOLDER),
        CREATE_IMAGE_FOLDER=str(CREATE_IMAGE_FOLDER),
        MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
        SECRET_KEY=SECRET_KEY,
        SQLALCHEMY_DATABASE_URI=app.config.get("SQLALCHEMY_DATABASE_URI") or f"sqlite:///{BASE_PATH}/database/users.db",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
        PREFERRED_URL_SCHEME="https",
        REDIS_URL=os.getenv("REDIS_URL"),
        CELERY_BROKER_URL=os.getenv("CELERY_BROKER_URL"),
        CELERY_RESULT_BACKEND=os.getenv("CELERY_RESULT_BACKEND"),
    )
    if ALLOWED_HOSTS:
        app.config["TRUSTED_HOSTS"] = ALLOWED_HOSTS
    import redis
    app.config["SESSION_TYPE"] = "redis"
    app.config["SESSION_PERMANENT"] = True
    app.config["SESSION_USE_SIGNER"] = True
    app.config["SESSION_REDIS"] = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    app.config["SESSION_COOKIE_SECURE"] = IS_PRODUCTION
    app.config["SESSION_COOKIE_HTTPONLY"] = True  # No JS access
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"  # CSRF protection
    app.config["SESSION_COOKIE_NAME"] = "remind_session"  # Custom cookie name
    configure_session(app)

    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1
    )

    CORS(
        app,
        origins=CORS_ORIGINS,
        allow_headers=CORS_ALLOW_HEADERS,
        expose_headers=CORS_EXPOSE_HEADERS,
        methods=CORS_METHODS,
        max_age=CORS_MAX_AGE,
        supports_credentials=CORS_ALLOW_CREDENTIALS,
        send_wildcard=CORS_SEND_WILDCARD,
        always_send=CORS_ALWAYS_SEND,
    )

    setup_auth(app)
    setup_logging(app)
    setup_csrf_protection(app)

    for folder in [UPLOAD_FOLDER, CHATS_FOLDER, CREATE_IMAGE_FOLDER]:
        folder.mkdir(parents=True, exist_ok=True)

    user_agent_validator = UserAgentValidator(
        allowed_patterns=ALLOWED_USER_AGENT_PATTERNS,
        bypass_routes=BYPASS_USER_AGENT_VALIDATION_ROUTES,
        enabled=VALIDATE_USER_AGENT,
    )

    @app.before_request
    def validate_user_agent():
        is_valid, error_message = user_agent_validator.validate_request()

        if not is_valid:
            log_suspicious_user_agent(
                user_agent=request.headers.get("User-Agent"),
                ip=anonymize_ip(request.remote_addr),
                endpoint=request.path,
                additional_info={"method": request.method},
            )
            log_audit_event(AuditEvents.SECURITY_SUSPICIOUS_UA, {
                'endpoint': request.path,
                'method': request.method
            })
            return make_error(error_message, status=403, code="invalid_user_agent")
        g.anonymized_ip = anonymize_ip(request.remote_addr)

    @app.after_request
    def add_security_headers(response):
        response = add_csrf_token_to_response(response)
        response = apply_security_headers(response)

        return response

    @app.errorhandler(413)
    def handle_request_entity_too_large(e):
        return make_error(
            f"File too large.", status=413, code="request_entity_too_large"
        )

    @app.errorhandler(401)
    def handle_401(e):
        return make_error("Authentication required", status=401, code="auth_required")

    @app.errorhandler(403)
    def handle_403(e):
        return make_error("Access denied", status=403, code="access_denied")

    @app.errorhandler(404)
    def handle_404(e):
        return make_error("Not found", status=404, code="not_found")

    @app.errorhandler(400)
    def handle_400(e):
        return make_error("Bad request", status=400, code="bad_request")

    @app.errorhandler(405)
    def handle_405(e):
        return make_error("Method not allowed", status=405, code="method_not_allowed")

    @app.errorhandler(429)
    def handle_429(e):
        return make_error("Too many requests", status=429, code="rate_limit_exceeded")

    @app.errorhandler(500)
    def handle_500(e):
        logger.error(f"Unhandled 500 error: {e}")
        return make_error("Internal server error", status=500, code="internal_error")

    @app.errorhandler(502)
    def handle_502(e):
        return make_error("Service unavailable", status=502, code="service_unavailable")

    @app.errorhandler(503)
    def handle_503(e):
        return make_error("Service temporarily unavailable", status=503, code="service_unavailable")
    app.register_blueprint(api_bp)

    return app
