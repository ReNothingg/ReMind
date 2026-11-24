from __future__ import annotations

import json
import time
from types import SimpleNamespace

import requests

from backend.ai_engine.claude import _history_messages, _new_message_content, _ThoughtStream
from backend.ai_engine.compaction import compaction_output_limit
from backend.ai_engine.compatible_messages import checked_call, ensure_distinct_calls
from backend.ai_engine.errors import ProviderRequestError
from backend.ai_engine.gemini import _execution_activity, _model_activity_token
from backend.ai_engine.output_contract import ReplyPreview, output_contract_errors
from backend.ai_engine.provider_events import SSE_DONE, stream_events, tool_arguments
from backend.security.public_http import public_http_request
from backend.services import chatgpt_account
from backend.services.chat.cancellation import interruptible, stop_http_stream
from backend.services.chat.provider_replay import begin_replay
from backend.services.context_usage import (
    build_context_usage,
    context_weights,
    enforce_model_context,
)
from backend.services.provider_retry import retry_response
from backend.services.tools.model_runtime import ModelRuntime
from backend.services.tools.tool_execution import ToolExecution
from backend.services.tools.tool_protocol import serialize_tool_output


def _input(data, replay=None):
    restoring = bool(replay and replay.previous_frames)
    messages = [
        *_history_messages(data, include_ids=restoring),
        {"role": "user", "content": _new_message_content(data)},
    ]
    items = []
    for message in messages:
        parts = []
        for block in message["content"]:
            if block["type"] == "text":
                parts.append({"type": "input_text", "text": block["text"]})
            elif message["role"] == "user" and block["type"] in {"image", "document"}:
                source = block["source"]
                url = f"data:{source['media_type']};base64,{source['data']}"
                if block["type"] == "image":
                    parts.append({"type": "input_image", "image_url": url})
                else:
                    parts.append(
                        {"type": "input_file", "filename": "document.pdf", "file_data": url}
                    )
        if parts:
            items.append((message.get("id"), {"role": message["role"], "content": parts}))
    return replay.restore(items) if restoring else [item for _, item in items]


def _failure(code, status):
    if code == "subscription_sharing_usage_limit_exceeded" or status == 429:
        return ProviderRequestError("chatgpt_quota", 429)
    if status == 401 or code == "subscription_sharing_invalid_user":
        return ProviderRequestError("chatgpt_reconnect", 401)
    if status == 403 or code in (
        "chatpass_v2_scope_not_authorized",
        "chatpass_v2_invalid_authorization_context",
    ):
        return ProviderRequestError("provider_access_denied", 403)
    if code == "subscription_sharing_unsupported_capability":
        return ProviderRequestError("chatgpt_unsupported", 400)
    return ProviderRequestError("provider_unavailable")


def _response_events(token, body, control=None, resource=None, *, custom=False, retry_policy=None):
    if control is not None:
        control.check()
    endpoint = f"{resource or chatgpt_account.RESOURCE}/responses"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def open_response():
        timeout = control.timeout(80) if control is not None else 80
        return (
            public_http_request(
                "POST", endpoint, headers=headers, body=json.dumps(body).encode(), timeout=timeout
            )
            if custom
            else requests.post(
                endpoint,
                headers=headers,
                json=body,
                stream=True,
                timeout=(min(5, timeout), timeout),
                allow_redirects=False,
            )
        )

    with (
        retry_response(open_response, retry_policy, control) as response,
        interruptible(control, lambda: stop_http_stream(response)),
    ):
        if response.status_code != 200:
            try:
                code = "" if custom else response.json()["error"]["code"]
            except (KeyError, TypeError, ValueError):
                code = ""
            raise _failure(code, response.status_code)
        for event in stream_events(response, control):
            if event is SSE_DONE:
                break
            kind = event.get("type")
            if kind == "response.incomplete" and (
                (event.get("response") or {}).get("incomplete_details") or {}
            ).get("reason") == "max_output_tokens":
                raise ProviderRequestError("provider_output_limit", 422)
            if kind in ("error", "response.failed", "response.incomplete"):
                raise _failure(
                    ((event.get("response") or {}).get("error") or event).get("code"), None
                )
            yield event
            if kind == "response.completed":
                return
    raise ProviderRequestError("provider_unavailable")


def chatgpt_stream(user_id, data, *, route=None):
    runtime = ModelRuntime.create(user_id, data)
    execution = ToolExecution(runtime)
    model = route.model if route else data["model"].removeprefix(chatgpt_account.MODEL_PREFIX)
    entry = (
        {"serviceTiers": ["standard"]}
        if route
        else next(
            (item for item in chatgpt_account.list_models(user_id) if item["id"] == data["model"]),
            None,
        )
    )
    if not entry:
        raise ProviderRequestError("provider_model_unavailable", 403)
    speed = data.get("serviceTier") or "standard"
    if speed != "standard" and speed not in entry.get("serviceTiers", []):
        raise ProviderRequestError("model_speed_unavailable", 400)
    effort = (
        data.get("thinkingLevel") or data.get("thinking_level") or entry.get("defaultThinkingLevel")
    )
    wire_effort = (
        route.wire_effort(effort)
        if route
        else effort
        if effort in entry.get("thinkingLevels", ())
        else None
    )
    context_limit = route.context_window if route else None
    output_limit = compaction_output_limit(data, route.max_tokens if route else None)
    authority = route.key if route else None
    if (
        route is None
        and runtime.agent_settings.get("modelReplayEnabled")
        and data.get("_context_is_private_web") is True
    ):
        _, authority = chatgpt_account.replay_access(user_id)
    endpoint = route.base if route else chatgpt_account.RESOURCE
    replay_turn = begin_replay(
        user_id,
        data,
        runtime,
        protocol="openai-responses",
        provider=route.provider if route else "chatgpt",
        model=model,
        endpoint=endpoint,
        authority=authority,
    )
    inputs = _input(data, replay_turn)
    thoughts = _ThoughtStream(data.get("request_id"))
    try:
        for turn in range(runtime.step_limit + 1):
            activity_id = f"provider-{turn}"
            if progress := thoughts.append(
                _model_activity_token(activity_id, "model_waiting", round_number=turn + 1),
                separate=True,
            ):
                yield progress
            declarations = runtime.declarations()
            body = {
                "model": model,
                "input": inputs,
                "instructions": runtime.prompts.render(runtime.canvas),
                "store": False,
                "stream": True,
                "include": ["reasoning.encrypted_content"],
            }
            if speed != "standard":
                body["service_tier"] = speed
            if wire_effort:
                body["reasoning"] = {"effort": wire_effort}
            if output_limit is not None:
                body["max_output_tokens"] = output_limit
            if declarations and not execution.exhausted and turn < runtime.step_limit:
                body["tools"] = [
                    dict(type="function", strict=False, **item) for item in declarations
                ]
                if (
                    turn == 0
                    and data.get("webSearch")
                    and any(item["name"] == "web_search" for item in declarations)
                ):
                    body["tool_choice"] = {"type": "function", "name": "web_search"}
            weights = None
            if context_limit is not None:
                weights = context_weights(body["instructions"], body.get("tools", []), inputs)
                if (
                    turn == 0
                    and replay_turn
                    and replay_turn.previous_frames
                    and sum(weights) + (output_limit or 0) > context_limit
                ):
                    inputs = _input(data)
                    body["input"] = inputs
                    weights = context_weights(body["instructions"], body.get("tools", []), inputs)
                enforce_model_context(weights, context_limit, output_limit)
            output = []
            preview = ReplyPreview()
            waiting = True
            if route:
                token = route.key
            elif replay_turn is not None:
                token, current_authority = chatgpt_account.replay_access(user_id)
                if current_authority != authority:
                    raise ProviderRequestError("chatgpt_reconnect", 401)
            else:
                token = chatgpt_account.access_token(user_id)
            for event in _response_events(
                token,
                body,
                data.get("_generation_control"),
                route.base if route else None,
                custom=bool(route and route.public_endpoint),
                retry_policy=route.retry_policy if route else None,
            ):
                if waiting:
                    waiting = False
                    if progress := thoughts.append(
                        _model_activity_token(
                            activity_id, "model_responded", round_number=turn + 1
                        ),
                        separate=True,
                    ):
                        yield progress
                kind = event.get("type")
                if kind == "response.output_text.delta":
                    if part := preview.append(event.get("delta")):
                        yield part
                elif (
                    kind == "response.output_item.added"
                    and (event.get("item") or {}).get("type") == "function_call"
                ):
                    if part := preview.clear(block=True):
                        yield part
                elif kind == "response.completed":
                    output = event["response"]["output"]
                    input_tokens = (event["response"].get("usage") or {}).get("input_tokens")
                    if weights and (
                        usage := build_context_usage(
                            SimpleNamespace(prompt_token_count=input_tokens), weights, context_limit
                        )
                    ):
                        yield {"context_usage": usage}
            if part := preview.clear():
                yield part
            calls = []
            for item in output:
                if item.get("type") != "function_call":
                    continue
                if item.get("status") not in (None, "completed"):
                    raise ProviderRequestError("provider_unavailable")
                calls.append(
                    checked_call(
                        item.get("call_id"), item.get("name"), tool_arguments(item.get("arguments"))
                    )
                )
            ensure_distinct_calls(calls)
            if replay_turn is not None:
                for item in output:
                    if item.get("type") in ("message", "function_call") or (
                        item.get("type") == "reasoning" and item.get("encrypted_content")
                    ):
                        replay_turn.append(item)
            if not calls:
                text = "".join(
                    part.get("text") or part.get("refusal") or ""
                    for item in output
                    if item.get("type") == "message"
                    for part in item.get("content", [])
                )
                yield from thoughts.finalize()
                if not text.strip() or output_contract_errors(text):
                    raise ProviderRequestError("provider_unavailable")
                if replay_turn is not None and (draft := replay_turn.finish()):
                    yield draft
                yield text
                return
            if "tools" not in body:
                raise ProviderRequestError("provider_unavailable")
            inputs.extend(
                item
                for item in output
                if item.get("type") in {"message", "function_call", "reasoning"}
            )
            for index, call in enumerate(calls):
                activity = f"tool-{turn}-{index}"
                started = time.monotonic()
                if progress := thoughts.append(_execution_activity(call, activity), separate=True):
                    yield progress
                result = execution.execute(call, index)
                yield from result.events
                if result.sources:
                    yield {"sources": result.sources}
                if progress := thoughts.append(
                    _execution_activity(
                        call, activity, result, (time.monotonic() - started) * 1000
                    ),
                    separate=True,
                ):
                    yield progress
                item = {
                    "type": "function_call_output",
                    "call_id": call.provider_id,
                    "output": serialize_tool_output(result.output),
                }
                inputs.append(item)
                if replay_turn is not None:
                    replay_turn.append(item)
                if result.output.get("awaiting_user"):
                    yield from thoughts.finalize()
                    return
        raise ProviderRequestError("provider_unavailable")
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        raise ProviderRequestError("provider_unavailable") from error
