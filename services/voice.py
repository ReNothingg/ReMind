import base64
import binascii
import json
import logging
import re

import requests
from langdetect import LangDetectException, detect

from config import DEFAULT_LANGUAGE

TTS_MAX_CHARS = 1000
_TTS_PART_MAX_CHARS = 100
_TTS_RESPONSE_MAX_BYTES = 5 * 1024 * 1024
_TTS_AUDIO_MAX_BYTES = 8 * 1024 * 1024
_TTS_ENDPOINT = "https://translate.google.com/_/TranslateWebserverUi/data/batchexecute"
_TTS_RPC_ID = "jQ1olc"
_TTS_TIMEOUT = (5, 20)
_AUDIO_PAYLOAD_PATTERN = re.compile(rf'{_TTS_RPC_ID}","\[\\"([A-Za-z0-9+/=]+)\\"\]')
_SUPPORTED_LANGUAGES = frozenset(
    {
        "af",
        "am",
        "ar",
        "bg",
        "bn",
        "bs",
        "ca",
        "cs",
        "cy",
        "da",
        "de",
        "el",
        "en",
        "es",
        "et",
        "eu",
        "fi",
        "fr",
        "fr-CA",
        "gl",
        "gu",
        "ha",
        "hi",
        "hr",
        "hu",
        "id",
        "is",
        "it",
        "iw",
        "ja",
        "jw",
        "km",
        "kn",
        "ko",
        "la",
        "lt",
        "lv",
        "ml",
        "mr",
        "ms",
        "my",
        "ne",
        "nl",
        "no",
        "pa",
        "pl",
        "pt",
        "pt-PT",
        "ro",
        "ru",
        "si",
        "sk",
        "sq",
        "sr",
        "su",
        "sv",
        "sw",
        "ta",
        "te",
        "th",
        "tl",
        "tr",
        "uk",
        "ur",
        "vi",
        "yue",
        "zh",
        "zh-CN",
        "zh-TW",
    }
)
_LANGUAGE_ALIASES = {
    "he": "iw",
    "jv": "jw",
    "zh-cn": "zh-CN",
    "zh-tw": "zh-TW",
}
_TTS_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
    "Referer": "https://translate.google.com/",
    "User-Agent": "Mozilla/5.0 (compatible; ReMind/1.0)",
}
logger = logging.getLogger("remind.voice")


def _language_for_text(text: str) -> str:
    fallback = _LANGUAGE_ALIASES.get(DEFAULT_LANGUAGE, DEFAULT_LANGUAGE)
    if fallback not in _SUPPORTED_LANGUAGES:
        fallback = "en"
    if len(text) <= 10:
        return fallback
    try:
        detected = detect(text)
    except LangDetectException:
        return fallback
    candidate = _LANGUAGE_ALIASES.get(detected, detected)
    return candidate if candidate in _SUPPORTED_LANGUAGES else fallback


def _split_text(text: str) -> list[str]:
    remaining = " ".join(text.split())
    parts: list[str] = []
    while remaining:
        if len(remaining) <= _TTS_PART_MAX_CHARS:
            parts.append(remaining)
            break

        window = remaining[: _TTS_PART_MAX_CHARS + 1]
        punctuation_break = max(window.rfind(mark) + 1 for mark in ".!?;:,。！？；，")
        whitespace_break = window.rfind(" ")
        split_at = punctuation_break if punctuation_break >= 40 else whitespace_break
        if split_at <= 0 or split_at > _TTS_PART_MAX_CHARS:
            split_at = _TTS_PART_MAX_CHARS

        part = remaining[:split_at].strip()
        if part:
            parts.append(part)
        remaining = remaining[split_at:].strip()
    return parts


def _request_audio_part(text: str, language: str) -> bytes:
    parameter = json.dumps([text, language, None, "null"], separators=(",", ":"))
    rpc = json.dumps([[[_TTS_RPC_ID, parameter, None, "generic"]]], separators=(",", ":"))
    response = requests.post(
        _TTS_ENDPOINT,
        data={"f.req": rpc},
        headers=_TTS_HEADERS,
        timeout=_TTS_TIMEOUT,
        allow_redirects=False,
        stream=True,
        verify=True,
    )
    try:
        response.raise_for_status()
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError as exc:
                raise ValueError("TTS response has an invalid length") from exc
            if declared_length < 0 or declared_length > _TTS_RESPONSE_MAX_BYTES:
                raise ValueError("TTS response exceeds the safety limit")

        body = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            body.extend(chunk)
            if len(body) > _TTS_RESPONSE_MAX_BYTES:
                raise ValueError("TTS response exceeds the safety limit")
    finally:
        response.close()

    response_text = bytes(body).decode("utf-8")
    match = _AUDIO_PAYLOAD_PATTERN.search(response_text)
    if match is None:
        raise ValueError("TTS response did not contain audio")
    try:
        return base64.b64decode(match.group(1), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("TTS response contained invalid audio") from exc


def synthesize_text_segments(text: str) -> list[dict[str, object]]:
    if not text.strip():
        return []
    lang = _language_for_text(text)
    info: dict[str, object] = {
        "original_text": text,
        "lang": lang,
        "audio_base64": None,
        "error": None,
    }
    try:
        audio_parts: list[bytes] = []
        audio_size = 0
        for part in _split_text(text):
            audio_part = _request_audio_part(part, lang)
            audio_size += len(audio_part)
            if audio_size > _TTS_AUDIO_MAX_BYTES:
                raise ValueError("TTS audio exceeds the safety limit")
            audio_parts.append(audio_part)
        audio = b"".join(audio_parts)
        if not audio:
            raise ValueError("TTS response was empty")
        info["audio_base64"] = base64.b64encode(audio).decode("ascii")
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Speech synthesis failed (%s)", type(exc).__name__)
        info["error"] = "speech_generation_failed"
    return [info]
