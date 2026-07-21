from __future__ import annotations

import json
from typing import Any

import requests

from services.ai_provider import generate_text_with_trace

_FALLBACK_TRANSLATION_ENDPOINT = "https://translate.googleapis.com/translate_a/single"
_FALLBACK_TIMEOUT = (5, 20)
_FALLBACK_RESPONSE_MAX_BYTES = 256 * 1024


class TranslationUnavailableError(RuntimeError):
    pass


def _read_limited_response(response: requests.Response) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise TranslationUnavailableError("Translation response has an invalid length") from exc
        if declared_length < 0 or declared_length > _FALLBACK_RESPONSE_MAX_BYTES:
            raise TranslationUnavailableError("Translation response exceeds the safety limit")

    body = bytearray()
    for chunk in response.iter_content(chunk_size=32 * 1024):
        if not chunk:
            continue
        body.extend(chunk)
        if len(body) > _FALLBACK_RESPONSE_MAX_BYTES:
            raise TranslationUnavailableError("Translation response exceeds the safety limit")
    return bytes(body)


def _parse_fallback_translation(payload: Any) -> str:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        raise TranslationUnavailableError("Translation response has an invalid format")

    translated_parts: list[str] = []
    for segment in payload[0]:
        if isinstance(segment, list) and segment and isinstance(segment[0], str):
            translated_parts.append(segment[0])

    translated_text = "".join(translated_parts).strip()
    if not translated_text:
        raise TranslationUnavailableError("Translation response is empty")
    return translated_text


def _translate_with_fallback(text: str, target_lang: str) -> str:
    response = requests.post(
        _FALLBACK_TRANSLATION_ENDPOINT,
        params={"client": "gtx", "sl": "auto", "tl": target_lang, "dt": "t"},
        data={"q": text},
        timeout=_FALLBACK_TIMEOUT,
        allow_redirects=False,
        stream=True,
        verify=True,
    )
    try:
        response.raise_for_status()
        body = _read_limited_response(response)
        try:
            payload = json.loads(body)
        except (TypeError, ValueError) as exc:
            raise TranslationUnavailableError("Translation response is not valid JSON") from exc
        return _parse_fallback_translation(payload)
    finally:
        response.close()


def translate_text(text: str, target_lang: str) -> tuple[str, bool]:
    prompt = (
        "Translate the following text to the target language.\n"
        f"Target language: {target_lang}\n"
        "Rules: Return ONLY the translated text. Do not add quotes, explanations, markdown, "
        "or extra lines.\n\n"
        f"{text}"
    )
    translated_text, _trace = generate_text_with_trace(prompt, temperature=0)
    if translated_text and translated_text.strip():
        return translated_text.strip(), False

    try:
        return _translate_with_fallback(text, target_lang), True
    except (requests.RequestException, TranslationUnavailableError) as exc:
        raise TranslationUnavailableError("Translation providers are unavailable") from exc
