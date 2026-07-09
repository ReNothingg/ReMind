import os
from ipaddress import ip_network
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

env_path = os.getenv("DOTENV_PATH", os.path.join(os.path.dirname(__file__), ".env"))
if os.getenv("LOAD_DOTENV", "true").lower() not in ("0", "false", "no"):
    load_dotenv(dotenv_path=env_path)

BASE_PATH: Path = Path(__file__).resolve().parent

DB_PATH: Path = BASE_PATH / "database"

UPLOAD_FOLDER: Path = DB_PATH / "uploads"
CHATS_FOLDER: Path = DB_PATH / "chats"
CREATE_IMAGE_FOLDER: Path = DB_PATH / "generated_images"

LOGS_FOLDER: Path = BASE_PATH / "logs"

for folder in [UPLOAD_FOLDER, CHATS_FOLDER, CREATE_IMAGE_FOLDER, LOGS_FOLDER]:
    folder.mkdir(parents=True, exist_ok=True)

try:
    MAX_CONTENT_LENGTH: int = int(os.getenv("MAX_CONTENT_LENGTH", 10 * 1024 * 1024))
except ValueError:
    MAX_CONTENT_LENGTH: int = 10 * 1024 * 1024

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
DEFAULT_LANGUAGE: str = "ru"

_flask_debug = os.getenv("FLASK_DEBUG", "0")
_is_debug = _flask_debug == "1" or _flask_debug.lower() == "true"
IS_PRODUCTION = not _is_debug and os.getenv("FLASK_ENV") != "development"

DEBUG_MODE = _is_debug
TESTING = False


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _sqlite_directory_usable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".sqlite_probe_{os.getpid()}.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def _normalize_host_entry(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if raw.startswith("."):
        return raw.lower()

    candidate = raw
    if "://" in raw:
        parsed = urlparse(raw)
        candidate = parsed.hostname or ""
    else:
        parsed = urlparse(f"//{raw}")
        candidate = parsed.hostname or raw
    candidate = candidate.split("/")[0].split("?")[0].split("#")[0].strip()
    if not candidate:
        return ""

    return candidate.lower()


ALLOWED_HOSTS = []
for host in ("127.0.0.1", "localhost"):
    normalized = _normalize_host_entry(host)
    if normalized:
        ALLOWED_HOSTS.append(normalized)

if os.getenv("ALLOWED_HOSTS"):
    for raw_host in os.getenv("ALLOWED_HOSTS").split(","):
        normalized = _normalize_host_entry(raw_host)
        if normalized and normalized not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(normalized)

CORS_ORIGINS = []
_DEV_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8000",
    "http://localhost:5000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

if not IS_PRODUCTION:
    CORS_ORIGINS.extend(_DEV_CORS_ORIGINS)
if os.getenv("CORS_ORIGINS"):
    CORS_ORIGINS.extend([o.strip() for o in os.getenv("CORS_ORIGINS").split(",") if o.strip()])
CORS_ORIGINS = [o for o in CORS_ORIGINS if o != "*"]
CORS_ALLOW_LOCAL_ORIGINS = _env_bool("CORS_ALLOW_LOCAL_ORIGINS", default=not IS_PRODUCTION)
if not CORS_ALLOW_LOCAL_ORIGINS:
    CORS_ORIGINS = [
        origin
        for origin in CORS_ORIGINS
        if _normalize_host_entry(origin) not in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
    ]

CORS_ALLOW_HEADERS = [
    "Content-Type",
    "Authorization",
    "X-Requested-With",
    "X-CSRF-Token",
    "X-Request-Id",
    "Accept",
    "Accept-Language",
]

CORS_EXPOSE_HEADERS = [
    "Content-Type",
    "X-CSRF-Token",
    "X-Request-Id",
    "X-Total-Count",
    "X-Page-Number",
]

CORS_METHODS = ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"]
CORS_MAX_AGE = 3600
CORS_ALLOW_CREDENTIALS = True
CORS_SEND_WILDCARD = False
CORS_ALWAYS_SEND = True

_DEFAULT_OPERATIONAL_ALLOWED_NETWORKS = (
    "127.0.0.1/32," "::1/128," "10.0.0.0/8," "172.16.0.0/12," "192.168.0.0/16," "fc00::/7"
)
_raw_operational_networks = os.getenv(
    "OPERATIONAL_ENDPOINT_ALLOWED_NETWORKS",
    _DEFAULT_OPERATIONAL_ALLOWED_NETWORKS,
)
OPERATIONAL_ENDPOINT_ALLOWED_NETWORKS = []
for raw_network in _raw_operational_networks.split(","):
    candidate = raw_network.strip()
    if not candidate:
        continue
    try:
        OPERATIONAL_ENDPOINT_ALLOWED_NETWORKS.append(ip_network(candidate, strict=False))
    except ValueError:
        continue

PUBLIC_METRICS_ENABLED = _env_bool("PUBLIC_METRICS_ENABLED", default=False)
PUBLIC_OPENAPI_ENABLED = _env_bool("PUBLIC_OPENAPI_ENABLED", default=False)

SERVER_THREADS: int = 8
SERVER_CONNECTION_LIMIT: int = 200
SERVER_CHANNEL_TIMEOUT: int = 300

SECRET_KEY = os.getenv("SECRET_KEY")

_database_url = os.getenv("DATABASE_URL")
if _database_url:
    _db_url = _database_url.strip()
    if _db_url.startswith("sqlite:///"):
        _sqlite_target = _db_url[len("sqlite:///") :]
        if _sqlite_target and _sqlite_target != ":memory:":
            if not Path(_sqlite_target).is_absolute():
                _sqlite_path = (BASE_PATH / _sqlite_target).resolve()
                target_parent = _sqlite_path.parent
            else:
                _sqlite_path = Path(_sqlite_target)
                target_parent = _sqlite_path.parent

            if not _sqlite_directory_usable(target_parent):
                fallback_sqlite_path = (BASE_PATH / "users.db").resolve()
                _sqlite_path = fallback_sqlite_path
                _sqlite_path.parent.mkdir(parents=True, exist_ok=True)

            SQLALCHEMY_DATABASE_URI = f"sqlite:///{_sqlite_path.as_posix()}"
        else:
            SQLALCHEMY_DATABASE_URI = _db_url
    else:
        SQLALCHEMY_DATABASE_URI = _db_url
else:
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{(DB_PATH / 'users.db').as_posix()}"
SQLALCHEMY_TRACK_MODIFICATIONS = False

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
IOS_OAUTH_REDIRECT_URI = (
    os.getenv("IOS_OAUTH_REDIRECT_URI", "remind://auth/google").strip() or "remind://auth/google"
)
IOS_OAUTH_CALLBACK_SCHEME = urlparse(IOS_OAUTH_REDIRECT_URI).scheme or "remind"


BACKEND_URL = os.getenv("BACKEND_URL", None)
if BACKEND_URL:
    backend_host = _normalize_host_entry(BACKEND_URL)
    if backend_host and backend_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(backend_host)

SESSION_COOKIE_DOMAIN = (os.getenv("SESSION_COOKIE_DOMAIN") or "").strip() or None
ALLOW_CROSS_SUBDOMAIN_SESSION_COOKIE = _env_bool(
    "ALLOW_CROSS_SUBDOMAIN_SESSION_COOKIE", default=False
)
if SESSION_COOKIE_DOMAIN and not ALLOW_CROSS_SUBDOMAIN_SESSION_COOKIE:
    SESSION_COOKIE_DOMAIN = None
SESSION_COOKIE_NAME = (
    os.getenv("SESSION_COOKIE_NAME") or "remind_session"
).strip() or "remind_session"

TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "")
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
LOCALHOST_MODE = os.getenv("LOCALHOST_MODE", "False").lower() in ("1", "true", "yes")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME")
AI_PROVIDER_API_KEY = os.getenv("AI_PROVIDER_API_KEY") or GEMINI_API_KEY
AI_PROVIDER_MODEL_NAME = os.getenv("AI_PROVIDER_MODEL_NAME") or GEMINI_MODEL_NAME
GITHUB_APP_ID = os.getenv("GITHUB_APP_ID", "").strip()
GITHUB_APP_CLIENT_ID = os.getenv("GITHUB_APP_CLIENT_ID", "").strip()
GITHUB_APP_CLIENT_SECRET = os.getenv("GITHUB_APP_CLIENT_SECRET", "").strip()
GITHUB_APP_SLUG = os.getenv("GITHUB_APP_SLUG", "").strip()
GITHUB_APP_PRIVATE_KEY = os.getenv("GITHUB_APP_PRIVATE_KEY", "").strip()
GITHUB_APP_PRIVATE_KEY_PATH = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH", "").strip()
GITHUB_PUBLIC_BASE_URL = os.getenv("GITHUB_PUBLIC_BASE_URL", "").strip().rstrip("/")
GITHUB_BRANCH_PREFIX = os.getenv("GITHUB_BRANCH_PREFIX", "remind").strip() or "remind"
GITHUB_OAUTH_ENCRYPTION_KEY = os.getenv("GITHUB_OAUTH_ENCRYPTION_KEY", "").strip()
try:
    GITHUB_OAUTH_STATE_TTL_SECONDS = max(
        60, int(os.getenv("GITHUB_OAUTH_STATE_TTL_SECONDS", "600"))
    )
except ValueError:
    GITHUB_OAUTH_STATE_TTL_SECONDS = 600
try:
    GITHUB_OAUTH_CREDENTIAL_TTL_SECONDS = max(
        60, int(os.getenv("GITHUB_OAUTH_CREDENTIAL_TTL_SECONDS", "900"))
    )
except ValueError:
    GITHUB_OAUTH_CREDENTIAL_TTL_SECONDS = 900
try:
    GITHUB_AGENT_MAX_FILE_CHARS = int(os.getenv("GITHUB_AGENT_MAX_FILE_CHARS", "80000"))
except ValueError:
    GITHUB_AGENT_MAX_FILE_CHARS = 80000
try:
    GITHUB_AGENT_MAX_PLAN_FILES = int(os.getenv("GITHUB_AGENT_MAX_PLAN_FILES", "8"))
except ValueError:
    GITHUB_AGENT_MAX_PLAN_FILES = 8

if not SECRET_KEY:
    if IS_PRODUCTION:
        raise ValueError("SECRET_KEY must be set when production settings are active")

    import secrets

    SECRET_KEY = secrets.token_hex(32)

try:

    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 ReMindBot/1.0"
)

ALLOWED_USER_AGENT_PATTERNS = [
    r"Mozilla/5\.0.*Chrome/.*Safari",
    r"Mozilla/5\.0.*Firefox/",
    r"Mozilla/5\.0.*Safari/.*Version/",
    r"Mozilla/5\.0.*Edg/",
    r"Mozilla/5\.0.*OPR/",
    r"AppleWebKit/.*Safari",
    r"^com\.apple\.WebKit\.Networking/",
]

VALIDATE_USER_AGENT: bool = os.getenv("VALIDATE_USER_AGENT", "True").lower() in (
    "1",
    "true",
    "yes",
)

BYPASS_USER_AGENT_VALIDATION_ROUTES = [
    r"^/health",
    r"^/metrics",
    r"^/openapi\\.json$",
    r"^/status",
    r"^/$",
    r"^/index\.html$",
    r"^/yandex_34c67fdadc366239\.html$",
]

ALLOW_GUEST_CHATS_SAVE: bool = os.getenv("ALLOW_GUEST_CHATS_SAVE", "False").lower() in (
    "1",
    "true",
    "yes",
)

try:
    TEMPORARY_CHAT_RETENTION_DAYS: int = int(os.getenv("TEMPORARY_CHAT_RETENTION_DAYS", "30"))
except ValueError:
    TEMPORARY_CHAT_RETENTION_DAYS = 30

try:
    SECURITY_LOG_RETENTION_DAYS: int = int(os.getenv("SECURITY_LOG_RETENTION_DAYS", "30"))
except ValueError:
    SECURITY_LOG_RETENTION_DAYS = 30

WEB_SEARCH_ENABLED: bool = os.getenv("WEB_SEARCH_ENABLED", "True").lower() in (
    "1",
    "true",
    "yes",
)

WEB_SEARCH_MAX_RESULTS = 10

try:
    WEB_SEARCH_FETCH_TIMEOUT_SECONDS: float = float(
        os.getenv("WEB_SEARCH_FETCH_TIMEOUT_SECONDS", "12")
    )
except ValueError:
    WEB_SEARCH_FETCH_TIMEOUT_SECONDS = 12.0
try:
    WEB_SEARCH_MAX_RESPONSE_BYTES: int = int(
        os.getenv("WEB_SEARCH_MAX_RESPONSE_BYTES", str(512 * 1024))
    )
except ValueError:
    WEB_SEARCH_MAX_RESPONSE_BYTES = 512 * 1024
try:
    WEB_SEARCH_PAGE_TEXT_CHARS: int = int(os.getenv("WEB_SEARCH_PAGE_TEXT_CHARS", "2200"))
except ValueError:
    WEB_SEARCH_PAGE_TEXT_CHARS = 2200

ENABLE_STRICT_HTTPS = os.getenv(
    "ENABLE_STRICT_HTTPS", "true" if IS_PRODUCTION else "false"
).lower() in ("1", "true", "yes")

RATELIMIT_ENABLED = True
RATELIMIT_STORAGE_URL = os.getenv("REDIS_URL", "memory://")
