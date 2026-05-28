from __future__ import annotations

import json
import ipaddress
import re
import socket
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL_NAME,
    USER_AGENT,
    WEB_SEARCH_ENABLED,
    WEB_SEARCH_FETCH_TIMEOUT_SECONDS,
    WEB_SEARCH_MAX_RESPONSE_BYTES,
    WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_PAGE_TEXT_CHARS,
)

SEARCH_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "0.0.0.0"}
BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal")


def is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def web_search_requested(value: Any) -> bool:
    return WEB_SEARCH_ENABLED and is_truthy(value)


def auto_web_search_requested(value: Any) -> bool:
    return WEB_SEARCH_ENABLED and is_truthy(value)


# Router fallback rules for cases where the model decision is unavailable.
AUTO_SEARCH_NEGATIVE_RE = re.compile(
    r"\b("
    r"без\s+(интернета|поиска|веб[-\s]?поиска)|"
    r"не\s+(ищи|гугли|пользуйся\s+интернетом|используй\s+интернет|делай\s+поиск)|"
    r"offline|without\s+(web|internet|search)|do\s+not\s+(search|browse|google)|"
    r"don't\s+(search|browse|google)|no\s+(web|internet|search)"
    r")\b",
    re.IGNORECASE,
)

AUTO_SEARCH_POSITIVE_RE = re.compile(
    r"\b("
    r"последн\w+|свеж\w+|новост\w+|сейчас|сегодня|вчера|завтра|"
    r"актуальн\w+|текущ\w+|недавн\w+|обновлен\w+|релиз\w+|"
    r"найди|поищи|загугли|проверь|источник\w+|ссылк\w+|"
    r"цена|стоимость|курс|акци[ияй]|бирж\w+|крипт\w+|погод\w+|"
    r"расписани\w+|результат\w+|матч\w+|турнир\w+|закон\w+|"
    r"latest|recent|newest|current|currently|today|yesterday|tomorrow|"
    r"news|update|release|price|stock|crypto|weather|schedule|score|"
    r"source|sources|link|links|search|find|lookup|verify|browse|google"
    r")\b",
    re.IGNORECASE,
)

EXPLICIT_SEARCH_REQUEST_RE = re.compile(
    r"\b("
    r"используй\s+(веб[-\s]?)?поиск|"
    r"включи\s+(веб[-\s]?)?поиск|"
    r"с\s+поиском\s+в\s+интернете|"
    r"поиск\s+в\s+интернете|"
    r"найди\s+в\s+интернете|"
    r"поищи\s+в\s+интернете|"
    r"проверь\s+в\s+интернете|"
    r"загугли|"
    r"use\s+(web\s+)?search|"
    r"search\s+the\s+web|"
    r"look\s+it\s+up|"
    r"browse\s+the\s+web"
    r")\b",
    re.IGNORECASE,
)

AUTO_SEARCH_TIME_SENSITIVE_RE = re.compile(
    r"\b("
    r"кто\s+(сейчас|теперь)|что\s+(сейчас|теперь)|когда\s+(выйдет|релиз)|"
    r"где\s+(сейчас|купить|скачать)|сколько\s+(стоит|сейчас)|"
    r"who\s+is\s+(the\s+)?(current|now)|what\s+is\s+(the\s+)?latest|"
    r"when\s+(is|will)|where\s+(to\s+buy|can\s+i)|how\s+much\s+(is|does)"
    r")\b",
    re.IGNORECASE,
)


def explicit_web_search_requested(query: str) -> bool:
    cleaned = safe_query(query, max_len=500).lower()
    if len(cleaned) < 4:
        return False
    if AUTO_SEARCH_NEGATIVE_RE.search(cleaned):
        return False
    return bool(EXPLICIT_SEARCH_REQUEST_RE.search(cleaned))


def should_auto_web_search(query: str) -> bool:
    cleaned = safe_query(query, max_len=500).lower()
    if len(cleaned) < 4:
        return False
    if AUTO_SEARCH_NEGATIVE_RE.search(cleaned):
        return False
    return explicit_web_search_requested(cleaned) or bool(
        AUTO_SEARCH_POSITIVE_RE.search(cleaned)
        or AUTO_SEARCH_TIME_SENSITIVE_RE.search(cleaned)
    )


AUTO_SEARCH_STATIC_RE = re.compile(
    r"\b("
    r"напиши|сочини|придумай|переведи|объясни|расскажи\s+что\s+такое|что\s+такое|"
    r"помоги\s+с|сделай\s+текст|сгенерируй|исправь|перепиши|резюмируй|"
    r"explain|write|draft|translate|summarize|rewrite|brainstorm|"
    r"help\s+me\s+with|how\s+do\s+i|how\s+to|what\s+is|debug|fix\s+this"
    r")\b",
    re.IGNORECASE,
)


def classify_auto_web_search_intent(query: str) -> str:
    cleaned = safe_query(query, max_len=500).lower()
    if len(cleaned) < 4 or AUTO_SEARCH_NEGATIVE_RE.search(cleaned):
        return "skip"
    if explicit_web_search_requested(cleaned):
        return "search"
    if AUTO_SEARCH_POSITIVE_RE.search(cleaned) or AUTO_SEARCH_TIME_SENSITIVE_RE.search(cleaned):
        return "search"
    if AUTO_SEARCH_STATIC_RE.search(cleaned):
        return "skip"
    return "model"


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _coerce_model_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "search", "needed"}:
            return True
        if normalized in {"false", "no", "0", "skip", "not_needed"}:
            return False
    return None


def _call_search_decision_model(prompt: str) -> str:
    import google.generativeai as genai

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL_NAME or "gemini-1.5-flash")
    response = model.generate_content(
        prompt,
        generation_config={"temperature": 0, "max_output_tokens": 120},
    )
    return (getattr(response, "text", None) or "").strip()


def decide_auto_web_search(query: str) -> dict[str, Any]:
    cleaned = safe_query(query, max_len=500)
    fallback_search = should_auto_web_search(cleaned)
    fallback = {
        "search": fallback_search,
        "query": cleaned,
        "reason": "fallback",
        "source": "fallback",
    }

    if not WEB_SEARCH_ENABLED or not cleaned:
        return {**fallback, "search": False}
    if AUTO_SEARCH_NEGATIVE_RE.search(cleaned):
        return {
            "search": False,
            "query": cleaned,
            "reason": "user asked not to search",
            "source": "rule",
        }
    if not GEMINI_API_KEY:
        return fallback

    try:
        prompt = (
            "You are ReMind's web-search router. Decide whether the assistant must use "
            "live web search before answering the user's latest message.\n"
            'Return ONLY compact JSON: {"search": true|false, "query": "...", "reason": "..."}.\n'
            "Use search=true for current/recent facts, news, prices, laws, schedules, releases, "
            "specific webpages, or when the user explicitly asks to search/browse/use the internet.\n"
            "Use search=false for timeless explanations, writing, coding, math, summaries of provided text, "
            "or casual conversation. If the user asks not to search, use false.\n"
            f"User message JSON: {json.dumps(cleaned, ensure_ascii=False)}"
        )
        data = _extract_json_object(_call_search_decision_model(prompt))
        model_search = _coerce_model_bool(data.get("search"))
        if model_search is None:
            return fallback

        decision_query = safe_query(data.get("query") or cleaned)
        return {
            "search": model_search,
            "query": decision_query or cleaned,
            "reason": str(data.get("reason") or "").strip()[:240],
            "source": "model",
        }
    except Exception:
        return fallback


def rewrite_web_search_query(query: str) -> dict[str, Any]:
    cleaned = safe_query(query, max_len=500)
    fallback = {
        "query": cleaned,
        "reason": "fallback",
        "source": "fallback",
    }
    if not WEB_SEARCH_ENABLED or not cleaned:
        return fallback
    if not GEMINI_API_KEY:
        return fallback

    try:
        prompt = (
            "You are ReMind's web-search query writer. Convert the user's message into "
            "the best concise query for a general web search engine.\n"
            'Return ONLY compact JSON: {"query": "...", "reason": "..."}.\n'
            "Rules:\n"
            "- Do not answer the user.\n"
            "- Remove assistant instructions such as 'use search', 'find online', or 'answer me'.\n"
            "- Preserve important entities, names, locations, dates, versions, and constraints.\n"
            "- If the request is time-sensitive, include words like latest/current/news and relevant dates.\n"
            "- Keep the query short enough for a search box; no markdown, no citations, no URLs unless the user asks for a specific URL.\n"
            f"Current UTC date: {datetime.now(timezone.utc).date().isoformat()}\n"
            f"User message JSON: {json.dumps(cleaned, ensure_ascii=False)}"
        )
        data = _extract_json_object(_call_search_decision_model(prompt))
        rewritten = safe_query(data.get("query") or "")
        if not rewritten:
            return fallback

        return {
            "query": rewritten,
            "reason": str(data.get("reason") or "").strip()[:240],
            "source": "model",
        }
    except Exception:
        return fallback


def safe_query(query: str, max_len: int = 240) -> str:
    cleaned = re.sub(r"\s+", " ", str(query or "")).strip()
    return cleaned[:max_len]


def _is_blocked_ip_address(address: str) -> bool:
    parsed = ipaddress.ip_address(address)
    return any(
        (
            parsed.is_private,
            parsed.is_loopback,
            parsed.is_link_local,
            parsed.is_multicast,
            parsed.is_reserved,
            parsed.is_unspecified,
        )
    )


def _hostname_is_allowed(hostname: str, *, resolve: bool = False) -> bool:
    host = (hostname or "").strip().lower().rstrip(".")
    if not host:
        return False
    if host in BLOCKED_HOSTNAMES or any(host.endswith(suffix) for suffix in BLOCKED_HOST_SUFFIXES):
        return False

    try:
        return not _is_blocked_ip_address(host)
    except ValueError:
        pass

    if not resolve:
        return True

    try:
        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            if info and info[4]
        }
    except socket.gaierror:
        return False

    return bool(addresses) and all(not _is_blocked_ip_address(address) for address in addresses)


def is_public_http_url(url: str, *, resolve_hostname: bool = False) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme in {"http", "https"} and _hostname_is_allowed(
        parsed.hostname or "", resolve=resolve_hostname
    )


def normalize_search_url(url: str) -> str:
    normalized = str(url or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("//"):
        normalized = f"https:{normalized}"
    if normalized.startswith("/"):
        normalized = urljoin("https://duckduckgo.com", normalized)

    parsed = urlparse(normalized)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            normalized = unquote(target)

    if not is_public_http_url(normalized):
        return ""
    return normalized


def get_site_name(url: str) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host or "source"


def get_display_url(url: str) -> str:
    parsed = urlparse(url or "")
    host = get_site_name(url)
    path = parsed.path.rstrip("/")
    if not path or path == "/":
        return host
    return f"{host}{path[:80]}"


def get_favicon_url(page_url: str, html: str) -> str | None:
    soup = BeautifulSoup(html or "", "html.parser")
    icon_rels = {
        "icon",
        "shortcut icon",
        "apple-touch-icon",
        "apple-touch-icon-precomposed",
        "mask-icon",
    }

    for link in soup.find_all("link"):
        rel = link.get("rel")
        href = link.get("href")
        if not href:
            continue

        rel_text = " ".join(rel).lower() if isinstance(rel, list) else str(rel or "").lower()
        if any(icon_rel in rel_text for icon_rel in icon_rels):
            return urljoin(page_url, href)

    parsed = urlparse(page_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/favicon.ico"
    return None


def extract_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")

    for tag in soup(["script", "style", "noscript", "svg", "template"]):
        tag.decompose()

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    body = soup.body or soup
    text = body.get_text("\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    final_text = "\n".join(lines)
    return f"{title}\n\n{final_text}" if title else final_text


def compact_text(text: str, max_chars: int = WEB_SEARCH_PAGE_TEXT_CHARS) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "..."


def fetch_full_page(url: str) -> dict[str, Any]:
    if not is_public_http_url(url, resolve_hostname=True):
        return {
            "ok": False,
            "final_url": url,
            "status_code": None,
            "content_type": None,
            "text": "",
            "favicon_url": None,
            "error": "blocked_or_invalid_url",
        }

    try:
        with requests.get(
            url,
            headers=SEARCH_HEADERS,
            timeout=WEB_SEARCH_FETCH_TIMEOUT_SECONDS,
            allow_redirects=True,
            stream=True,
        ) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_content(chunk_size=16384):
                if not chunk:
                    continue
                chunks.append(chunk)
                size += len(chunk)
                if size >= WEB_SEARCH_MAX_RESPONSE_BYTES:
                    break

            raw_body = b"".join(chunks)
            encoding = response.encoding or response.apparent_encoding or "utf-8"
            html = raw_body.decode(encoding, errors="replace")
            content_type = response.headers.get("content-type", "")
            final_url = response.url
            favicon_url = None
            text = ""

            if "text/html" in content_type.lower() or "<html" in html[:2048].lower():
                favicon_url = get_favicon_url(final_url, html)
                text = extract_text_from_html(html)

            return {
                "ok": True,
                "final_url": final_url,
                "status_code": response.status_code,
                "content_type": content_type,
                "text": compact_text(text),
                "favicon_url": favicon_url,
                "error": None,
            }
    except Exception as exc:
        return {
            "ok": False,
            "final_url": url,
            "status_code": None,
            "content_type": None,
            "text": "",
            "favicon_url": None,
            "error": str(exc),
        }


def _ddgs_text_search(query: str, max_results: int) -> list[dict[str, Any]]:
    from ddgs import DDGS

    with DDGS() as ddgs:
        results = ddgs.text(query, max_results=max_results)

    return list(results or [])


def _duckduckgo_html_search(query: str, max_results: int) -> list[dict[str, Any]]:
    response = requests.get(
        "https://duckduckgo.com/html/",
        params={"q": query},
        headers=SEARCH_HEADERS,
        timeout=WEB_SEARCH_FETCH_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results: list[dict[str, Any]] = []

    for item in soup.select(".result"):
        link = item.select_one(".result__a")
        if not link:
            continue
        snippet_node = item.select_one(".result__snippet")
        results.append(
            {
                "title": link.get_text(" ", strip=True),
                "href": link.get("href"),
                "body": snippet_node.get_text(" ", strip=True) if snippet_node else "",
            }
        )
        if len(results) >= max_results:
            break

    return results


def web_search_free(query: str, max_results: int = WEB_SEARCH_MAX_RESULTS) -> list[dict[str, Any]]:
    max_results = max(1, min(int(max_results or WEB_SEARCH_MAX_RESULTS), 10))
    try:
        raw_results = _ddgs_text_search(query, max_results)
    except Exception:
        raw_results = _duckduckgo_html_search(query, max_results)

    results: list[dict[str, Any]] = []
    for raw in raw_results:
        url = normalize_search_url(raw.get("href") or raw.get("url") or "")
        if not url:
            continue

        results.append(
            {
                "title": str(raw.get("title") or get_site_name(url)).strip(),
                "url": url,
                "snippet": str(raw.get("body") or raw.get("content") or "").strip(),
            }
        )
        if len(results) >= max_results:
            break

    return results


def run_web_search(query: str, max_results: int = WEB_SEARCH_MAX_RESULTS) -> dict[str, Any]:
    max_results = max(1, min(int(max_results or WEB_SEARCH_MAX_RESULTS), 10))
    normalized_query = safe_query(query)
    if not normalized_query:
        return {
            "query": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "sources": [],
            "context": "",
        }

    raw_results = web_search_free(normalized_query, max_results=max_results)
    seen_urls: set[str] = set()
    sources: list[dict[str, Any]] = []

    for raw in raw_results:
        url = normalize_search_url(raw.get("url") or "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        page = fetch_full_page(url)
        final_url = normalize_search_url(page.get("final_url") or url) or url
        title = str(raw.get("title") or get_site_name(final_url)).strip()
        snippet = compact_text(raw.get("snippet") or "", 360)
        page_text = compact_text(page.get("text") or "", WEB_SEARCH_PAGE_TEXT_CHARS)
        favicon_url = page.get("favicon_url") or f"{urlparse(final_url).scheme}://{urlparse(final_url).netloc}/favicon.ico"

        sources.append(
            {
                "rank": len(sources) + 1,
                "title": title,
                "url": url,
                "final_url": final_url,
                "display_url": get_display_url(final_url),
                "site_name": get_site_name(final_url),
                "snippet": snippet,
                "text": page_text,
                "favicon_url": favicon_url,
                "ok": bool(page.get("ok")),
                "status_code": page.get("status_code"),
                "content_type": page.get("content_type"),
                "error": page.get("error"),
            }
        )

    result = {
        "query": normalized_query,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
    }
    result["context"] = build_web_search_context(result)
    return result


def build_web_search_context(search_payload: dict[str, Any]) -> str:
    sources = search_payload.get("sources") if isinstance(search_payload, dict) else []
    if not isinstance(sources, list) or not sources:
        return ""

    blocks = [
        "WEB SEARCH RESULTS",
        f"Query: {search_payload.get('query') or ''}",
        f"Fetched at: {search_payload.get('created_at') or ''}",
        (
            "Use these results for current facts. Cite by wrapping only the "
            "source-backed words, sentence, or clause in "
            '<c s="1">...</c> using the matching source id. '
            "For multiple sources use comma-separated ids. Do not invent URLs."
        ),
    ]

    for source in sources:
        if not isinstance(source, dict):
            continue

        rank = source.get("rank") or len(blocks)
        title = source.get("title") or source.get("site_name") or "Untitled"
        url = source.get("final_url") or source.get("url") or ""
        site_name = source.get("site_name") or get_site_name(str(url))
        snippet = source.get("snippet") or ""
        text = source.get("text") or ""

        blocks.append(
            "\n".join(
                [
                    f"[{rank}] {title}",
                    f"Site: {site_name}",
                    f"URL: {url}",
                    f"Snippet: {snippet}",
                    f"Extract: {text}",
                ]
            )
        )

    return "\n\n".join(blocks).strip()


def build_web_search_augmented_message(user_message: str, search_payload: dict[str, Any]) -> str:
    context = build_web_search_context(search_payload)
    if not context:
        return str(user_message or "")

    return (
        f"{user_message}\n\n"
        "<web_search_context>\n"
        f"{context}\n"
        "</web_search_context>"
    )


def public_sources(search_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    sources = search_payload.get("sources") if isinstance(search_payload, dict) else []
    public: list[dict[str, Any]] = []
    if not isinstance(sources, list):
        return public

    for source in sources:
        if not isinstance(source, dict):
            continue
        public.append(
            {
                "rank": source.get("rank"),
                "title": source.get("title"),
                "url": source.get("final_url") or source.get("url"),
                "display_url": source.get("display_url"),
                "site_name": source.get("site_name"),
                "snippet": source.get("snippet"),
                "favicon_url": source.get("favicon_url"),
            }
        )

    return public


def favicon_service_url(domain_or_url: str) -> str:
    domain = get_site_name(domain_or_url)
    return f"https://www.google.com/s2/favicons?sz=64&domain={quote_plus(domain)}"
