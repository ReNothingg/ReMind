import os
import time
from datetime import datetime, timedelta, timezone

from flask import Flask, g, request
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from config import (
    ALLOWED_HOSTS,
    ALLOWED_USER_AGENT_PATTERNS,
    BASE_PATH,
    BYPASS_USER_AGENT_VALIDATION_ROUTES,
    CHATS_FOLDER,
    CORS_ALLOW_CREDENTIALS,
    CORS_ALLOW_HEADERS,
    CORS_ALWAYS_SEND,
    CORS_EXPOSE_HEADERS,
    CORS_MAX_AGE,
    CORS_METHODS,
    CORS_ORIGINS,
    CORS_SEND_WILDCARD,
    CREATE_IMAGE_FOLDER,
    IS_PRODUCTION,
    MAX_CONTENT_LENGTH,
    SECRET_KEY,
    SESSION_COOKIE_DOMAIN,
    SESSION_COOKIE_NAME,
    SQLALCHEMY_DATABASE_URI,
    UPLOAD_FOLDER,
    VALIDATE_USER_AGENT,
)
from routes.api import api_bp
from utils.audit_log import AuditEvents, log_audit_event
from utils.auth import setup_auth
from utils.csrf_protection import add_csrf_token_to_response, setup_csrf_protection
from utils.logger_config import setup_logging
from utils.observability import finish_request_context, start_request_context
from utils.privacy import anonymize_ip
from utils.responses import logger, make_error
from utils.security_headers import apply_security_headers
from utils.session_security import (
    RequestAwareSessionInterface,
    configure_session,
)
from utils.user_agent_validator import UserAgentValidator, log_suspicious_user_agent


def create_app():
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
    app.config["APP_STARTED_AT"] = datetime.now(timezone.utc)
    app.config["APP_STARTED_MONOTONIC"] = time.perf_counter()
    app.config.from_mapping(
        UPLOAD_FOLDER=str(UPLOAD_FOLDER),
        CHATS_FOLDER=str(CHATS_FOLDER),
        CREATE_IMAGE_FOLDER=str(CREATE_IMAGE_FOLDER),
        MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
        SECRET_KEY=SECRET_KEY,
        SQLALCHEMY_DATABASE_URI=SQLALCHEMY_DATABASE_URI,
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
    app.config["SESSION_COOKIE_HTTPONLY"] = True 
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_NAME"] = SESSION_COOKIE_NAME
    app.config["SESSION_COOKIE_DOMAIN"] = SESSION_COOKIE_DOMAIN
    configure_session(app)
    app.session_interface = RequestAwareSessionInterface()

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

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
    def attach_request_context():
        start_request_context()

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
            log_audit_event(
                AuditEvents.SECURITY_SUSPICIOUS_UA,
                {"endpoint": request.path, "method": request.method},
            )
            return make_error(error_message, status=403, code="invalid_user_agent")
        g.anonymized_ip = anonymize_ip(request.remote_addr)

    @app.after_request
    def add_security_headers(response):
        response = add_csrf_token_to_response(response)
        response = apply_security_headers(response)
        response = finish_request_context(response)

        return response

    @app.errorhandler(413)
    def handle_request_entity_too_large(e):
        return make_error("File too large.", status=413, code="request_entity_too_large")

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
