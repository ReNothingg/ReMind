from flask import has_request_context, request
from config import IS_PRODUCTION


def get_csp_header():
    directives = [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com https://www.google.com https://www.googletagmanager.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com",
        "font-src 'self' https://fonts.gstatic.com https://fonts.googleapis.com https://cdn.jsdelivr.net data:",
        "img-src 'self' data: https: blob:",
        "media-src 'self' https: blob:",
        "connect-src 'self' https: wss: ws:",
        "frame-src 'self' https://challenges.cloudflare.com",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "upgrade-insecure-requests" if IS_PRODUCTION else "",
        "block-all-mixed-content" if IS_PRODUCTION else "",
    ]

    return "; ".join(d for d in directives if d)


def get_permissions_policy():
    policies = [
        "accelerometer=()",
        "autoplay=(self)",
        "camera=()",
        "cross-origin-isolated=()",
        "display-capture=()",
        "encrypted-media=()",
        "fullscreen=(self)",
        "geolocation=()",
        "gyroscope=()",
        "keyboard-map=()",
        "magnetometer=()",
        "microphone=()",
        "midi=()",
        "payment=()",
        "picture-in-picture=()",
        "publickey-credentials-get=()",
        "screen-wake-lock=()",
        "sync-xhr=()",
        "usb=()",
        "web-share=()",
        "xr-spatial-tracking=()",
    ]

    return ", ".join(policies)


def apply_security_headers(response):
    response.headers["Content-Security-Policy"] = get_csp_header()
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = get_permissions_policy()
    if IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Embedder-Policy"] = "credentialless"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    content_type = (response.headers.get("Content-Type") or "").lower()
    is_json_response = "application/json" in content_type
    is_api_request = bool(has_request_context() and request.path.startswith("/api/"))
    if response.status_code in (401, 403) or is_json_response or is_api_request:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response
ERROR_TEMPLATES = {
    400: ("Bad Request", "bad_request"),
    401: ("Authentication required", "auth_required"),
    403: ("Access denied", "access_denied"),
    404: ("Resource not found", "not_found"),
    405: ("Method not allowed", "method_not_allowed"),
    413: ("Request too large", "request_too_large"),
    429: ("Too many requests", "rate_limit_exceeded"),
    500: ("Internal server error", "internal_error"),
    502: ("Service unavailable", "service_unavailable"),
    503: ("Service temporarily unavailable", "service_unavailable"),
}


def get_safe_error_response(status_code):
    message, code = ERROR_TEMPLATES.get(status_code, ("An error occurred", "error"))
    return {"error": message, "code": code}
