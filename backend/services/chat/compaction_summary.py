import json
import re
from contextlib import closing, contextmanager, nullcontext
from threading import Lock
from uuid import uuid4

from flask import current_app
from redis import RedisError

from backend.ai_engine import get_model_function
from backend.ai_engine.compaction import CompactionTurn, supports_summary_model
from backend.ai_engine.deepseek_messages import CONTEXT_LIMITS
from backend.ai_engine.errors import ProviderRequestError
from backend.ai_engine.prompt_templates import require_prompt
from backend.errors import ApiError
from backend.services.agent_models import key_route, platform_route
from backend.services.chat.cancellation import (
    GenerationControl,
    GenerationStopped,
    chat_redis_client,
)
from backend.services.context_usage import GEMINI_CONTEXT_LIMIT
from backend.services.model_access import can_user_access_model

SUMMARY_DEADLINE = 32
REPLAY_BYTES_LIMIT = 140_000
REPLAY_MESSAGES_LIMIT = 36
SUMMARY_BYTES_LIMIT = 32_000
SECTION_HEADINGS = {
    "Primary Request and Intent": "intent",
    "Key Technical Concepts": "concepts",
    "Files and Code": "files",
    "Errors and Fixes": "errors",
    "Pending Jobs": "pending",
    "Current Work": "current",
    "Next Step": "next",
    "Critical Context": "critical",
}
HEADING = re.compile(r"^##[ \t]+([^#\n]+?)[ \t]*$", re.M)
EMPTY_SECTIONS = {"(none)", "- (none)", "* (none)"}
ACTIVE_SUMMARIES = set()
ACTIVE_LOCK = Lock()


def model_capacity(owner, model):
    route = key_route(owner, model)
    if route is None and model in {"base", "harness"}:
        route = platform_route(model)
    if route is None:
        return (1_000_000, 64_000) if model == "claude_sonnet_5_5" else (None, None)
    capacity = route.context_window or CONTEXT_LIMITS.get(route.model)
    if capacity is None and model == "base" and route.provider == "google":
        capacity = GEMINI_CONTEXT_LIMIT
    return capacity, route.max_tokens


def summary_pressure(options, capacity, reserved, ceiling):
    window = capacity or ceiling // 4
    available = max(1, window - (reserved or 0))
    pressure = available - options["contextHeadroomTokens"]
    threshold = max(1, min(window * options["contextThresholdPercent"] // 100, pressure))
    limit = min(ceiling, max(256, threshold * 4))
    tail = options["contextRetainTokens"] or available * options["contextRetainPercent"] // 100
    return limit, max(1, min(limit * 3 // 5, tail * 4))


def _message(role, text):
    return {"role": role, "parts": [{"text": text}]}


def _replay(records, prior, excerpts, budget):
    history = []
    omitted = False
    remaining = budget - min(16_000, budget // 4)
    for record in reversed(records):
        text = record["text"]
        if not text:
            continue
        raw = text.encode("utf-8", errors="replace")
        if len(history) >= REPLAY_MESSAGES_LIMIT or remaining < 128:
            omitted = True
            break
        limit = min(32_000, remaining)
        if len(raw) > limit:
            snippet = raw[: limit // 2].decode("utf-8", errors="ignore")
            ending = raw[-limit // 2 :].decode("utf-8", errors="ignore")
            text = snippet + "\n[…]\n" + ending
            omitted = True
        remaining -= min(len(raw), limit) + 32
        history.append(_message(record["role"], text))
    frame = {}
    if prior:
        frame["prior_checkpoint"] = prior
    if omitted:
        frame["older_excerpts"] = excerpts
        frame["partial_history"] = True
    if frame:
        payload = json.dumps(frame, ensure_ascii=False).replace("<", r"\u003c")
        maximum = min(16_000, budget // 4)
        if len(payload.encode()) > maximum:
            frame.pop("older_excerpts", None)
            payload = json.dumps(frame, ensure_ascii=False).replace("<", r"\u003c")
        if len(payload.encode()) > maximum:
            omitted = True
            payload = '{"partial_history":true}'
        history.append(
            _message("user", "<compacted-summary>\n" + payload + "\n</compacted-summary>")
        )
    if not history:
        raise ApiError("context_summary_failed", status=502, code="context_summary_failed")
    history.reverse()
    if history[0]["role"] == "model":
        history.insert(0, _message("user", '{"earlier_conversation":true}'))
    return history, omitted


def _summary_sections(answer):
    answer = answer.strip()
    if answer.startswith(("```markdown\n", "```md\n", "```\n")) and answer.endswith("\n```"):
        answer = answer.split("\n", 1)[1].removesuffix("\n```").strip()
    headings = list(HEADING.finditer(answer))
    if [heading.group(1) for heading in headings] != list(SECTION_HEADINGS):
        raise ProviderRequestError("context_summary_invalid")
    if answer[: headings[0].start()].strip():
        raise ProviderRequestError("context_summary_invalid")
    sections = {}
    for index, heading in enumerate(headings):
        stop = headings[index + 1].start() if index + 1 < len(headings) else len(answer)
        text = answer[heading.end() : stop].strip()
        sections[SECTION_HEADINGS[heading.group(1)]] = "" if text in EMPTY_SECTIONS else text
    if not any(sections.values()):
        raise ProviderRequestError("context_summary_invalid")
    return sections


def _collect_events(events, control, byte_limit):
    final = []
    size = 0
    preview_size = 0
    for event in events:
        control.check()
        if isinstance(event, dict):
            if isinstance(preview := event.get("reply_preview"), str):
                preview_size += len(preview.encode())
                if preview_size > byte_limit:
                    raise ProviderRequestError("provider_output_limit", 422)
            text = event.get("reply_part")
        else:
            text = event
        if isinstance(text, str) and text:
            size += len(text.encode())
            if size > byte_limit:
                raise ProviderRequestError("provider_output_limit", 422)
            final.append(text)
    control.check()
    return _summary_sections("".join(final))


def summarize_context(owner, model, records, prior, excerpts, options, *, parent=None):
    if not supports_summary_model(model) or not can_user_access_model(model, owner):
        raise ApiError(
            "context_summary_model_unavailable",
            status=422,
            code="context_summary_model_unavailable",
        )
    handler = get_model_function(model)
    if not handler:
        raise ApiError(
            "context_summary_model_unavailable",
            status=422,
            code="context_summary_model_unavailable",
        )
    tokens = options["contextSummaryTokens"]
    capacity, max_output = model_capacity(owner, model)
    if max_output is not None:
        tokens = min(tokens, max_output)
    budget = (
        min(REPLAY_BYTES_LIMIT, max(0, (capacity - tokens - 640) * 3))
        if capacity
        else REPLAY_BYTES_LIMIT
    )
    if budget < 512:
        raise ApiError("context_summary_failed", status=502, code="context_summary_failed")
    history, omitted = _replay(records, prior, excerpts, budget)
    control = GenerationControl(
        time_limit=parent.timeout(SUMMARY_DEADLINE) if parent is not None else SUMMARY_DEADLINE
    )
    scope = parent.track(control.stop) if parent is not None else nullcontext()
    with scope:
        try:
            for attempt in range(options["contextSummaryRetries"] + 1):
                control.check()
                data = {
                    "model": model,
                    "history": history,
                    "message": require_prompt("context/summarize_checkpoint.md"),
                    "request_id": uuid4().hex,
                    "_compaction_turn": CompactionTurn(tokens),
                    "_generation_control": control,
                    "_model_text_only": True,
                    "thinkingLevel": "low",
                }
                try:
                    with closing(handler(owner, data)) as events:
                        sections = _collect_events(
                            events, control, min(SUMMARY_BYTES_LIMIT, tokens * 6)
                        )
                    return {"model": model, "sections": sections, "partial_history": omitted}
                except ProviderRequestError as error:
                    if attempt == options["contextSummaryRetries"] or error.status not in {
                        408,
                        500,
                        502,
                        503,
                        504,
                    }:
                        break
                except GenerationStopped:
                    raise
                except (RuntimeError, OSError, ValueError, KeyError, TypeError):
                    break
        except GenerationStopped:
            if parent is not None:
                parent.check()
    raise ApiError("context_summary_failed", status=502, code="context_summary_failed")


@contextmanager
def summary_lease(chat_id):
    redis_url = current_app.config.get("REDIS_URL")
    if redis_url:
        lease = chat_redis_client(redis_url).lock(
            f"remind:chat:summary:{chat_id}", timeout=SUMMARY_DEADLINE + 18, blocking=False
        )
        try:
            acquired = lease.acquire()
        except RedisError:
            acquired = False
        try:
            yield acquired
        finally:
            if acquired:
                try:
                    lease.release()
                except RedisError:
                    pass
        return
    with ACTIVE_LOCK:
        acquired = chat_id not in ACTIVE_SUMMARIES
        if acquired:
            ACTIVE_SUMMARIES.add(chat_id)
    try:
        yield acquired
    finally:
        if acquired:
            with ACTIVE_LOCK:
                ACTIVE_SUMMARIES.discard(chat_id)
