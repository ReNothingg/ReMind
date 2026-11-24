from __future__ import annotations

import json
import time
from contextlib import closing, contextmanager
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import quote

import requests
import urllib3

from backend.ai_engine.claude import _history_messages, _new_message_content, _ThoughtStream
from backend.ai_engine.compaction import compaction_output_limit
from backend.ai_engine.compatible_messages import (
    RoundReply,
    checked_call,
    completions_events,
    ensure_distinct_calls,
    google_events,
)
from backend.ai_engine.deepseek_messages import (
    CONTEXT_LIMITS,
    build_request,
    merge_messages,
    stream_response,
)
from backend.ai_engine.errors import ProviderRequestError
from backend.ai_engine.gemini import _execution_activity, _model_activity_token
from backend.ai_engine.output_contract import ReplyPreview, output_contract_errors
from backend.ai_engine.provider_events import (
    ProviderStreamError,
    empty_response,
    has_json_body,
    json_response,
    provider_error,
    usage_count,
)
from backend.security.public_http import public_http_request
from backend.services.agent_models import (
    PROVIDERS,
    key_route,
    platform_route,
    provider_headers,
)
from backend.services.chat.cancellation import interruptible, stop_http_stream
from backend.services.chat.provider_replay import begin_replay, wire_prefix
from backend.services.context_usage import (
    build_context_usage,
    context_weights,
    enforce_model_context,
)
from backend.services.provider_retry import RetryWindow, retry_first_event, retry_response
from backend.services.tools.model_runtime import ModelRuntime
from backend.services.tools.tool_execution import ToolExecution
from backend.services.tools.tool_protocol import serialize_tool_output


def _completions_content(message):
    parts = []
    for block in message["content"]:
        if block["type"] == "text":
            parts.append({"type": "text", "text": block["text"]})
        elif message["role"] == "user" and block["type"] == "image":
            source = block["source"]
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{source['media_type']};base64,{source['data']}"},
                }
            )
    if any(part["type"] == "image_url" for part in parts):
        return parts
    return "\n".join(part["text"] for part in parts)


def _http_failure(response, control):
    code, status = {
        400: ("provider_model_unavailable", 400),
        401: ("provider_access_denied", 403),
        403: ("provider_access_denied", 403),
        404: ("provider_model_unavailable", 404),
        429: ("provider_rate_limited", 429),
    }.get(response.status_code, ("provider_unavailable", 503))
    unsupported = False
    if response.status_code in (400, 413, 415, 422) and has_json_body(response):
        try:
            details = json_response(response, control, limit=32_000).get("error")
        except (
            ProviderRequestError,
            OSError,
            requests.RequestException,
            urllib3.exceptions.HTTPError,
        ):
            details = None
        if isinstance(details, dict):
            possible = provider_error(details)
            if possible.code == "model_context_exceeded":
                return possible
            unsupported = details.get("code") in (
                "stream_unsupported",
                "streaming_not_supported",
                "unsupported_streaming",
            ) or (
                details.get("param") == "stream"
                and details.get("code") in ("unsupported_parameter", "invalid_parameter")
            )
    return ProviderStreamError(
        code, status, wire_status=response.status_code, stream_unsupported=unsupported
    )


@contextmanager
def _provider_response(route, path, body, control, *, retry_window=None):
    if control is not None:
        control.check()
    endpoint = (route.base or PROVIDERS[route.provider].base) + path
    headers = {
        **provider_headers(route.provider, route.key, route.protocol),
        "Content-Type": "application/json",
    }
    if body.get("stream") or path.endswith("?alt=sse"):
        headers["Accept"] = "text/event-stream, application/json"
    if route.provider == "deepseek":
        headers.update({"x-api-key": route.key, "anthropic-version": "2023-06-01"})
    data = json.dumps(body, ensure_ascii=False).encode()

    def open_response():
        timeout = control.timeout(95) if control is not None else 95
        return (
            public_http_request("POST", endpoint, headers=headers, body=data, timeout=timeout)
            if route.public_endpoint
            else requests.post(
                endpoint,
                headers=headers,
                data=data,
                stream=True,
                timeout=(min(5, timeout), timeout),
                allow_redirects=False,
            )
        )

    try:
        with (
            retry_response(
                open_response, route.retry_policy, control, window=retry_window
            ) as response,
            interruptible(control, lambda: stop_http_stream(response)),
        ):
            if response.status_code != 200:
                raise _http_failure(response, control)
            yield response
    except (requests.RequestException, urllib3.exceptions.HTTPError, OSError) as error:
        if control is not None:
            control.check()
        retry_code = (
            "TIMEOUT"
            if isinstance(error, (requests.Timeout, urllib3.exceptions.TimeoutError, TimeoutError))
            else "TRANSPORT"
        )
        raise ProviderStreamError(retry_code=retry_code) from error
    except ValueError as error:
        raise ProviderStreamError() from error


def _round_events(route, path, body, control, parse, *, fallback=None):
    window = RetryWindow(route.retry_policy, control)

    def attempt():
        opened = False
        try:
            with _provider_response(route, path, body, control, retry_window=window) as response:
                opened = True
                yield from parse(response, control)
        except ProviderStreamError as error:
            if control is not None:
                control.check()
            if (
                opened
                or fallback is None
                or not (error.stream_unsupported or error.wire_status in fallback[2])
            ):
                raise
            fallback_path, fallback_body, _ = fallback
            with _provider_response(
                route, fallback_path, fallback_body, control, retry_window=window
            ) as response:
                yield from parse(response, control)

    return retry_first_event(
        attempt,
        route.retry_policy,
        control,
        lambda error: getattr(error, "retry_code", None),
        window=window,
    )


def _completions_request(route, messages, instructions, tools, data):
    body = {
        "model": route.model,
        "messages": [{"role": "system", "content": instructions}, *messages],
        "stream": True,
    }
    if tools:
        body["tools"] = [{"type": "function", "function": tool} for tool in tools]
    if route.max_tokens is not None:
        body["max_completion_tokens" if route.provider == "openai" else "max_tokens"] = (
            route.max_tokens
        )
    if effort := route.wire_effort(data.get("thinkingLevel") or data.get("thinking_level")):
        if route.provider == "openrouter":
            body["reasoning"] = {"effort": effort}
        else:
            body["reasoning_effort"] = effort
    if route.provider == "openai" and not route.public_endpoint:
        body["stream_options"] = {"include_usage": True}
    return body


def _anthropic_result(response):
    if response.get("stop_reason") == "max_tokens":
        raise ProviderRequestError("provider_output_limit", 422)
    if response.get("stop_reason") == "refusal":
        raise ProviderStreamError("provider_refused", 422)
    if response.get("stop_reason") not in {"end_turn", "tool_use", "stop_sequence"}:
        raise ProviderRequestError("provider_unavailable")
    parts = response.get("content")
    if not isinstance(parts, list) or any(not isinstance(block, dict) for block in parts):
        raise ProviderStreamError()
    visible = [block.get("text") for block in parts if block.get("type") == "text"]
    if any(not isinstance(text, str) for text in visible):
        raise ProviderStreamError()
    answer = "".join(visible)
    calls = [
        checked_call(block.get("id"), block.get("name"), block.get("input"))
        for block in parts
        if block.get("type") == "tool_use"
    ]
    ensure_distinct_calls(calls)
    if (response["stop_reason"] == "tool_use") != bool(calls):
        raise ProviderStreamError()
    if not answer.strip() and not calls:
        raise empty_response()
    usage = response.get("usage")
    tokens = usage_count(usage.get("input_tokens")) if isinstance(usage, dict) else None
    if tokens is not None:
        tokens += sum(
            usage_count(usage.get(key)) or 0
            for key in ("cache_read_input_tokens", "cache_creation_input_tokens")
        )
    return RoundReply(answer, {"role": "assistant", "content": parts}, calls, tokens)


def _native_message_events(response, control):
    for kind, payload in stream_response(response, control):
        if kind in ("text", "tools", "reasoning"):
            yield kind, payload
        elif kind == "finish":
            yield "finish", _anthropic_result(payload)


def _anthropic_request(route, messages, instructions, tools, data):
    body = {
        "model": route.model,
        "system": instructions,
        "messages": merge_messages(messages),
        "max_tokens": route.max_tokens or 8192,
        "stream": True,
    }
    if effort := route.wire_effort(data.get("thinkingLevel") or data.get("thinking_level")):
        body["output_config"] = {"effort": effort}
    if tools:
        body["tools"] = [
            {
                "name": item["name"],
                "description": item["description"],
                "input_schema": item["parameters"],
            }
            for item in tools
        ]
    return body


def _google_wire(messages):
    contents = []
    names = {}
    for message in messages:
        parts = []
        for block in message["content"]:
            kind = block["type"]
            if kind == "text":
                parts.append({"text": block["text"]})
            elif kind in {"image", "document"}:
                source = block["source"]
                parts.append(
                    {"inlineData": {"mimeType": source["media_type"], "data": source["data"]}}
                )
            elif kind == "google":
                parts.append(block["part"])
                call = block["part"].get("functionCall")
                if call is not None:
                    names[block["id"]] = call
            elif kind == "tool_result":
                call = names[block["tool_use_id"]]
                result = {"name": call["name"], "response": json.loads(block["content"])}
                if call.get("id"):
                    result["id"] = call["id"]
                parts.append({"functionResponse": result})
        if parts:
            contents.append(
                {"role": "model" if message["role"] == "assistant" else "user", "parts": parts}
            )
    return contents


def _google_request(route, messages, instructions, tools, data):
    body = {
        "systemInstruction": {"parts": [{"text": instructions}]},
        "contents": _google_wire(messages),
    }
    if tools:
        body["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": item["name"],
                        "description": item["description"],
                        "parametersJsonSchema": item["parameters"],
                    }
                    for item in tools
                ]
            }
        ]
    generation = {}
    if effort := route.wire_effort(data.get("thinkingLevel") or data.get("thinking_level")):
        generation["thinkingConfig"] = {"thinkingLevel": effort.upper()}
    if route.max_tokens is not None:
        generation["maxOutputTokens"] = route.max_tokens
    if generation:
        body["generationConfig"] = generation
    return body


def _model_round(route, messages, instructions, tools, data):
    control = data.get("_generation_control")
    if route.provider == "deepseek":
        body = build_request(
            route.model,
            messages,
            instructions,
            tools,
            route.wire_effort(data.get("thinkingLevel") or data.get("thinking_level")),
            max_tokens=route.max_tokens or 8192,
        )
        return _round_events(route, "/anthropic/v1/messages", body, control, _native_message_events)
    if route.protocol == "anthropic-messages":
        body = _anthropic_request(route, messages, instructions, tools, data)
        return _round_events(
            route,
            "/messages",
            body,
            control,
            _native_message_events,
            fallback=("/messages", {**body, "stream": False}, (501,)),
        )
    if route.protocol == "google-generative-ai":
        body = _google_request(route, messages, instructions, tools, data)
        model_path = "/models/" + quote(route.model, safe="")
        return _round_events(
            route,
            model_path + ":streamGenerateContent?alt=sse",
            body,
            control,
            lambda response, generation_control: google_events(
                response, generation_control, message_count=len(messages)
            ),
            fallback=(model_path + ":generateContent", body, (404, 405, 501)),
        )
    body = _completions_request(route, messages, instructions, tools, data)
    fallback_body = {**body, "stream": False}
    fallback_body.pop("stream_options", None)
    return _round_events(
        route,
        "/chat/completions",
        body,
        control,
        completions_events,
        fallback=("/chat/completions", fallback_body, (501,)),
    )


def _stream_model_round(route, messages, instructions, tools, data, thought, activity_id, number):
    preview = ReplyPreview()
    replied = False
    with closing(_model_round(route, messages, instructions, tools, data)) as events:
        for kind, payload in events:
            if not replied:
                replied = True
                if progress := thought.append(
                    _model_activity_token(activity_id, "model_responded", round_number=number),
                    separate=True,
                ):
                    yield progress
            if kind == "text":
                if update := preview.append(payload):
                    yield update
            elif kind == "tools":
                if update := preview.clear(block=True):
                    yield update
            elif kind == "finish":
                if update := preview.clear():
                    yield update
                return payload
    raise empty_response()


def _replay_head(route, instructions, tools, data):
    return [
        instructions, tools, route.max_tokens,
        route.wire_effort(data.get("thinkingLevel") or data.get("thinking_level")),
    ]


def _agent_turn(owner, data, route):
    runtime = ModelRuntime.create(owner, data)
    execution = ToolExecution(runtime)
    thought = _ThoughtStream(data.get("request_id"))
    replay_turn = begin_replay(
        owner,
        data,
        runtime,
        protocol=route.protocol,
        provider=route.provider,
        model=route.model,
        endpoint=route.base or PROVIDERS[route.provider].base,
        authority=route.key,
    )
    restoring = bool(replay_turn and replay_turn.previous_frames)
    native_history = route.protocol in {"anthropic-messages", "google-generative-ai"}
    initial = []
    for message in [
        *_history_messages(data, include_ids=restoring),
        {"role": "user", "content": _new_message_content(data)},
    ]:
        item = {
            "role": message["role"],
            "content": message["content"] if native_history else _completions_content(message),
        }
        initial.append((message.get("id"), item))
    plain = [item for _, item in initial]
    bounded_signatures = route.protocol == "anthropic-messages"
    messages = plain
    if restoring and replay_turn is not None:
        head = _replay_head(
            route, runtime.prompts.render(runtime.canvas), runtime.declarations(), data
        )
        messages = replay_turn.restore(initial, bound_head=head if bounded_signatures else None)
    step_limit = runtime.step_limit
    control = data.get("_generation_control")
    for index in range(step_limit + 1):
        if control is not None:
            control.check()
        tools = runtime.declarations() if index < step_limit and not execution.exhausted else []
        instructions = runtime.prompts.render(runtime.canvas)
        limit = route.context_window or (
            CONTEXT_LIMITS.get(route.model) if route.provider == "deepseek" else None
        )
        weights = None
        if limit is not None:
            weights = context_weights(instructions, tools, messages)
            if (
                index == 0
                and messages is not plain
                and sum(weights) + (route.max_tokens or 0) > limit
            ):
                messages = plain
                weights = context_weights(instructions, tools, messages)
            enforce_model_context(weights, limit, route.max_tokens)
        signature = (
            wire_prefix(_replay_head(route, instructions, tools, data), messages)
            if replay_turn is not None and bounded_signatures
            else None
        )
        activity_id = f"provider-{index}"
        if progress := thought.append(
            _model_activity_token(activity_id, "model_waiting", round_number=index + 1),
            separate=True,
        ):
            yield progress
        reply = yield from _stream_model_round(
            route, messages, instructions, tools, data, thought, activity_id, index + 1
        )
        if weights and (
            usage := build_context_usage(
                SimpleNamespace(prompt_token_count=reply.input_tokens), weights, limit
            )
        ):
            yield {"context_usage": usage}
        answer, replay, calls = reply.text, reply.replay, reply.calls
        if replay_turn is not None:
            replay_turn.append(replay, prefix=signature)
        if not calls:
            yield from thought.finalize()
            if not isinstance(answer, str) or not answer.strip() or output_contract_errors(answer):
                raise ProviderRequestError("provider_unavailable")
            if replay_turn is not None and (draft := replay_turn.finish()):
                yield draft
            yield answer
            return
        if not tools:
            raise ProviderRequestError("provider_unavailable")
        messages.append(replay)
        feedback = []
        for offset, call in enumerate(calls):
            if control is not None:
                control.check()
            activity = f"tool-{index}-{offset}"
            started = time.monotonic()
            if progress := thought.append(_execution_activity(call, activity), separate=True):
                yield progress
            result = execution.execute(call, offset)
            yield from result.events
            if result.sources:
                yield {"sources": result.sources}
            if progress := thought.append(
                _execution_activity(call, activity, result, (time.monotonic() - started) * 1000),
                separate=True,
            ):
                yield progress
            if result.output.get("awaiting_user"):
                yield from thought.finalize()
                return
            output = serialize_tool_output(result.output)
            if native_history:
                feedback.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.provider_id,
                        "content": output,
                        "is_error": result.output.get("ok") is not True,
                    }
                )
            else:
                item = {"role": "tool", "tool_call_id": call.provider_id, "content": output}
                messages.append(item)
                if replay_turn is not None:
                    replay_turn.append(item)
        if feedback:
            item = {"role": "user", "content": feedback}
            messages.append(item)
            if replay_turn is not None:
                replay_turn.append(item)
    raise ProviderRequestError("provider_unavailable")


def agent_stream(user_id, data):
    model_id = data.get("model") or "base"
    route = (
        key_route(user_id, model_id) if model_id.startswith("key/") else platform_route(model_id)
    )
    if not route or not route.key:
        raise ProviderRequestError("provider_not_configured")
    output_limit = compaction_output_limit(data, route.max_tokens)
    if output_limit != route.max_tokens:
        route = replace(route, spec={**route.spec, "maxTokens": output_limit})
    if route.text_only:
        data = {**data, "_model_text_only": True}
    if route.protocol == "google-generative-ai" and not route.public_endpoint:
        from backend.ai_engine.gemini import gemini_stream

        yield from gemini_stream(
            user_id,
            data,
            api_key=route.key,
            model=route.model,
            retry_policy=route.retry_policy if model_id.startswith("key/") else None,
            model_route=route if model_id.startswith("key/") or output_limit is not None else None,
        )
        return
    if route.protocol == "openai-responses":
        from backend.ai_engine.chatgpt import chatgpt_stream

        yield from chatgpt_stream(
            user_id,
            data,
            route=replace(route, base=route.base or PROVIDERS["openai"].base),
        )
        return
    try:
        yield from _agent_turn(user_id, data, route)
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ProviderRequestError("provider_unavailable") from error
