from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.ai_engine.provider_events import (
    MAX_TOOL_CALLS,
    SSE_DONE,
    ProviderStreamError,
    empty_response,
    incomplete_stream,
    provider_error,
    response_objects,
    tool_arguments,
    usage_count,
)
from backend.services.tools.tool_execution import ToolCall

TOOL_NAME = re.compile(r"[a-zA-Z0-9_-]{1,64}")
TOOL_ID = re.compile(r"[a-zA-Z0-9_.:-]{1,200}")
DETAIL_FIELDS = {"text", "summary", "signature", "data"}


@dataclass
class RoundReply:
    text: str
    replay: dict
    calls: list[ToolCall]
    input_tokens: int | None = None


def checked_call(tool_id, name, arguments):
    if (
        not isinstance(tool_id, str)
        or not TOOL_ID.fullmatch(tool_id)
        or not isinstance(name, str)
        or not TOOL_NAME.fullmatch(name)
        or not isinstance(arguments, dict)
    ):
        raise ProviderStreamError()
    return ToolCall(name, arguments, tool_id)


def ensure_distinct_calls(calls):
    if len(calls) > MAX_TOOL_CALLS or len({call.provider_id for call in calls}) != len(calls):
        raise ProviderStreamError()


def _assign_identity(previous, value):
    if value is None or value == "":
        return previous
    if not isinstance(value, str) or (previous and value != previous):
        raise ProviderStreamError()
    return value


@dataclass
class CompletionTool:
    id: str = ""
    name: str = ""
    arguments: list[str] = field(default_factory=list)

    def append(self, delta):
        if delta.get("type") not in (None, "function"):
            raise ProviderStreamError()
        self.id = _assign_identity(self.id, delta.get("id"))
        function = delta.get("function")
        if function is None:
            return
        if not isinstance(function, dict):
            raise ProviderStreamError()
        self.name = _assign_identity(self.name, function.get("name"))
        if (fragment := function.get("arguments")) is not None:
            if not isinstance(fragment, str):
                raise ProviderStreamError()
            self.arguments.append(fragment)

    def finish(self):
        raw = "".join(self.arguments)
        return checked_call(self.id, self.name, tool_arguments(raw)), {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": raw},
        }


@dataclass
class ReasoningDetail:
    metadata: dict = field(default_factory=dict)
    segments: dict[str, list[str]] = field(default_factory=dict)

    def append(self, detail):
        for key, value in detail.items():
            if key in DETAIL_FIELDS and value is not None:
                if not isinstance(value, str):
                    raise ProviderStreamError()
                self.segments.setdefault(key, []).append(value)
            elif key not in self.metadata or self.metadata[key] is None:
                self.metadata[key] = value
            elif value is not None and value != self.metadata[key]:
                raise ProviderStreamError()

    def finish(self):
        return {**self.metadata, **{key: "".join(values) for key, values in self.segments.items()}}


def _selected_choice(event, key):
    choices = event.get(key)
    if choices is None:
        return None
    if not isinstance(choices, list) or any(not isinstance(choice, dict) for choice in choices):
        raise ProviderStreamError()
    result = [choice for choice in choices if choice.get("index", 0) == 0]
    if len(result) > 1:
        raise ProviderStreamError()
    return result[0] if result else None


@dataclass
class CompletionRound:
    answer: list[str] = field(default_factory=list)
    reasoning: dict[str, list[str]] = field(default_factory=dict)
    details: dict[tuple, ReasoningDetail] = field(default_factory=dict)
    calls: dict[int, CompletionTool] = field(default_factory=dict)
    refused: bool = False
    input_tokens: int | None = None
    stop: str | None = None

    def _reasoning_details(self, raw):
        if not isinstance(raw, list):
            raise ProviderStreamError()
        for info in raw:
            if not isinstance(info, dict):
                raise ProviderStreamError()
            index, key = info.get("index"), info.get("id")
            if type(index) is int and 0 <= index <= 4096:
                key = ("index", index)
            elif isinstance(key, str) and key:
                key = ("id", key)
            else:
                key = ("position", len(self.details))
            self.details.setdefault(key, ReasoningDetail()).append(info)
            if len(self.details) > 256:
                raise ProviderStreamError()

    def accept(self, event, *, complete):
        if event.get("error") is not None:
            raise provider_error(event["error"])
        usage = event.get("usage")
        if (
            isinstance(usage, dict)
            and (tokens := usage_count(usage.get("prompt_tokens"))) is not None
        ):
            self.input_tokens = tokens
        choice = _selected_choice(event, "choices")
        if choice is None:
            return False, None
        delta = choice.get("message" if complete else "delta") or {}
        stop = choice.get("finish_reason")
        if not isinstance(delta, dict) or (stop is not None and not isinstance(stop, str)):
            raise ProviderStreamError()
        if self.stop and (any(delta.values()) or (stop and stop != self.stop)):
            raise ProviderStreamError()
        if delta.get("role") not in (None, "assistant"):
            raise ProviderStreamError()
        content = delta.get("content")
        if content is not None:
            if not isinstance(content, str):
                raise ProviderStreamError()
            if content:
                self.answer.append(content)
        if delta.get("refusal"):
            self.refused = True
        for field_name in ("reasoning", "reasoning_content"):
            value = delta.get(field_name)
            if isinstance(value, str) and value:
                self.reasoning.setdefault(field_name, []).append(value)
        if (details := delta.get("reasoning_details")) is not None:
            self._reasoning_details(details)
        tool_blocks = delta.get("tool_calls")
        first_call = bool(tool_blocks) and not self.calls
        if tool_blocks is not None:
            if not isinstance(tool_blocks, list):
                raise ProviderStreamError()
            for offset, call in enumerate(tool_blocks):
                if not isinstance(call, dict):
                    raise ProviderStreamError()
                index = offset if complete else call.get("index")
                if type(index) is not int or not 0 <= index < MAX_TOOL_CALLS:
                    raise ProviderStreamError()
                self.calls.setdefault(index, CompletionTool()).append(call)
        if stop:
            self.stop = stop
        return first_call, content

    def finish(self):
        if self.stop == "length":
            raise ProviderStreamError("provider_output_limit", 422)
        if self.refused or self.stop == "content_filter":
            raise ProviderStreamError("provider_refused", 422)
        if self.stop is None:
            if not self.answer and not self.calls and not self.reasoning and not self.details:
                raise empty_response()
            raise incomplete_stream()
        if self.stop not in {"stop", "tool_calls"} or (self.stop == "tool_calls") != bool(
            self.calls
        ):
            raise ProviderStreamError()
        text = "".join(self.answer)
        if not text.strip() and not self.calls:
            raise empty_response()
        replay = {"role": "assistant", "content": text or None}
        calls = []
        if self.calls:
            wire = []
            for index in sorted(self.calls):
                call, block = self.calls[index].finish()
                calls.append(call)
                wire.append(block)
            ensure_distinct_calls(calls)
            replay["tool_calls"] = wire
            replay.update({key: "".join(value) for key, value in self.reasoning.items()})
            if self.details:
                replay["reasoning_details"] = [item.finish() for item in self.details.values()]
        return RoundReply(text, replay, calls, self.input_tokens)


def completions_events(response, control=None):
    complete, events = response_objects(response, control)
    state = CompletionRound()
    started_reasoning = False
    for event in events:
        if event is SSE_DONE:
            break
        first_call, text = state.accept(event, complete=complete)
        if not started_reasoning and (state.reasoning or state.details):
            started_reasoning = True
            yield "reasoning", None
        if first_call:
            yield "tools", None
        if text:
            yield "text", text
    yield "finish", state.finish()


@dataclass
class GoogleRound:
    message_count: int
    parts: list[dict] = field(default_factory=list)
    calls: list[ToolCall] = field(default_factory=list)
    answer: list[str] = field(default_factory=list)
    input_tokens: int | None = None
    stop: str | None = None

    def accept(self, event):
        if event.get("error") is not None:
            raise provider_error(event["error"])
        feedback = event.get("promptFeedback")
        if isinstance(feedback, dict) and feedback.get("blockReason") not in (
            None,
            "",
            "BLOCK_REASON_UNSPECIFIED",
        ):
            raise ProviderStreamError("provider_refused", 422)
        usage = event.get("usageMetadata")
        if (
            isinstance(usage, dict)
            and (tokens := usage_count(usage.get("promptTokenCount"))) is not None
        ):
            self.input_tokens = tokens
        candidate = _selected_choice(event, "candidates")
        if candidate is None:
            return
        content = candidate.get("content") or {}
        if not isinstance(content, dict):
            raise ProviderStreamError()
        blocks = content.get("parts") or []
        if not isinstance(blocks, list) or (self.stop and blocks):
            raise ProviderStreamError()
        stop = candidate.get("finishReason")
        if stop not in (None, "FINISH_REASON_UNSPECIFIED"):
            if not isinstance(stop, str) or (self.stop and self.stop != stop):
                raise ProviderStreamError()
            self.stop = stop
        for block in blocks:
            if not isinstance(block, dict):
                raise ProviderStreamError()
            call = block.get("functionCall")
            call_id = f"google-{self.message_count}-{len(self.parts)}"
            if call is not None:
                if not isinstance(call, dict):
                    raise ProviderStreamError()
                if "partialArgs" in call or call.get("willContinue") is True:
                    raise ProviderStreamError()
                call_id = call.get("id") or call_id
                self.calls.append(checked_call(call_id, call.get("name"), call.get("args", {})))
                if len(self.calls) == 1:
                    yield "tools", None
                if len(self.calls) > MAX_TOOL_CALLS:
                    raise ProviderStreamError()
            self.parts.append({"type": "google", "part": block, "id": call_id})
            text = block.get("text")
            if text is not None and not isinstance(text, str):
                raise ProviderStreamError()
            if text and not block.get("thought"):
                self.answer.append(text)
                yield "text", text
            elif text:
                yield "reasoning", None

    def finish(self, complete):
        if self.stop == "MAX_TOKENS":
            raise ProviderStreamError("provider_output_limit", 422)
        if self.stop in {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}:
            raise ProviderStreamError("provider_refused", 422)
        if self.stop not in (None, "STOP"):
            raise ProviderStreamError()
        if self.stop is None and not complete:
            if not self.parts:
                raise empty_response()
            raise incomplete_stream()
        text = "".join(self.answer)
        if not text.strip() and not self.calls:
            raise empty_response()
        ensure_distinct_calls(self.calls)
        return RoundReply(
            text, {"role": "assistant", "content": self.parts}, self.calls, self.input_tokens
        )


def google_events(response, control=None, *, message_count):
    complete, events = response_objects(response, control)
    state = GoogleRound(message_count)
    for event in events:
        if event is SSE_DONE:
            break
        yield from state.accept(event)
    yield "finish", state.finish(complete)
