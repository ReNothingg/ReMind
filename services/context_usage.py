from __future__ import annotations

from typing import Any

GEMINI_CONTEXT_LIMIT = 1_048_576
TOKEN_FIELDS = ("input_tokens", "system_tokens", "tool_tokens", "message_tokens", "context_limit")


def _weight(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bytes):
        return 768
    if isinstance(value, str):
        return max(1, (len(value.encode("utf-8")) + 3) // 4)
    if isinstance(value, (list, tuple)):
        return sum(_weight(item) for item in value)
    if isinstance(value, dict):
        return sum(
            _weight(key) + _weight(item)
            for key, item in value.items()
            if key != "thought_signature"
        )
    if hasattr(value, "model_dump"):
        return _weight(value.model_dump(exclude_none=True))
    return 1


def context_weights(
    system_prompt: str, declarations: list[dict], messages: Any
) -> tuple[int, int, int]:
    return _weight(system_prompt), _weight(declarations), max(1, _weight(messages))


def build_context_usage(usage: Any, weights: tuple[int, int, int]) -> dict | None:
    total = getattr(usage, "prompt_token_count", None)
    if type(total) is not int or not 0 <= total <= 16_000_000:
        return None
    denominator = max(1, sum(weights))
    system_tokens = int(total * weights[0] / denominator)
    tool_tokens = int(total * weights[1] / denominator)
    return {
        "input_tokens": total,
        "context_limit": GEMINI_CONTEXT_LIMIT,
        "system_tokens": system_tokens,
        "tool_tokens": tool_tokens,
        "message_tokens": total - system_tokens - tool_tokens,
        "estimated_breakdown": True,
    }


def normalize_context_usage(value: Any) -> dict | None:
    if not isinstance(value, dict) or any(
        type(value.get(key)) is not int or not 0 <= value[key] <= 16_000_000 for key in TOKEN_FIELDS
    ):
        return None
    if (
        value["context_limit"] <= 0
        or sum(value[key] for key in ("system_tokens", "tool_tokens", "message_tokens"))
        != value["input_tokens"]
    ):
        return None
    return {**{key: value[key] for key in TOKEN_FIELDS}, "estimated_breakdown": True}
