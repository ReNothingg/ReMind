from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from config import AI_PROVIDER_API_KEY, AI_PROVIDER_MODEL_NAME

DEFAULT_PROVIDER_MODEL = AI_PROVIDER_MODEL_NAME or "gemini-1.5-flash"


def _activity(
    code: str,
    status: str = "done",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "status": status,
        "meta": meta or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _text_preview(value: str, limit: int = 900) -> str:
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit].rstrip()}..."


def _json_from_text(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def is_ai_provider_configured() -> bool:
    return bool(AI_PROVIDER_API_KEY)


def _generate_content(
    prompt: str,
    *,
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
    response_mime_type: str | None = None,
) -> str:
    import google.generativeai as genai

    genai.configure(api_key=AI_PROVIDER_API_KEY)
    generation_config: dict[str, Any] = {"temperature": temperature}
    if max_output_tokens is not None:
        generation_config["max_output_tokens"] = max_output_tokens
    if response_mime_type:
        generation_config["response_mime_type"] = response_mime_type

    model = genai.GenerativeModel(DEFAULT_PROVIDER_MODEL)
    response = model.generate_content(prompt, generation_config=generation_config)
    return (getattr(response, "text", None) or "").strip()


def generate_json_with_trace(
    prompt: str,
    *,
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not is_ai_provider_configured():
        return None, _activity("aiProviderMissingKey", "warning")

    try:
        text = _generate_content(
            prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json",
        )
    except Exception as exc:
        return None, _activity(
            "aiProviderRequestFailed",
            "error",
            {"message": str(exc)[:500]},
        )

    parsed = _json_from_text(text)
    if parsed is None:
        return None, _activity(
            "aiProviderInvalidJson",
            "error",
            {
                "response_preview": _text_preview(text),
                "response_chars": len(text),
            },
        )
    return parsed, _activity("aiProviderJsonParsed", "done", {"response_chars": len(text)})


def generate_json(
    prompt: str,
    *,
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
) -> dict[str, Any] | None:
    parsed, _trace = generate_json_with_trace(
        prompt,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )
    return parsed


def generate_text_with_trace(
    prompt: str,
    *,
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
) -> tuple[str | None, dict[str, Any]]:
    if not is_ai_provider_configured():
        return None, _activity("aiProviderMissingKey", "warning")

    try:
        text = _generate_content(
            prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
    except Exception as exc:
        return None, _activity(
            "aiProviderTextRequestFailed",
            "error",
            {"message": str(exc)[:500]},
        )
    if not text.strip():
        return None, _activity("aiProviderTextEmpty", "error")
    return text, _activity("aiProviderTextGenerated", "done", {"response_chars": len(text)})


def generate_text(
    prompt: str,
    *,
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
) -> str | None:
    text, _trace = generate_text_with_trace(
        prompt,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )
    return text
