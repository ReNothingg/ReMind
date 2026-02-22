import re
import time
import uuid
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict

from flask import g, has_request_context, request


REQUEST_ID_HEADER = "X-Request-Id"
TRACKED_ENDPOINTS = {"/chat", "/translate", "/synthesize"}
TIMEOUT_THRESHOLD_MS = 8_000.0


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


def finish_request_context(response):
    request_id = get_request_id()
    if request_id:
        response.headers.setdefault(REQUEST_ID_HEADER, request_id)

    started_at = getattr(g, "request_started_at", None)
    path = request.path if has_request_context() else ""
    if (
        started_at is not None
        and path in TRACKED_ENDPOINTS
    ):
        duration_ms = (time.perf_counter() - started_at) * 1000.0
        metrics_registry.observe(path, response.status_code, duration_ms)
    return response


@dataclass
class EndpointMetric:
    request_total: int = 0
    error_total: int = 0
    timeout_total: int = 0
    latency_ms_sum: float = 0.0
    latency_ms_count: int = 0


@dataclass
class MetricsRegistry:
    _data: Dict[str, EndpointMetric] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def observe(self, endpoint: str, status_code: int, latency_ms: float) -> None:
        with self._lock:
            metric = self._data.get(endpoint)
            if metric is None:
                metric = EndpointMetric()
                self._data[endpoint] = metric

            metric.request_total += 1
            metric.latency_ms_sum += max(0.0, latency_ms)
            metric.latency_ms_count += 1

            if status_code >= 500:
                metric.error_total += 1
            if status_code == 504 or latency_ms >= TIMEOUT_THRESHOLD_MS:
                metric.timeout_total += 1

    def snapshot(self) -> Dict[str, EndpointMetric]:
        with self._lock:
            return {
                endpoint: EndpointMetric(
                    request_total=value.request_total,
                    error_total=value.error_total,
                    timeout_total=value.timeout_total,
                    latency_ms_sum=value.latency_ms_sum,
                    latency_ms_count=value.latency_ms_count,
                )
                for endpoint, value in self._data.items()
            }


metrics_registry = MetricsRegistry()


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def export_prometheus_metrics() -> str:
    snapshot = metrics_registry.snapshot()
    lines = [
        "# HELP remind_endpoint_requests_total Total requests for tracked endpoints.",
        "# TYPE remind_endpoint_requests_total counter",
        "# HELP remind_endpoint_errors_total Total 5xx responses for tracked endpoints.",
        "# TYPE remind_endpoint_errors_total counter",
        "# HELP remind_endpoint_timeouts_total Total timeout-like responses for tracked endpoints.",
        "# TYPE remind_endpoint_timeouts_total counter",
        "# HELP remind_endpoint_latency_ms_sum Total latency in milliseconds for tracked endpoints.",
        "# TYPE remind_endpoint_latency_ms_sum counter",
        "# HELP remind_endpoint_latency_ms_count Total latency samples for tracked endpoints.",
        "# TYPE remind_endpoint_latency_ms_count counter",
    ]

    for endpoint in sorted(snapshot.keys()):
        metric = snapshot[endpoint]
        ep = _escape_label(endpoint)
        lines.append(
            f'remind_endpoint_requests_total{{endpoint="{ep}"}} {metric.request_total}'
        )
        lines.append(
            f'remind_endpoint_errors_total{{endpoint="{ep}"}} {metric.error_total}'
        )
        lines.append(
            f'remind_endpoint_timeouts_total{{endpoint="{ep}"}} {metric.timeout_total}'
        )
        lines.append(
            f'remind_endpoint_latency_ms_sum{{endpoint="{ep}"}} {metric.latency_ms_sum:.3f}'
        )
        lines.append(
            f'remind_endpoint_latency_ms_count{{endpoint="{ep}"}} {metric.latency_ms_count}'
        )

    return "\n".join(lines) + "\n"
