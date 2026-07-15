from __future__ import annotations

import ipaddress
import json
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from ai_engine.prompt_templates import render_prompt_section
from config import (
    USER_AGENT,
    WEB_SEARCH_ENABLED,
    WEB_SEARCH_FETCH_TIMEOUT_SECONDS,
    WEB_SEARCH_MAX_RESPONSE_BYTES,
    WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_PAGE_TEXT_CHARS,
)
from services.ai_provider import generate_text, is_ai_provider_configured

SEARCH_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "0.0.0.0"}
BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal")
ROBOTS_USER_AGENT = "ReMindBot"
ROBOTS_MAX_BYTES = 512 * 1024
WEB_SEARCH_MAX_REDIRECTS = 5
WEB_SEARCH_MAX_QUERY_VARIANTS = 3
WEB_SEARCH_FETCH_WORKERS = 4
WEB_SEARCH_CANDIDATE_MULTIPLIER = 4
WEB_SEARCH_MIN_FETCH_CANDIDATES = 8
WEB_SEARCH_CONTEXT_MAX_CHARS = 36_000
WEB_SEARCH_CONTEXT_SOURCE_MAX_CHARS = 3_200

HIGH_SIGNAL_HOST_SUFFIXES = (
    ".edu",
    ".gov",
    ".mil",
)
HIGH_SIGNAL_HOSTS = {
    "developer.mozilla.org",
    "docs.python.org",
    "github.com",
    "openai.com",
    "support.google.com",
    "learn.microsoft.com",
    "synvexai.com",
}


def _render_web_tool_prompt_section(section: str, **replacements: str) -> str:
    return render_prompt_section("tools/web.md", section, replacements)


@dataclass(frozen=True)
class RobotsRule:
    path: str
    allow: bool


@dataclass(frozen=True)
class RobotsPolicy:
    rules: tuple[RobotsRule, ...] = ()

    def can_fetch(self, url: str) -> bool:
        target = robots_match_target(url)
        matches = [rule for rule in self.rules if robots_path_matches(rule.path, target)]
        if not matches:
            return True

        best_length = max(len(rule.path.rstrip("$")) for rule in matches)
        best_matches = [rule for rule in matches if len(rule.path.rstrip("$")) == best_length]
        return any(rule.allow for rule in best_matches)


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


# Перенаправление когда модель вернула неизвестный ответ
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
        AUTO_SEARCH_POSITIVE_RE.search(cleaned) or AUTO_SEARCH_TIME_SENSITIVE_RE.search(cleaned)
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
    return generate_text(prompt, temperature=0, max_output_tokens=120) or ""


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
    if not is_ai_provider_configured():
        return fallback

    try:
        prompt = _render_web_tool_prompt_section(
            "Search Router Prompt",
            USER_MESSAGE_JSON=json.dumps(cleaned, ensure_ascii=False),
        )
        if not prompt:
            return fallback
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
    if not is_ai_provider_configured():
        return fallback

    try:
        prompt = _render_web_tool_prompt_section(
            "Search Query Writer Prompt",
            CURRENT_UTC_DATE=datetime.now(timezone.utc).date().isoformat(),
            USER_MESSAGE_JSON=json.dumps(cleaned, ensure_ascii=False),
        )
        if not prompt:
            return fallback
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


def query_terms(query: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[\wА-Яа-яЁё]{3,}", str(query or "").lower())
        if term not in {"the", "and", "for", "with", "что", "как", "или", "для"}
    }


def query_looks_time_sensitive(query: str) -> bool:
    cleaned = safe_query(query, max_len=500)
    return bool(
        AUTO_SEARCH_POSITIVE_RE.search(cleaned) or AUTO_SEARCH_TIME_SENSITIVE_RE.search(cleaned)
    )


def build_search_query_variants(query: str) -> list[str]:
    normalized = safe_query(query)
    if not normalized:
        return []

    variants = [normalized]
    lower = normalized.lower()
    current_year = str(datetime.now(timezone.utc).year)

    if query_looks_time_sensitive(normalized) and current_year not in lower:
        variants.append(f"{normalized} {current_year}")

    if not re.search(r"\b(official|официальн\w+|site:)\b", lower):
        variants.append(f"{normalized} official")

    deduped: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        cleaned = safe_query(variant)
        key = cleaned.lower()
        if cleaned and key not in seen:
            deduped.append(cleaned)
            seen.add(key)
        if len(deduped) >= WEB_SEARCH_MAX_QUERY_VARIANTS:
            break
    return deduped


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

    return bool(addresses) and all(
        not _is_blocked_ip_address(str(address)) for address in addresses
    )


def is_public_http_url(url: str, *, resolve_hostname: bool = False) -> bool:
    parsed = urlparse(url or "")
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.username or parsed.password:
        return False
    return _hostname_is_allowed(parsed.hostname or "", resolve=resolve_hostname)


def robots_match_target(url: str) -> str:
    parsed = urlparse(url or "")
    path = parsed.path or "/"
    if parsed.params:
        path = f"{path};{parsed.params}"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return path


def robots_path_matches(pattern: str, target: str) -> bool:
    if not pattern:
        return False

    anchored = pattern.endswith("$")
    pattern_body = pattern[:-1] if anchored else pattern
    regex = re.escape(pattern_body).replace(r"\*", ".*")
    if anchored:
        regex = f"^{regex}$"
    else:
        regex = f"^{regex}"
    return re.match(regex, target) is not None


def _robots_agent_score(agent: str, user_agent: str) -> int | None:
    normalized_agent = str(agent or "").strip().lower()
    normalized_user_agent = str(user_agent or "").strip().lower()
    if not normalized_agent:
        return None
    if normalized_agent == "*":
        return 0
    if normalized_agent in normalized_user_agent:
        return len(normalized_agent)
    return None


def _parse_robots_txt(robots_text: str, user_agent: str = ROBOTS_USER_AGENT) -> RobotsPolicy:
    groups: list[tuple[list[str], list[RobotsRule]]] = []
    current_agents: list[str] = []
    current_rules: list[RobotsRule] = []
    seen_rule = False

    def finish_group() -> None:
        if current_agents:
            groups.append((current_agents.copy(), current_rules.copy()))

    for raw_line in str(robots_text or "").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            finish_group()
            current_agents = []
            current_rules = []
            seen_rule = False
            continue

        if ":" not in line:
            continue

        field, value = line.split(":", 1)
        field = field.strip().lower()
        value = value.strip()

        if field == "user-agent":
            if current_agents and seen_rule:
                finish_group()
                current_agents = []
                current_rules = []
                seen_rule = False
            if value:
                current_agents.append(value.lower())
            continue

        if field not in {"allow", "disallow"} or not current_agents:
            continue

        seen_rule = True
        if not value:
            continue
        current_rules.append(RobotsRule(path=value, allow=field == "allow"))

    finish_group()

    best_score: int | None = None
    selected_rules: list[RobotsRule] = []
    for agents, rules in groups:
        matching_scores = [
            score
            for agent in agents
            for score in [_robots_agent_score(agent, user_agent)]
            if score is not None
        ]
        group_score = max(matching_scores, default=None)
        if group_score is None:
            continue
        if best_score is None or group_score > best_score:
            best_score = group_score
            selected_rules = list(rules)
        elif group_score == best_score:
            selected_rules.extend(rules)

    return RobotsPolicy(rules=tuple(selected_rules))


def _origin_from_url(url: str) -> str:
    parsed = urlparse(url or "")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


@lru_cache(maxsize=256)
def _robots_policy_for_origin(origin: str, user_agent: str = ROBOTS_USER_AGENT) -> RobotsPolicy:
    if not origin:
        return RobotsPolicy()

    robots_url = urljoin(f"{origin.rstrip('/')}/", "/robots.txt")
    try:
        with requests.get(
            robots_url,
            headers=SEARCH_HEADERS,
            timeout=WEB_SEARCH_FETCH_TIMEOUT_SECONDS,
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code >= 400:
                return RobotsPolicy()
            response.raise_for_status()

            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                chunks.append(chunk)
                size += len(chunk)
                if size >= ROBOTS_MAX_BYTES:
                    break

            raw_body = b"".join(chunks)
            encoding = response.encoding or response.apparent_encoding or "utf-8"
            return _parse_robots_txt(raw_body.decode(encoding, errors="replace"), user_agent)
    except Exception:
        return RobotsPolicy()


def robots_txt_allows(url: str, *, resolve_hostname: bool = False) -> bool:
    if not is_public_http_url(url, resolve_hostname=resolve_hostname):
        return False
    origin = _origin_from_url(url)
    if not origin:
        return False
    return _robots_policy_for_origin(origin, ROBOTS_USER_AGENT).can_fetch(url)


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


def canonical_search_url_key(url: str) -> str:
    parsed = urlparse(url or "")
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    netloc = hostname
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"

    query_pairs = [
        (key, item)
        for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
        if not key.lower().startswith("utm_")
        and key.lower() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}
        for item in values
    ]
    query = urlencode(sorted(query_pairs), doseq=True)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((scheme, netloc, path, "", query, ""))


def host_is_high_signal(url: str) -> bool:
    host = get_site_name(url)
    return host in HIGH_SIGNAL_HOSTS or any(
        host.endswith(suffix) for suffix in HIGH_SIGNAL_HOST_SUFFIXES
    )


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
    if not robots_txt_allows(url, resolve_hostname=True):
        return {
            "ok": False,
            "final_url": url,
            "status_code": None,
            "content_type": None,
            "text": "",
            "favicon_url": None,
            "error": "robots_txt_disallowed",
        }

    current_url = url
    try:
        for _redirect_count in range(WEB_SEARCH_MAX_REDIRECTS + 1):
            if not is_public_http_url(current_url, resolve_hostname=True):
                return {
                    "ok": False,
                    "final_url": current_url,
                    "status_code": None,
                    "content_type": None,
                    "text": "",
                    "favicon_url": None,
                    "error": "blocked_redirect_url",
                }

            with requests.get(
                current_url,
                headers=SEARCH_HEADERS,
                timeout=WEB_SEARCH_FETCH_TIMEOUT_SECONDS,
                allow_redirects=False,
                stream=True,
            ) as response:
                if response.is_redirect or response.is_permanent_redirect:
                    location = response.headers.get("Location")
                    if not location:
                        return {
                            "ok": False,
                            "final_url": response.url or current_url,
                            "status_code": response.status_code,
                            "content_type": response.headers.get("content-type", ""),
                            "text": "",
                            "favicon_url": None,
                            "error": "redirect_missing_location",
                        }

                    next_url = urljoin(response.url or current_url, location)
                    if not is_public_http_url(next_url, resolve_hostname=True):
                        return {
                            "ok": False,
                            "final_url": next_url,
                            "status_code": response.status_code,
                            "content_type": response.headers.get("content-type", ""),
                            "text": "",
                            "favicon_url": None,
                            "error": "blocked_redirect_url",
                        }
                    if not robots_txt_allows(next_url, resolve_hostname=True):
                        return {
                            "ok": False,
                            "final_url": next_url,
                            "status_code": response.status_code,
                            "content_type": response.headers.get("content-type", ""),
                            "text": "",
                            "favicon_url": None,
                            "error": "robots_txt_disallowed",
                        }
                    current_url = next_url
                    continue

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
                final_url = response.url or current_url
                favicon_url = None
                text = ""

                if "text/html" in content_type.lower() or "<html" in html[:2048].lower():
                    candidate_favicon = get_favicon_url(final_url, html)
                    if candidate_favicon and is_public_http_url(
                        candidate_favicon, resolve_hostname=True
                    ):
                        favicon_url = candidate_favicon
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

        return {
            "ok": False,
            "final_url": current_url,
            "status_code": None,
            "content_type": None,
            "text": "",
            "favicon_url": None,
            "error": "too_many_redirects",
        }
    except Exception as exc:
        return {
            "ok": False,
            "final_url": current_url,
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


def collect_web_search_candidates(query: str, max_candidates: int) -> list[dict[str, Any]]:
    candidates_by_url: dict[str, dict[str, Any]] = {}
    query_variants = build_search_query_variants(query)
    if not query_variants:
        return []

    per_query_limit = max(4, min(10, max_candidates))
    for variant_index, variant in enumerate(query_variants):
        try:
            raw_results = web_search_free(variant, max_results=per_query_limit)
        except Exception:
            continue

        for result_index, raw in enumerate(raw_results):
            url = normalize_search_url(raw.get("url") or raw.get("href") or "")
            if not url:
                continue
            key = canonical_search_url_key(url)
            existing = candidates_by_url.get(key)
            if existing:
                existing["matched_queries"].append(variant)
                existing["search_rank"] = min(existing["search_rank"], result_index + 1)
                existing["query_variant_index"] = min(
                    existing["query_variant_index"], variant_index
                )
                if not existing.get("snippet") and raw.get("snippet"):
                    existing["snippet"] = str(raw.get("snippet") or "").strip()
                continue

            candidates_by_url[key] = {
                "title": str(raw.get("title") or get_site_name(url)).strip(),
                "url": url,
                "snippet": str(raw.get("snippet") or "").strip(),
                "search_rank": result_index + 1,
                "query_variant_index": variant_index,
                "matched_queries": [variant],
            }

            if len(candidates_by_url) >= max_candidates:
                break
        if len(candidates_by_url) >= max_candidates:
            break

    return list(candidates_by_url.values())


def score_web_source(source: dict[str, Any], query: str) -> float:
    terms = query_terms(query)
    title = str(source.get("title") or "")
    snippet = str(source.get("snippet") or "")
    text = str(source.get("text") or "")
    searchable = f"{title} {snippet} {text[:1200]}".lower()
    matched_terms = {term for term in terms if term in searchable}

    score = 0.0
    if terms:
        score += (len(matched_terms) / len(terms)) * 4.0
    if source.get("ok") and text:
        score += 2.0
    elif snippet:
        score += 0.6

    text_length = len(text)
    if text_length >= 1000:
        score += 1.0
    elif text_length >= 350:
        score += 0.5

    if host_is_high_signal(str(source.get("final_url") or source.get("url") or "")):
        score += 1.0

    search_rank = int(source.get("search_rank") or 10)
    query_variant_index = int(source.get("query_variant_index") or 0)
    score += max(0.0, 1.2 - (search_rank - 1) * 0.12)
    score -= query_variant_index * 0.2
    if source.get("error"):
        score -= 0.8
    return score


def build_source_from_candidate(candidate: dict[str, Any], query: str) -> dict[str, Any] | None:
    url = normalize_search_url(candidate.get("url") or "")
    if not url:
        return None
    if not is_public_http_url(url, resolve_hostname=True) or not robots_txt_allows(
        url, resolve_hostname=True
    ):
        return None

    page = fetch_full_page(url)
    final_url = normalize_search_url(page.get("final_url") or url) or url
    title = str(candidate.get("title") or get_site_name(final_url)).strip()
    snippet = compact_text(candidate.get("snippet") or "", 360)
    page_text = compact_text(page.get("text") or "", WEB_SEARCH_PAGE_TEXT_CHARS)
    favicon_url = (
        page.get("favicon_url")
        or f"{urlparse(final_url).scheme}://{urlparse(final_url).netloc}/favicon.ico"
    )

    source = {
        "rank": 0,
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
        "search_rank": candidate.get("search_rank"),
        "query_variant_index": candidate.get("query_variant_index"),
        "matched_queries": candidate.get("matched_queries") or [],
    }
    source["score"] = score_web_source(source, query)
    return source


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

    max_candidates = max(
        WEB_SEARCH_MIN_FETCH_CANDIDATES,
        min(30, max_results * WEB_SEARCH_CANDIDATE_MULTIPLIER),
    )
    candidates = collect_web_search_candidates(normalized_query, max_candidates=max_candidates)
    sources: list[dict[str, Any]] = []
    if candidates:
        with ThreadPoolExecutor(
            max_workers=min(WEB_SEARCH_FETCH_WORKERS, len(candidates))
        ) as executor:
            future_to_candidate = {
                executor.submit(build_source_from_candidate, candidate, normalized_query): candidate
                for candidate in candidates
            }
            for future in as_completed(future_to_candidate):
                try:
                    source = future.result()
                except Exception:
                    continue
                if source:
                    sources.append(source)

    sources.sort(
        key=lambda source: (
            -float(source.get("score") or 0),
            int(source.get("query_variant_index") or 0),
            int(source.get("search_rank") or 999),
        )
    )

    host_counts: dict[str, int] = {}
    selected_sources: list[dict[str, Any]] = []
    for source in sources:
        host = str(source.get("site_name") or "")
        if host_counts.get(host, 0) >= 2:
            continue
        host_counts[host] = host_counts.get(host, 0) + 1
        public_source = dict(source)
        public_source["rank"] = len(selected_sources) + 1
        public_source.pop("score", None)
        public_source.pop("search_rank", None)
        public_source.pop("query_variant_index", None)
        public_source.pop("matched_queries", None)
        selected_sources.append(public_source)
        if len(selected_sources) >= max_results:
            break

    result = {
        "query": normalized_query,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sources": selected_sources,
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
            "Use only claims directly supported by these results. Cite by wrapping only the "
            "source-backed words, sentence, or clause in "
            '<c s="1">...</c> using the matching source id. '
            "For multiple sources use comma-separated ids. Do not invent facts or URLs. "
            "If support is insufficient, search again with a narrower query or say so."
        ),
    ]

    valid_sources = [source for source in sources if isinstance(source, dict)]
    header = "\n\n".join(blocks).strip()
    per_source_budget = max(
        800,
        min(
            WEB_SEARCH_CONTEXT_SOURCE_MAX_CHARS,
            (WEB_SEARCH_CONTEXT_MAX_CHARS - len(header)) // max(1, len(valid_sources)),
        ),
    )

    for source in valid_sources:

        rank = source.get("rank") or len(blocks)
        title = _compact_search_context_value(
            source.get("title") or source.get("site_name") or "Untitled", 240
        )
        url = _compact_search_context_value(
            source.get("final_url") or source.get("url") or "", 700
        )
        site_name = _compact_search_context_value(
            source.get("site_name") or get_site_name(str(url)), 160
        )
        snippet = _compact_search_context_value(source.get("snippet") or "", 600)
        metadata = "\n".join(
            [
                f"[{rank}] {title}",
                f"Site: {site_name}",
                f"URL: {url}",
                f"Snippet: {snippet}",
            ]
        )
        extract_budget = max(0, per_source_budget - len(metadata) - len("\nExtract: "))
        text = _compact_search_context_value(source.get("text") or "", extract_budget)

        blocks.append(f"{metadata}\nExtract: {text}")

    return "\n\n".join(blocks).strip()[:WEB_SEARCH_CONTEXT_MAX_CHARS]


def _compact_search_context_value(value: Any, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    return compact[:max_chars]


def build_web_search_augmented_message(user_message: str, search_payload: dict[str, Any]) -> str:
    context = build_web_search_context(search_payload)
    if not context:
        return str(user_message or "")

    return f"{user_message}\n\n" "<web_search_context>\n" f"{context}\n" "</web_search_context>"


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
