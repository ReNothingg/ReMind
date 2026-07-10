from urllib.parse import urlparse

from flask import g, has_request_context, request

from config import BACKEND_URL, CORS_ORIGINS, ENABLE_STRICT_HTTPS

JSON_LD_SCRIPT_HASH = "'sha256-eOo7R2QxzL/n0WXjk+i1Gj3T+BbZVyQd3/ZhRDi4nig='"
HTML_PREVIEW_PATH = "/html-preview.html"


def _origin_from_url(raw_url: str | None) -> str | None:
    if not raw_url:
        return None
    try:
        parsed = urlparse(raw_url)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https", "ws", "wss"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _configured_connect_sources() -> list[str]:
    sources = ["'self'", "https://challenges.cloudflare.com"]
    for raw_origin in [BACKEND_URL, *CORS_ORIGINS]:
        origin = _origin_from_url(raw_origin)
        if origin and origin not in sources:
            sources.append(origin)
    return sources


def _script_sources() -> list[str]:
    sources = ["'self'", JSON_LD_SCRIPT_HASH, "https://challenges.cloudflare.com"]
    if has_request_context():
        nonce = getattr(g, "csp_nonce", "")
        if nonce:
            sources.insert(1, f"'nonce-{nonce}'")
    return sources


def get_csp_header():
    directives = [
        "default-src 'self'",
        f"script-src {' '.join(_script_sources())}",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net",
        "font-src 'self' https://fonts.gstatic.com https://fonts.googleapis.com https://cdn.jsdelivr.net data:",
        "img-src 'self' data: https: blob:",
        "media-src 'self' https: blob:",
        f"connect-src {' '.join(_configured_connect_sources())}",
        "frame-src 'self' https://challenges.cloudflare.com",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "upgrade-insecure-requests" if ENABLE_STRICT_HTTPS else "",
        "block-all-mixed-content" if ENABLE_STRICT_HTTPS else "",
    ]

    return "; ".join(d for d in directives if d)


def get_html_preview_csp_header():
    return "; ".join([
        "default-src 'none'",
        "script-src 'unsafe-inline' 'unsafe-eval' data: blob: http: https:",
        "style-src 'unsafe-inline' data: blob: http: https:",
        "img-src data: blob: http: https:",
        "font-src data: blob: http: https:",
        "media-src data: blob: http: https:",
        "connect-src http: https:",
        "frame-src 'self' data: blob: http: https:",
        "worker-src blob:",
        "form-action http: https:",
        "base-uri 'none'",
        "frame-ancestors 'self'",
    ])


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
    is_html_preview = bool(has_request_context() and request.path == HTML_PREVIEW_PATH)
    if is_html_preview:
        response.headers["Content-Security-Policy"] = get_html_preview_csp_header()
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Permissions-Policy"] = get_permissions_policy()
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        return response

    response.headers["Content-Security-Policy"] = get_csp_header()
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = get_permissions_policy()
    if ENABLE_STRICT_HTTPS:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
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
