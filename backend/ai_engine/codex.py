from __future__ import annotations

import json
import secrets
import time

from backend.ai_engine.claude import _history_messages, _new_message_content, _ThoughtStream
from backend.ai_engine.compaction import compaction_turn
from backend.ai_engine.errors import ProviderRequestError
from backend.ai_engine.gemini import _execution_activity
from backend.ai_engine.output_contract import ReplyPreview, output_contract_errors
from backend.errors import ApiError
from backend.services import workspaces
from backend.services.chat.cancellation import interruptible, stop_http_stream
from backend.services.codex_account import PREFIX
from backend.services.tools.model_runtime import ModelRuntime
from backend.services.tools.tool_execution import ToolCall, ToolExecution
from backend.services.tools.tool_protocol import serialize_tool_output


def _rpc(slot, method, payload, **options):
    try:
        return workspaces.rpc(slot, method, payload, **options)
    except ApiError as error:
        raise ProviderRequestError(error.code, error.status) from error


def codex_stream(user_id, data):
    slot = workspaces.existing(user_id)
    if not slot:
        raise ProviderRequestError("chatgpt_reconnect", 401)
    runtime = ModelRuntime.create(user_id, data)
    execution = ToolExecution(runtime)
    thoughts = _ThoughtStream(data.get("request_id"))
    request = secrets.token_hex(16)
    blocks = []
    for part in _new_message_content(data):
        if part["type"] == "text":
            blocks.append({"type": "text", "text": part["text"]})
        elif part["type"] == "image":
            source = part["source"]
            blocks.append(
                {"type": "image", "url": f"data:{source['media_type']};base64,{source['data']}"}
            )
    history = [
        {
            "role": item["role"],
            "text": "\n".join(
                block["text"] for block in item["content"] if block["type"] == "text"
            ),
        }
        for item in _history_messages(data)
    ]
    body = {
        "request": request,
        "model": data["model"].removeprefix(PREFIX),
        "speed": data.get("serviceTier") or "standard",
        "effort": data.get("thinkingLevel"),
        "instructions": runtime.prompts.render(runtime.canvas),
        "tools": runtime.declarations(),
        "history": history,
        "input": blocks,
    }
    control = data.get("_generation_control")
    preview = ReplyPreview()
    timeout = control.timeout(195) if control is not None else 195
    with (
        _rpc(slot, "codex/turn", body, owner=user_id, stream=True, timeout=timeout) as stream,
        interruptible(control, lambda: stop_http_stream(stream)),
    ):
        for line in stream.iter_lines(chunk_size=512):
            if control is not None:
                control.check()
            if not line:
                continue
            event = json.loads(line)
            if event.get("type") == "preview":
                if update := preview.append(event.get("text")):
                    yield update
                continue
            if event.get("type") == "completed":
                if update := preview.clear():
                    yield update
                yield from thoughts.finalize()
                answer = event.get("text") or ""
                if not answer.strip() or output_contract_errors(answer):
                    raise ProviderRequestError("provider_unavailable")
                yield answer
                return
            if event.get("type") != "tool":
                raise ProviderRequestError(
                    "chatgpt_quota"
                    if event.get("code") == "chatgpt_quota"
                    else "provider_unavailable"
                )
            if compaction_turn(data):
                raise ProviderRequestError("provider_unavailable")
            if update := preview.clear():
                yield update
            name = event.get("name", "").removeprefix("remind_")
            call = ToolCall(name, event.get("arguments"))
            task_id = "codex-" + event["id"]
            start = time.monotonic()
            if progress := thoughts.append(_execution_activity(call, task_id), separate=True):
                yield progress
            result = execution.execute(call, 0)
            yield from result.events
            if result.sources:
                yield {"sources": result.sources}
            if progress := thoughts.append(
                _execution_activity(call, task_id, result, (time.monotonic() - start) * 1000),
                separate=True,
            ):
                yield progress
            if result.output.get("awaiting_user"):
                yield from thoughts.finalize()
                return
            output = dict(result.output)
            if name == "read_skill" and output.get("ok"):
                output["instructions"] = runtime.prompts.instructions[output["skill_id"]]
            _rpc(
                slot,
                "codex/tool",
                {
                    "id": event["id"],
                    "request": request,
                    "ok": output.get("ok") is True,
                    "output": serialize_tool_output(output),
                },
                owner=user_id,
            )
    raise ProviderRequestError("provider_unavailable")
