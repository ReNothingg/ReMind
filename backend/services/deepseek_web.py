from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urljoin, urlsplit

import urllib3

from backend.security.public_http import public_http_request
from backend.security.rate_limiting import RateLimiter
from backend.services.chat.cancellation import interruptible, stop_http_stream
from backend.services.web_research_settings import WebResearchSettings
from backend.services.web_search import get_site_name, is_public_http_url, robots_txt_allows

TOOLS_API = "https://api.deepseek.com/v1/tools"
MESSAGES_API = "https://api.deepseek.com/anthropic/v1/messages"
SECRET_TEXT = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|"
    r"AIza[A-Za-z0-9_-]{20,}|-----BEGIN[^-]*PRIVATE KEY-----|Bearer\s+[A-Za-z0-9._-]{16,})",
    re.I,
)
SECRET_PARAM = re.compile(
    r"(?:[\w-]*[_-])?(?:password|passwd|[a-z]*_?token|api_?key|signature|sig|secret|auth)",
    re.I,
)
SECRET_QUERY = re.compile(r"[?&]([A-Za-z_-]{1,60})=[^&\s]{1,4096}")
MARKDOWN_LINK = re.compile(r"\[([^\]\n]{0,200})\]\(<?([^\s<>()]{1,2048})>?\)")
FRESHNESS_DAYS = {"d": 1, "w": 7, "m": 31, "y": 366}
search_limiter = RateLimiter(max_requests=5, time_window=1, namespace="deepseek_web")


def has_web_credentials(value: str) -> bool:
    return bool(SECRET_TEXT.search(value)) or any(
        SECRET_PARAM.fullmatch(name) for name in SECRET_QUERY.findall(value)
    )


def _public_web_url(url: str, *, resolve=False) -> bool:
    if len(url) > 2048 or any(ord(char) < 33 or char == "\\" for char in url):
        return False
    try:
        parts = urlsplit(url)
        return (
            parts.username is None
            and parts.password is None
            and parts.port in (None, 443)
            and not has_web_credentials(url)
            and not any(SECRET_PARAM.fullmatch(name) for name, _ in parse_qsl(parts.query))
            and is_public_http_url(url, resolve_hostname=resolve)
        )
    except (ValueError, OSError, UnicodeError):
        return False


def _request(endpoint, key, payload, control, *, legacy=False):
    if control:
        control.check()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "ReMind",
    }
    if legacy:
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    try:
        with (
            public_http_request(
                "POST",
                endpoint,
                headers=headers,
                timeout=25 if legacy else 12,
                body=json.dumps(payload).encode(),
            ) as response,
            interruptible(control, lambda: stop_http_stream(response)),
        ):
            if response.status_code == 429:
                raise ValueError("web_rate_limit")
            if response.status_code in (401, 403):
                raise ValueError("web_key_rejected")
            if response.status_code != 200:
                raise ValueError("web_provider_unavailable")
            body = bytearray()
            for chunk in response.iter_content(16384):
                if control:
                    control.check()
                body.extend(chunk)
                if len(body) > 2 * 1024 * 1024:
                    raise ValueError("web_provider_response_too_large")
    except (OSError, urllib3.exceptions.HTTPError):
        if control:
            control.check()
        raise ValueError("web_provider_unavailable") from None
    try:
        result = json.loads(body)
    except (ValueError, RecursionError):
        raise ValueError("web_provider_unavailable") from None
    if not isinstance(result, dict):
        raise ValueError("web_provider_unavailable")
    return result


def _legacy_results(payload):
    content = payload.get("content")
    if not isinstance(content, list):
        raise ValueError("search_provider_unavailable")
    blocks = [block for block in content if isinstance(block, dict)]
    result_blocks = [
        block.get("content") for block in blocks if block.get("type") == "web_search_tool_result"
    ]
    if not result_blocks or not any(isinstance(items, list) for items in result_blocks):
        raise ValueError("search_provider_unavailable")
    snippets = {}
    for block in blocks:
        citations = block.get("citations")
        if not isinstance(citations, list):
            continue
        for item in citations:
            if isinstance(item, dict) and isinstance(item.get("url"), str):
                snippets.setdefault(item["url"], item.get("cited_text"))
    return [
        {
            **item,
            "snippet": item.get("snippet") or snippets.get(item.get("url")),
            "date": item.get("page_age"),
        }
        for items in result_blocks
        if isinstance(items, list)
        for item in items
        if isinstance(item, dict)
        and item.get("type") == "web_search_result"
        and isinstance(item.get("url"), str)
    ]


def _short_text(value, limit):
    return " ".join(value[: limit * 2].split())[:limit] if isinstance(value, str) else ""


def _recent(published, start):
    try:
        date = datetime.fromisoformat(published.replace("Z", "+00:00"))
        return date.replace(tzinfo=date.tzinfo or timezone.utc) >= start
    except ValueError:
        return False


def deepseek_search(
    query: str,
    settings: WebResearchSettings,
    *,
    domains: list[str] | None = None,
    freshness: str | None = None,
    control=None,
):
    if has_web_credentials(query):
        raise ValueError("private_data_in_web_request")
    if not settings.search_key:
        raise ValueError("web_key_required")
    query = " ".join(query.split())[:128]
    if not query:
        raise ValueError("invalid_query")
    legacy = settings.search_provider == "deepseek-legacy"
    if legacy:
        result = _request(
            MESSAGES_API,
            settings.search_key,
            {
                "model": "deepseek-v4-flash",
                "max_tokens": 4096,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"Perform a web search for the query: {query}"}
                        ],
                    }
                ],
                "tools": [
                    {
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": settings.max_uses,
                    }
                ],
                "thinking": {"type": "disabled"},
            },
            control,
            legacy=True,
        )
        items = _legacy_results(result)
    else:
        digest = hashlib.sha256(settings.search_key.encode()).hexdigest()
        if not search_limiter.evaluate(f"deepseek_web:{digest}").allowed:
            raise ValueError("web_rate_limit")
        items = _request(
            TOOLS_API + "/search",
            settings.search_key,
            {
                "query": query,
                "count": settings.count,
                "need_content": False,
            },
            control,
        ).get("results")
    if not isinstance(items, list):
        raise ValueError("search_provider_unavailable")
    now = datetime.now(timezone.utc)
    days = FRESHNESS_DAYS.get(freshness or "")
    since = now - timedelta(days=days) if days else None
    results = {}
    for item in items:
        url = item.get("url") if isinstance(item, dict) else None
        if not isinstance(url, str) or not _public_web_url(url) or url in results:
            continue
        site = (urlsplit(url).hostname or "").lower().rstrip(".")
        if domains and not any(site == domain or site.endswith("." + domain) for domain in domains):
            continue
        date = _short_text(item.get("date"), 100)
        if since and not _recent(date, since):
            continue
        results[url] = {
            "rank": len(results) + 1,
            "url": url,
            "display_url": site,
            "site_name": get_site_name(url),
            "title": _short_text(item.get("title"), 280) or site,
            "snippet": _short_text(item.get("snippet") or item.get("summary"), 600),
            "text": _short_text(item.get("summary"), 900),
            "published_at": date or None,
        }
        if len(results) >= (6 if legacy else settings.count):
            break
    return {"query": query, "created_at": now.isoformat(), "sources": list(results.values())}


def deepseek_fetch(url: str, settings: WebResearchSettings, *, control=None):
    if not settings.fetch_key:
        raise ValueError("web_key_required")
    if not _public_web_url(url, resolve=True):
        raise ValueError("blocked_or_invalid_url")
    if not robots_txt_allows(url, resolve_hostname=True):
        raise ValueError("robots_txt_disallowed")
    result = _request(
        TOOLS_API + "/fetch", settings.fetch_key, {"url": url.split("#", 1)[0]}, control
    )
    content = result.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("readable_text_unavailable")
    text = content[:100_000]
    links = {}
    for match in MARKDOWN_LINK.finditer(text):
        try:
            target = urljoin(url, match.group(2))
        except ValueError:
            continue
        if _public_web_url(target) and target not in links:
            links[target] = {
                "url": target,
                "title": match.group(1).strip() or get_site_name(target),
            }
        if len(links) >= 40:
            break
    return {
        "ok": True,
        "final_url": url,
        "text": text,
        "links": list(links.values()),
        "truncated": len(text) < len(content),
    }
