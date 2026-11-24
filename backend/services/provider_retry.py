from __future__ import annotations

import math
import time
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from random import uniform

import requests
import urllib3

RETRY_CODES = ("EMPTY_RESPONSE", "RATE_LIMIT", "SERVER", "TIMEOUT", "TRANSPORT")
RETRY_WINDOW_SECONDS = 45
MAX_RETRIES = 8
MAX_ALWAYS_RETRIES = 12
SERVER_STATUSES = {500, 502, 503, 504, 507, 529}


@dataclass(frozen=True)
class Backoff:
    initialDelayMs: int = 500
    maxDelayMs: int = 10_000
    jitterRatio: float = 0.1


@dataclass(frozen=True)
class RetryPolicy:
    mode: str = "normal"
    maxRetries: int = 5
    retryableCodes: tuple[str, ...] = RETRY_CODES
    backoff: Backoff = Backoff()

    def to_dict(self):
        return asdict(self)


DEFAULT_RETRY_POLICY = RetryPolicy()


def resolve_retry_policy(value):
    if value is None:
        return DEFAULT_RETRY_POLICY
    if not isinstance(value, dict) or set(value) - {
        "mode",
        "maxRetries",
        "retryableCodes",
        "backoff",
    }:
        raise ValueError("invalid_retry_policy")
    mode = value.get("mode", "normal")
    if mode not in ("normal", "always"):
        raise ValueError("invalid_retry_policy")
    retries = value.get("maxRetries", DEFAULT_RETRY_POLICY.maxRetries)
    codes = value.get("retryableCodes", RETRY_CODES)
    if mode == "normal":
        if type(retries) is not int or not 0 <= retries <= MAX_RETRIES:
            raise ValueError("invalid_retry_policy")
        if (
            not isinstance(codes, (list, tuple))
            or not codes
            or any(not isinstance(code, str) or code not in RETRY_CODES for code in codes)
            or len(set(codes)) != len(codes)
        ):
            raise ValueError("invalid_retry_policy")
    else:
        retries, codes = MAX_ALWAYS_RETRIES, RETRY_CODES
    raw_backoff = value.get("backoff", {})
    if not isinstance(raw_backoff, dict) or set(raw_backoff) - {
        "initialDelayMs",
        "maxDelayMs",
        "jitterRatio",
    }:
        raise ValueError("invalid_retry_policy")
    initial = raw_backoff.get("initialDelayMs", 500)
    maximum = raw_backoff.get("maxDelayMs", 10_000)
    jitter = raw_backoff.get("jitterRatio", 0.1)
    if (
        type(initial) is not int
        or type(maximum) is not int
        or not 100 <= initial <= maximum <= 15_000
        or type(jitter) not in (int, float)
        or not 0 <= jitter <= 1
    ):
        raise ValueError("invalid_retry_policy")
    return RetryPolicy(mode, retries, tuple(codes), Backoff(initial, maximum, float(jitter)))


def retry_failure_for_status(status):
    if status in (204,):
        return "EMPTY_RESPONSE"
    if status == 408:
        return "TIMEOUT"
    if status == 429:
        return "RATE_LIMIT"
    if status in SERVER_STATUSES:
        return "SERVER"
    return None


def _connect_failure(error):
    if isinstance(error, urllib3.exceptions.NewConnectionError):
        return "TRANSPORT"
    if isinstance(error, (requests.ConnectTimeout, urllib3.exceptions.ConnectTimeoutError)):
        return "TIMEOUT"
    cause = getattr(error, "reason", None) or (error.args[0] if error.args else None)
    if isinstance(cause, urllib3.exceptions.NewConnectionError):
        return "TRANSPORT"
    if isinstance(cause, urllib3.exceptions.MaxRetryError) and isinstance(
        cause.reason, urllib3.exceptions.NewConnectionError
    ):
        return "TRANSPORT"
    return None


def _retry_after(raw):
    if not isinstance(raw, str) or not raw or len(raw) > 120:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        try:
            value = (parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds()
        except (OverflowError, TypeError, ValueError):
            return None
    return max(0, value) if math.isfinite(value) else None


class RetryWindow:
    def __init__(self, policy, control):
        self.policy = policy
        self.control = control
        self.deadline = time.monotonic() + RETRY_WINDOW_SECONDS
        self.retries = 0

    def delay(self, code, header=None):
        policy = self.policy
        if not policy or code not in policy.retryableCodes or self.retries >= policy.maxRetries:
            return None
        backoff = policy.backoff
        maximum = backoff.maxDelayMs / 1000
        retry_after = _retry_after(header)
        if retry_after is not None and retry_after > maximum:
            return None
        scheduled = min(maximum, backoff.initialDelayMs * 2**self.retries / 1000)
        local = min(
            maximum, max(0.1, scheduled * uniform(1 - backoff.jitterRatio, 1 + backoff.jitterRatio))
        )
        delay = max(local, retry_after or 0)
        return delay if time.monotonic() + delay < self.deadline else None

    def wait(self, delay):
        self.retries += 1
        if self.control is None:
            time.sleep(delay)
        else:
            self.control.stopped.wait(delay)
            self.control.check()


@contextmanager
def retry_response(open_response, policy, control, *, window=None):
    window = window or RetryWindow(policy, control)
    while True:
        if control is not None:
            control.check()
        with ExitStack() as stack:
            try:
                response = stack.enter_context(open_response())
            except (requests.RequestException, urllib3.exceptions.HTTPError) as error:
                delay = window.delay(_connect_failure(error))
                if delay is None:
                    raise
            else:
                code = retry_failure_for_status(response.status_code)
                if response.status_code == 200 and response.headers.get("Content-Length") == "0":
                    code = "EMPTY_RESPONSE"
                delay = window.delay(code, response.headers.get("Retry-After"))
                if delay is None:
                    yield response
                    return
        window.wait(delay)


def retry_first_event(open_stream, policy, control, classify, *, window=None):
    window = window or RetryWindow(policy, control)
    while True:
        if control is not None:
            control.check()
        stream = None
        try:
            stream = iter(open_stream())
            first = next(stream)
        except StopIteration:
            delay = window.delay("EMPTY_RESPONSE")
            if delay is None:
                return
        except Exception as error:
            if control is not None:
                control.check()
            response = getattr(error, "response", None)
            headers = getattr(response, "headers", None)
            delay = window.delay(classify(error), headers.get("Retry-After") if headers else None)
            if delay is None:
                raise
        else:
            yield first
            yield from stream
            return
        finally:
            if stream is not None and hasattr(stream, "close"):
                stream.close()
        window.wait(delay)
