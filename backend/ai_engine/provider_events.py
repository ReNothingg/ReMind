from __future__ import annotations

import json
import re
from itertools import chain

from backend.ai_engine.errors import ProviderRequestError

MAX_STREAM_BYTES = 4 * 1024 * 1024
MAX_EVENT_BYTES = 1_250_000
MAX_TOOL_CALLS = 32
MAX_TOOL_ARGUMENT_BYTES = 1_100_000
SSE_DONE = object()
LINE_END = re.compile(rb"\r\n|\n|\r(?!$)")
CONTEXT_ERROR = re.compile(
    r"context[_ ](length|window).{0,50}(exceed|limit|too long)|"
    r"maximum context length|prompt is too long|input.{0,30}too many tokens",
    re.I,
)


class ProviderStreamError(ProviderRequestError):
    def __init__(
        self,
        code="provider_unavailable",
        status=503,
        *,
        retry_code=None,
        wire_status=None,
        stream_unsupported=False,
    ):
        super().__init__(code, status)
        self.retry_code = retry_code
        self.wire_status = wire_status
        self.stream_unsupported = stream_unsupported


def incomplete_stream():
    return ProviderStreamError(retry_code="TRANSPORT")


def empty_response():
    return ProviderStreamError(retry_code="EMPTY_RESPONSE")


def provider_error(details):
    details = details if isinstance(details, dict) else {}
    tags = {
        str(details[field]).lower()[:120]
        for field in ("type", "status", "code")
        if isinstance(details.get(field), (str, int))
    }
    text = details.get("message")
    if tags & {"context_length_exceeded", "context_window_exceeded"} or (
        isinstance(text, str) and CONTEXT_ERROR.search(text[:1000])
    ):
        return ProviderStreamError("model_context_exceeded", 422)
    if tags & {"rate_limit_error", "rate_limit_exceeded", "resource_exhausted", "429"}:
        return ProviderStreamError("provider_rate_limited", 429, retry_code="RATE_LIMIT")
    if tags & {"insufficient_quota", "quota_exceeded"}:
        return ProviderStreamError("provider_rate_limited", 429)
    if tags & {"unauthenticated", "authentication_error", "permission_denied", "401", "403"}:
        return ProviderStreamError("provider_access_denied", 403)
    if tags & {
        "overloaded_error",
        "api_error",
        "server_error",
        "internal",
        "unavailable",
        "500",
        "502",
        "503",
        "529",
    }:
        return ProviderStreamError(retry_code="SERVER")
    return ProviderStreamError()


def usage_count(value):
    return value if type(value) is int and 0 <= value < 2**53 else None


def _invalid_constant(_):
    raise ValueError("invalid_provider_json")


def tool_arguments(raw):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_TOOL_ARGUMENT_BYTES:
        raise ProviderStreamError()
    try:
        parsed = json.loads(raw, parse_constant=_invalid_constant)
    except (ValueError, RecursionError):
        raise ProviderStreamError() from None
    if not isinstance(parsed, dict):
        raise ProviderStreamError()
    return parsed


def _decode_json(data):
    try:
        event = json.loads(data, parse_constant=_invalid_constant)
    except (ValueError, RecursionError):
        raise ProviderStreamError() from None
    if not isinstance(event, dict):
        raise ProviderStreamError()
    return event


def _decode_frame(frame):
    data = b"\n".join(frame).strip()
    return SSE_DONE if data == b"[DONE]" else _decode_json(data)


def _bounded_chunks(response, control=None, *, limit=MAX_STREAM_BYTES):
    total = 0
    for chunk in response.iter_content(1024):
        if control is not None:
            control.check()
        total += len(chunk)
        if total > limit:
            raise ProviderStreamError()
        if chunk:
            yield chunk
    if control is not None:
        control.check()


def json_response(response, control=None, *, limit=MAX_STREAM_BYTES):
    return _decode_json(b"".join(_bounded_chunks(response, control, limit=limit)))


def has_json_body(response):
    media_type = getattr(response, "headers", {}).get("Content-Type", "").split(";", 1)[0]
    return media_type.strip().lower() == "application/json" or media_type.strip().lower().endswith(
        "+json"
    )


def _event_frames(chunks):
    pending = bytearray()
    frame = []
    frame_size = 0
    first_line = True
    search_from = 0
    for chunk in chunks:
        pending.extend(chunk)
        position = 0
        for match in LINE_END.finditer(pending, search_from):
            line = bytes(pending[position : match.start()])
            position = match.end()
            if first_line:
                line = line.removeprefix(b"\xef\xbb\xbf")
                first_line = False
            if not line:
                if frame:
                    if any(frame):
                        yield _decode_frame(frame)
                    frame.clear()
                    frame_size = 0
            elif line == b"data" or line.startswith(b"data:"):
                data = line[5:].removeprefix(b" ")
                frame_size += len(data) + 1
                if frame_size > MAX_EVENT_BYTES:
                    raise ProviderStreamError()
                frame.append(data)
        del pending[:position]
        search_from = max(0, len(pending) - 1)
        if len(pending) > MAX_EVENT_BYTES:
            raise ProviderStreamError()
    if frame and pending in (b"", b"\r") and any(frame):
        yield _decode_frame(frame)


def stream_events(response, control=None):
    return _event_frames(_bounded_chunks(response, control))


def response_objects(response, control=None):
    if has_json_body(response):
        return True, iter((json_response(response, control),))
    chunks = iter(_bounded_chunks(response, control))
    first = next(chunks, b"")
    source = chain((first,), chunks)
    if first.removeprefix(b"\xef\xbb\xbf").lstrip().startswith(b"{"):
        return True, iter((_decode_json(b"".join(source)),))
    return False, _event_frames(source)
