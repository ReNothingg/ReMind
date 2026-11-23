from __future__ import annotations

import secrets
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from authlib.integrations.flask_client import OAuth
from itsdangerous import BadData, URLSafeTimedSerializer

from backend.security.session_security import is_loopback_hostname

oauth = OAuth()


OAUTH_FALLBACK_STATE_COOKIE = "oauth_state_fallback"


OAUTH_FALLBACK_STATE_TTL_SECONDS = 900


MOBILE_GOOGLE_OAUTH_TOKEN_TTL_SECONDS = 180


def _is_allowed_hostname(hostname: str | None, allowed_hosts) -> bool:
    if not hostname:
        return False

    host = hostname.lower().strip(".")
    for allowed in allowed_hosts or []:
        allowed_host = (allowed or "").lower().strip()
        if not allowed_host:
            continue
        if allowed_host.startswith("."):
            suffix = allowed_host[1:].strip(".")
            if host == suffix or host.endswith(f".{suffix}"):
                return True
            continue
        if host == allowed_host.strip("."):
            return True
    return False


def _is_loopback_hostname(hostname: str) -> bool:
    return is_loopback_hostname(hostname)


def _is_safe_redirect_target(target: str, allowed_hosts) -> bool:
    if not target or not isinstance(target, str):
        return False
    if "\\" in target or any(ord(char) < 32 or ord(char) == 127 for char in target):
        return False

    parsed = urlparse(target)
    if not parsed.netloc:
        return target.startswith("/") and not target.startswith("//")

    if parsed.scheme not in ("http", "https"):
        return False

    return _is_allowed_hostname(parsed.hostname, allowed_hosts)


def _normalize_redirect_target(target: str, allowed_hosts) -> str:
    if not _is_safe_redirect_target(target, allowed_hosts):
        return ""

    parsed = urlparse(target)
    if not parsed.netloc:
        return target

    normalized = parsed.path or "/"
    if parsed.params:
        normalized = f"{normalized};{parsed.params}"
    if parsed.query:
        normalized = f"{normalized}?{parsed.query}"
    if parsed.fragment:
        normalized = f"{normalized}#{parsed.fragment}"
    return normalized


def _oauth_state_serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="google-oauth-fallback-state")


def _encode_oauth_fallback_state(secret_key: str, payload: dict) -> str:
    serializer = _oauth_state_serializer(secret_key)
    return serializer.dumps(payload)


def _decode_oauth_fallback_state(
    secret_key: str,
    raw_value: str,
    max_age: int = OAUTH_FALLBACK_STATE_TTL_SECONDS,
):
    if not raw_value or not secret_key:
        return None
    serializer = _oauth_state_serializer(secret_key)
    try:
        data = serializer.loads(raw_value, max_age=max_age)
    except BadData:
        return None
    return data if isinstance(data, dict) else None


def _mobile_google_oauth_serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="google-mobile-oauth")


def _encode_mobile_google_oauth_token(secret_key: str, user_id: int) -> str:
    serializer = _mobile_google_oauth_serializer(secret_key)
    return serializer.dumps(
        {
            "aud": "remind-ios-google",
            "user_id": user_id,
            "nonce": secrets.token_urlsafe(16),
        }
    )


def _decode_mobile_google_oauth_token(
    secret_key: str,
    raw_value: str,
    max_age: int = MOBILE_GOOGLE_OAUTH_TOKEN_TTL_SECONDS,
):
    if not raw_value or not secret_key:
        return None
    serializer = _mobile_google_oauth_serializer(secret_key)
    try:
        data = serializer.loads(raw_value, max_age=max_age)
    except BadData:
        return None
    if not isinstance(data, dict) or data.get("aud") != "remind-ios-google":
        return None
    return data


def _is_allowed_mobile_oauth_redirect_uri(raw_value: str, configured_uri: str) -> bool:
    candidate = (raw_value or "").strip()
    configured = (configured_uri or "").strip()
    if not candidate or candidate != configured:
        return False

    parsed = urlparse(candidate)
    return bool(parsed.scheme and parsed.netloc == "auth" and parsed.path.rstrip("/") == "/google")


def _append_url_query(raw_url: str, params: dict[str, str]) -> str:
    parsed = urlparse(raw_url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.extend((key, value) for key, value in params.items() if value is not None)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _resolve_oauth_redirect_base(
    request_host_url: str,
    backend_url: str | None,
    allowed_hosts,
    preferred_target: str = "",
) -> str:
    parsed_target = urlparse(preferred_target or "")
    if (
        parsed_target.scheme in ("http", "https")
        and parsed_target.netloc
        and _is_allowed_hostname(parsed_target.hostname, allowed_hosts)
    ):
        return f"{parsed_target.scheme}://{parsed_target.netloc}"

    request_host = urlparse(request_host_url).hostname
    if request_host and _is_loopback_hostname(request_host):
        return request_host_url.rstrip("/")

    if backend_url:
        return backend_url.rstrip("/")

    if not _is_allowed_hostname(request_host, allowed_hosts):
        return ""

    return request_host_url.rstrip("/")
