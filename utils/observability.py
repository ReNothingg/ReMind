import re
import time
import uuid

from flask import g, has_request_context, request
from prometheus_client import Counter, Histogram, generate_latest

REQUEST_ID_HEADER = "X-Request-Id"
TRACKED_ENDPOINTS = {"/chat", "/translate", "/synthesize"}
TIMEOUT_THRESHOLD_MS = 8_000.0

REQUESTS_TOTAL = Counter(
    "remind_http_requests_total",
    "Total tracked HTTP requests.",
    ["endpoint", "method", "status"],
)
REQUEST_LATENCY_SECONDS = Histogram(
    "remind_http_request_duration_seconds",
    "Request latency for tracked endpoints.",
    ["endpoint", "method"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0),
)
REQUEST_ERRORS_TOTAL = Counter(
    "remind_http_errors_total",
    "Total 5xx responses for tracked endpoints.",
    ["endpoint", "method"],
)
REQUEST_TIMEOUTS_TOTAL = Counter(
    "remind_http_timeouts_total",
    "Total timeout-like requests for tracked endpoints.",
    ["endpoint", "method"],
)
ERROR_BUDGET_BURN_TOTAL = Counter(
    "remind_error_budget_burn_total",
    "Error budget burn events (5xx responses).",
    ["endpoint", "method"],
)


def _is_valid_request_id(value: str) -> bool:
    if not value or len(value) > 128:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9._-]{8,128}", value))


def resolve_request_id(incoming: str) -> str:
    raw = (incoming or "").strip()
    if _is_valid_request_id(raw):
        return raw
    return uuid.uuid4().hex


def start_request_context() -> None:
    rid = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
    g.request_id = rid
    g.request_started_at = time.perf_counter()


def get_request_id(default=None):
    if not has_request_context():
        return default
    return getattr(g, "request_id", default)


def _observe_request(endpoint: str, method: str, status_code: int, duration_seconds: float) -> None:
    status = str(int(status_code))
    REQUESTS_TOTAL.labels(endpoint=endpoint, method=method, status=status).inc()
    REQUEST_LATENCY_SECONDS.labels(endpoint=endpoint, method=method).observe(
        max(0.0, duration_seconds)
    )

    if status_code >= 500:
        REQUEST_ERRORS_TOTAL.labels(endpoint=endpoint, method=method).inc()
        ERROR_BUDGET_BURN_TOTAL.labels(endpoint=endpoint, method=method).inc()

    if status_code == 504 or (duration_seconds * 1000.0) >= TIMEOUT_THRESHOLD_MS:
        REQUEST_TIMEOUTS_TOTAL.labels(endpoint=endpoint, method=method).inc()


def finish_request_context(response):
    request_id = get_request_id()
    if request_id:
        response.headers.setdefault(REQUEST_ID_HEADER, request_id)

    started_at = getattr(g, "request_started_at", None)
    if started_at is None or not has_request_context():
        return response

    path = request.path
    if path in TRACKED_ENDPOINTS:
        duration_seconds = time.perf_counter() - started_at
        _observe_request(
            endpoint=path,
            method=request.method,
            status_code=response.status_code,
            duration_seconds=duration_seconds,
        )

    return response


def export_prometheus_metrics() -> str:
    return generate_latest().decode("utf-8")
