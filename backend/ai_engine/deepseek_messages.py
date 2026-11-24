from __future__ import annotations

from backend.ai_engine.errors import ProviderRequestError
from backend.ai_engine.provider_events import (
    MAX_TOOL_CALLS,
    SSE_DONE,
    empty_response,
    incomplete_stream,
    provider_error,
    response_objects,
    tool_arguments,
)

DEEPSEEK_EFFORTS = {"off", "low", "high", "max"}
CONTEXT_LIMITS = {
    "deepseek-v4-pro": 1_000_000,
    "deepseek-flash": 1_000_000,
    "deepseek-v4-flash": 1_000_000,
    "deepseek-v4-flash-vision-exp": 1_000_000,
}
USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)
DELTA_FIELDS = {
    "text_delta": ("text", "text"),
    "thinking_delta": ("thinking", "thinking"),
    "signature_delta": ("thinking", "signature"),
    "input_json_delta": ("tool_use", "partial_json"),
}


def merge_messages(messages):
    merged = []
    for message in messages:
        blocks = message["content"]
        if blocks:
            if merged and merged[-1]["role"] == message["role"]:
                merged[-1]["content"].extend(blocks)
            else:
                merged.append({"role": message["role"], "content": list(blocks)})
    pending = set()
    for message in merged:
        blocks = message["content"]
        if message["role"] == "assistant":
            if pending:
                raise ProviderRequestError("provider_unavailable")
            calls = [block["id"] for block in blocks if block["type"] == "tool_use"]
            pending = set(calls)
            if len(pending) != len(calls):
                raise ProviderRequestError("provider_unavailable")
        else:
            results = [block for block in blocks if block["type"] == "tool_result"]
            for block in results:
                if block["tool_use_id"] not in pending:
                    raise ProviderRequestError("provider_unavailable")
                pending.remove(block["tool_use_id"])
            if pending:
                raise ProviderRequestError("provider_unavailable")
            message["content"] = results + [
                block for block in blocks if block["type"] != "tool_result"
            ]
    if pending:
        raise ProviderRequestError("provider_unavailable")
    return merged


def build_request(model, messages, system, tools, effort, *, max_tokens=8192):
    if effort == "none":
        effort = "off"
    if not isinstance(effort, str) or effort not in DEEPSEEK_EFFORTS:
        effort = "high"
    body = {
        "model": model,
        "stream": True,
        "messages": merge_messages(messages),
        "system": system,
        "max_tokens": max_tokens,
        "thinking": {"type": "disabled" if effort == "off" else "enabled"},
    }
    if effort != "off":
        body["output_config"] = {"effort": effort}
    if tools:
        body["tools"] = [
            {
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["parameters"],
            }
            for tool in tools
        ]
    return body


def _update_usage(usage, raw):
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise ProviderRequestError("provider_unavailable")
    for field in USAGE_FIELDS:
        if field in raw:
            value = raw[field]
            if type(value) is not int or not 0 <= value < 2**53:
                raise ProviderRequestError("provider_unavailable")
            usage[field] = value


def stream_response(response, control=None):
    complete, events = response_objects(response, control)
    if complete:
        payload = next(events)
        if payload.get("error") is not None:
            raise provider_error(payload["error"])
        yield "finish", payload
        return
    blocks = {}
    deltas = {}
    stopped = set()
    started = False
    reason = None
    usage = {}
    for event in events:
        if event is SSE_DONE:
            break
        kind = event.get("type")
        if kind == "error":
            raise provider_error(event.get("error"))
        if kind == "message_start":
            if started:
                raise ProviderRequestError("provider_unavailable")
            started = True
            _update_usage(usage, event.get("message", {}).get("usage"))
            yield "start", None
            continue
        if kind not in {
            "content_block_start",
            "content_block_delta",
            "content_block_stop",
            "message_delta",
            "message_stop",
        }:
            continue
        if not started:
            raise ProviderRequestError("provider_unavailable")
        if kind == "message_stop":
            if usage:
                yield "usage", dict(usage)
            if reason == "refusal":
                raise ProviderRequestError("provider_refused", 422)
            if reason == "max_tokens":
                raise ProviderRequestError("provider_output_limit", 422)
            if reason not in {"end_turn", "stop_sequence", "tool_use"} or stopped != blocks.keys():
                raise ProviderRequestError("provider_unavailable")
            content = [blocks[index] for index in sorted(blocks)]
            calls = [block["id"] for block in content if block["type"] == "tool_use"]
            if (
                (reason == "tool_use") != bool(calls)
                or len(set(calls)) != len(calls)
                or len(calls) > MAX_TOOL_CALLS
            ):
                raise ProviderRequestError("provider_unavailable")
            yield "finish", {"content": content, "stop_reason": reason, "usage": usage}
            return
        if kind == "message_delta":
            reason = event["delta"].get("stop_reason") or reason
            _update_usage(usage, event.get("usage"))
            continue
        index = event["index"]
        if type(index) is not int or not 0 <= index <= 4096 or index in stopped:
            raise ProviderRequestError("provider_unavailable")
        if kind == "content_block_start":
            block = event["content_block"]
            if (
                index in blocks
                or reason
                or block["type"] not in {"text", "thinking", "redacted_thinking", "tool_use"}
            ):
                raise ProviderRequestError("provider_unavailable")
            block_type = block["type"]
            if block_type == "tool_use" and (
                not isinstance(block.get("id"), str)
                or not block["id"]
                or not isinstance(block.get("name"), str)
                or not block["name"]
                or not isinstance(block.get("input"), dict)
            ):
                raise ProviderRequestError("provider_unavailable")
            if block_type in {"text", "thinking"} and not isinstance(block.get(block_type), str):
                raise ProviderRequestError("provider_unavailable")
            if block_type == "redacted_thinking" and not isinstance(block.get("data"), str):
                raise ProviderRequestError("provider_unavailable")
            if "signature" in block and not isinstance(block["signature"], str):
                raise ProviderRequestError("provider_unavailable")
            blocks[index] = block
            deltas[index] = []
            if block_type == "text" and block["text"]:
                yield "text", block["text"]
            elif block_type == "tool_use":
                yield "tools", None
            elif block_type in ("thinking", "redacted_thinking"):
                yield "reasoning", None
        elif kind == "content_block_delta":
            block = blocks[index]
            delta = event["delta"]
            block_type, field = DELTA_FIELDS[delta["type"]]
            if block["type"] != block_type or not isinstance(delta[field], str):
                raise ProviderRequestError("provider_unavailable")
            if field == "partial_json":
                deltas[index].append(delta[field])
            else:
                block[field] = block.get(field, "") + delta[field]
                if field == "text" and delta[field]:
                    yield "text", delta[field]
        else:
            block = blocks[index]
            if raw := "".join(deltas[index]).strip():
                block["input"] = tool_arguments(raw)
            stopped.add(index)
    raise incomplete_stream() if started else empty_response()


def read_response(response):
    for kind, payload in stream_response(response):
        if kind == "finish":
            return payload
    raise ProviderRequestError("provider_unavailable")
