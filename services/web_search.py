from __future__ import annotations

import ipaddress
import json
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET

from ai_engine.prompt_templates import render_prompt_section
from config import (
    USER_AGENT,
    WEB_SEARCH_ENABLED,
    WEB_SEARCH_FETCH_TIMEOUT_SECONDS,
    WEB_SEARCH_MAX_RESPONSE_BYTES,
    WEB_SEARCH_PAGE_TEXT_CHARS,
)
from services.ai_provider import generate_text, is_ai_provider_configured

SEARCH_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"

BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "0.0.0.0"}
BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal")
ROBOTS_USER_AGENT = "ReMindBot"
ROBOTS_MAX_BYTES = 512 * 1024
WEB_SEARCH_MAX_REDIRECTS = 5
WEB_SEARCH_MAX_QUERY_VARIANTS = 3
WEB_SEARCH_FETCH_WORKERS = 4
WEB_SEARCH_CONTEXT_MAX_CHARS = 36_000
WEB_SEARCH_CONTEXT_SOURCE_MAX_CHARS = 3_200
WEB_SEARCH_QUALITY_SCORE_WINDOW = 7.0

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

TRUSTED_NEWS_HOSTS = {
    "apnews.com",
    "arstechnica.com",
    "axios.com",
    "bbc.com",
    "bbc.co.uk",
    "bloomberg.com",
    "businessinsider.com",
    "cnbc.com",
    "engadget.com",
    "forbes.com",
    "ft.com",
    "npr.org",
    "nytimes.com",
    "politico.com",
    "reuters.com",
    "straitstimes.com",
    "techcrunch.com",
    "theguardian.com",
    "theverge.com",
    "time.com",
    "washingtonpost.com",
    "wired.com",
    "wsj.com",
}

LOW_SIGNAL_AGGREGATOR_HOSTS = {
    "news.google.com",
}

SEARCH_QUERY_STOP_TERMS = {
    "and", "current", "find", "latest", "news", "official", "recent", "search", "the",
    "апрель", "август", "декабрь", "июль", "июнь", "май", "март", "ноябрь", "новости",
    "октябрь", "официально", "последние", "сентябрь", "свежие", "февраль", "январь",
    "для", "или", "как", "найди", "что",
}

QUERY_MONTH_TERMS = {
    1: ("january", "jan", "январь", "января"),
    2: ("february", "feb", "февраль", "февраля"),
    3: ("march", "mar", "март", "марта"),
    4: ("april", "apr", "апрель", "апреля"),
    5: ("may", "май", "мая"),
    6: ("june", "jun", "июнь", "июня"),
    7: ("july", "jul", "июль", "июля"),
    8: ("august", "aug", "август", "августа"),
    9: ("september", "sep", "sept", "сентябрь", "сентября"),
    10: ("october", "oct", "октябрь", "октября"),
    11: ("november", "nov", "ноябрь", "ноября"),
    12: ("december", "dec", "декабрь", "декабря"),
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
        if term not in SEARCH_QUERY_STOP_TERMS and not term.isdigit()
    }


def query_looks_time_sensitive(query: str) -> bool:
    cleaned = safe_query(query, max_len=500)
    return bool(
        AUTO_SEARCH_POSITIVE_RE.search(cleaned) or AUTO_SEARCH_TIME_SENSITIVE_RE.search(cleaned)
    )


def official_site_hint(query: str) -> str | None:
    lowered = str(query or "").lower()
    for host in sorted(HIGH_SIGNAL_HOSTS):
        brand = host.split(".")[0]
        if len(brand) >= 4 and re.search(rf"\b{re.escape(brand)}\b", lowered):
            return host
    return None


def build_search_query_variants(query: str) -> list[str]:
    normalized = safe_query(query)
    if not normalized:
        return []

    variants = [normalized]
    lower = normalized.lower()
    current_year = str(datetime.now(timezone.utc).year)

    if query_looks_time_sensitive(normalized) and current_year not in lower:
        variants.append(f"{normalized} {current_year}")

    official_host = official_site_hint(normalized)
    if official_host and "site:" not in lower:
        variants.append(f"{normalized} site:{official_host}")
    elif not re.search(r"\b(official|официальн\w+|site:)\b", lower):
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


def build_news_query_variants(query: str) -> list[str]:
    normalized = safe_query(query)
    if not normalized:
        return []
    editorial_query = safe_query(
        f"{normalized} Reuters Bloomberg Financial Times AP TechCrunch"
    )
    return list(
        dict.fromkeys(
            [
                normalized,
                editorial_query,
                safe_query(f"{normalized} site:reuters.com"),
                safe_query(f"{normalized} site:bloomberg.com"),
            ]
        )
    )


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


def _host_matches(host: str, domains: set[str]) -> bool:
    normalized = str(host or "").lower().removeprefix("www.")
    return any(normalized == domain or normalized.endswith(f".{domain}") for domain in domains)


def host_is_high_signal(url: str) -> bool:
    host = get_site_name(url)
    return _host_matches(host, HIGH_SIGNAL_HOSTS) or any(
        host.endswith(suffix) for suffix in HIGH_SIGNAL_HOST_SUFFIXES
    )


def host_is_trusted_news(url: str) -> bool:
    return _host_matches(get_site_name(url), TRUSTED_NEWS_HOSTS)


def host_is_low_signal_aggregator(url: str) -> bool:
    return _host_matches(get_site_name(url), LOW_SIGNAL_AGGREGATOR_HOSTS)


def query_host_affinity(url: str, query: str) -> float:
    host = re.sub(r"[^a-z0-9]+", " ", get_site_name(url).lower())
    if not host:
        return 0.0
    host_tokens = {token for token in host.split() if len(token) >= 4}
    query_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", str(query or "").lower())
        if len(token) >= 4 and not token.isdigit()
    }
    return 1.0 if host_tokens & query_tokens else 0.0


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


def extract_published_at(html: str) -> str | None:
    soup = BeautifulSoup(html or "", "html.parser")
    meta_keys = {
        "article:published_time",
        "date",
        "datepublished",
        "dc.date",
        "dc.date.issued",
        "og:published_time",
        "publishdate",
        "pubdate",
    }
    for meta in soup.find_all("meta"):
        key = str(
            meta.get("property") or meta.get("name") or meta.get("itemprop") or ""
        ).strip().lower()
        value = str(meta.get("content") or "").strip()
        if key in meta_keys and value:
            return value[:120]

    time_node = soup.find("time", attrs={"datetime": True})
    if time_node:
        value = str(time_node.get("datetime") or "").strip()
        if value:
            return value[:120]

    def find_json_date(value: Any) -> str | None:
        if isinstance(value, dict):
            published = value.get("datePublished") or value.get("dateCreated")
            if published:
                return str(published).strip()[:120]
            for nested in value.values():
                result = find_json_date(nested)
                if result:
                    return result
        elif isinstance(value, list):
            for nested in value:
                result = find_json_date(nested)
                if result:
                    return result
        return None

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            parsed = json.loads(script.string or script.get_text(" ", strip=True) or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        published = find_json_date(parsed)
        if published:
            return published
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
                published_at = None

                if "text/html" in content_type.lower() or "<html" in html[:2048].lower():
                    candidate_favicon = get_favicon_url(final_url, html)
                    if candidate_favicon and is_public_http_url(
                        candidate_favicon, resolve_hostname=True
                    ):
                        favicon_url = candidate_favicon
                    published_at = extract_published_at(html)
                    text = extract_text_from_html(html)

                return {
                    "ok": True,
                    "final_url": final_url,
                    "status_code": response.status_code,
                    "content_type": content_type,
                    "text": compact_text(text),
                    "favicon_url": favicon_url,
                    "published_at": published_at,
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


def _ddgs_text_search(query: str, max_results: int | None) -> list[dict[str, Any]]:
    from ddgs import DDGS

    with DDGS() as ddgs:
        results = ddgs.text(query, max_results=max_results)

    return list(results or [])


def _ddgs_news_search(query: str, max_results: int | None) -> list[dict[str, Any]]:
    from ddgs import DDGS

    with DDGS() as ddgs:
        results = ddgs.news(query, max_results=max_results)

    return list(results or [])


def _duckduckgo_html_search(query: str, max_results: int | None) -> list[dict[str, Any]]:
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
        if max_results is not None and len(results) >= max_results:
            break

    return results


def web_search_free(query: str, max_results: int | None = None) -> list[dict[str, Any]]:
    if max_results is not None:
        max_results = max(1, int(max_results))
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
                "published_at": str(
                    raw.get("published_at") or raw.get("published") or raw.get("date") or ""
                ).strip(),
                "result_type": "web",
            }
        )
        if max_results is not None and len(results) >= max_results:
            break

    return results


def web_search_news_free(
    query: str,
    max_results: int | None = None,
) -> list[dict[str, Any]]:
    if max_results is not None:
        max_results = max(1, int(max_results))
    raw_results = _ddgs_news_search(query, max_results)
    results: list[dict[str, Any]] = []
    for raw in raw_results:
        url = normalize_search_url(raw.get("url") or raw.get("href") or "")
        if not url:
            continue
        results.append(
            {
                "title": str(raw.get("title") or get_site_name(url)).strip(),
                "url": url,
                "snippet": str(raw.get("body") or raw.get("content") or "").strip(),
                "published_at": str(
                    raw.get("published_at") or raw.get("published") or raw.get("date") or ""
                ).strip(),
                "result_type": "news",
            }
        )
        if max_results is not None and len(results) >= max_results:
            break
    return results


def google_news_rss_search(query: str) -> list[dict[str, Any]]:
    with requests.get(
        GOOGLE_NEWS_RSS_URL,
        params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
        headers=SEARCH_HEADERS,
        timeout=WEB_SEARCH_FETCH_TIMEOUT_SECONDS,
        stream=True,
    ) as response:
        response.raise_for_status()
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(chunk_size=16_384):
            if not chunk:
                continue
            remaining = WEB_SEARCH_MAX_RESPONSE_BYTES - size
            if remaining <= 0:
                break
            chunks.append(chunk[:remaining])
            size += min(len(chunk), remaining)
            if len(chunk) > remaining:
                break

    root = ET.fromstring(b"".join(chunks))
    results: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        url = normalize_search_url(item.findtext("link") or "")
        publisher = item.find("source")
        publisher_url = normalize_search_url(
            publisher.get("url") if publisher is not None else ""
        )
        if (
            not url
            or not publisher_url
            or not is_public_http_url(publisher_url, resolve_hostname=False)
        ):
            continue
        publisher_name = compact_text(
            publisher.text if publisher is not None else get_site_name(publisher_url),
            160,
        )
        description_html = item.findtext("description") or ""
        snippet = BeautifulSoup(description_html, "html.parser").get_text(" ", strip=True)
        results.append(
            {
                "title": compact_text(item.findtext("title") or publisher_name, 240),
                "url": url,
                "snippet": compact_text(snippet, 360),
                "published_at": str(item.findtext("pubDate") or "").strip(),
                "result_type": "news_rss",
                "publisher_url": publisher_url,
                "site_name": publisher_name or get_site_name(publisher_url),
                "display_url": get_display_url(publisher_url),
                "favicon_url": f"{publisher_url.rstrip('/')}/favicon.ico",
            }
        )
    return results


def collect_web_search_candidates(
    query: str,
    max_candidates: int | None = None,
) -> list[dict[str, Any]]:
    candidates_by_url: dict[str, dict[str, Any]] = {}
    query_variants = build_search_query_variants(query)
    if not query_variants:
        return []

    per_query_limit = max(4, max_candidates) if max_candidates is not None else None
    search_batches: list[tuple[int, str, list[dict[str, Any]]]] = []
    if query_looks_time_sensitive(query):
        try:
            search_batches.append((0, query, google_news_rss_search(query)))
        except Exception:
            pass
        for news_variant_index, news_variant in enumerate(
            build_news_query_variants(query),
            start=len(search_batches),
        ):
            try:
                search_batches.append(
                    (
                        news_variant_index,
                        news_variant,
                        web_search_news_free(news_variant, max_results=per_query_limit),
                    )
                )
            except Exception:
                continue

    variant_offset = len(search_batches)
    for variant_index, variant in enumerate(query_variants, start=variant_offset):
        try:
            raw_results = web_search_free(variant, max_results=per_query_limit)
        except Exception:
            continue
        search_batches.append((variant_index, variant, raw_results))

    for variant_index, variant, raw_results in search_batches:
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
                if not existing.get("published_at") and raw.get("published_at"):
                    existing["published_at"] = str(raw.get("published_at") or "").strip()
                if str(raw.get("result_type") or "").startswith("news"):
                    existing["result_type"] = str(raw.get("result_type"))
                for field in ("publisher_url", "site_name", "display_url", "favicon_url"):
                    if not existing.get(field) and raw.get(field):
                        existing[field] = raw.get(field)
                continue

            candidates_by_url[key] = {
                "title": str(raw.get("title") or get_site_name(url)).strip(),
                "url": url,
                "snippet": str(raw.get("snippet") or "").strip(),
                "published_at": str(raw.get("published_at") or "").strip(),
                "search_rank": result_index + 1,
                "query_variant_index": variant_index,
                "matched_queries": [variant],
                "result_type": str(raw.get("result_type") or "web"),
                "publisher_url": str(raw.get("publisher_url") or ""),
                "site_name": str(raw.get("site_name") or ""),
                "display_url": str(raw.get("display_url") or ""),
                "favicon_url": str(raw.get("favicon_url") or ""),
            }

            if max_candidates is not None and len(candidates_by_url) >= max_candidates:
                break
        if max_candidates is not None and len(candidates_by_url) >= max_candidates:
            break

    return list(candidates_by_url.values())


def parse_published_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def source_recency_score(published_at: Any, query: str) -> float:
    if not query_looks_time_sensitive(query):
        return 0.0
    published = parse_published_datetime(published_at)
    if published is None:
        return 0.0
    age_days = max(0.0, (datetime.now(timezone.utc) - published).total_seconds() / 86400)
    if age_days <= 7:
        return 3.0
    if age_days <= 31:
        return 2.0
    if age_days <= 180:
        return 0.8
    if age_days <= 365:
        return 0.0
    if age_days <= 730:
        return -1.5
    return -2.5


def requested_period_score(published_at: Any, query: str) -> float:
    published = parse_published_datetime(published_at)
    if published is None:
        return 0.0
    lowered_query = str(query or "").lower()
    requested_years = {
        int(year) for year in re.findall(r"\b(20\d{2})\b", lowered_query)
    }
    requested_month = next(
        (
            month
            for month, terms in QUERY_MONTH_TERMS.items()
            if any(re.search(rf"\b{re.escape(term)}\b", lowered_query) for term in terms)
        ),
        None,
    )
    if requested_years and published.year not in requested_years:
        return -7.0
    if requested_month is not None and published.month != requested_month:
        return -6.0
    if requested_years or requested_month is not None:
        return 1.5
    return 0.0


def score_search_candidate(candidate: dict[str, Any], query: str) -> float:
    terms = query_terms(query)
    title = str(candidate.get("title") or "")
    snippet = str(candidate.get("snippet") or "")
    url = str(
        candidate.get("authority_url")
        or candidate.get("publisher_url")
        or candidate.get("final_url")
        or candidate.get("url")
        or ""
    )
    searchable = f"{title} {snippet}".lower()
    matched_terms = {term for term in terms if term in searchable}

    score = 0.0
    if terms:
        score += (len(matched_terms) / len(terms)) * 5.0
        title_terms = {term for term in terms if term in title.lower()}
        score += (len(title_terms) / len(terms)) * 1.5

    score += query_host_affinity(url, query) * 4.0
    if host_is_high_signal(url):
        score += 2.5
    is_trusted_news = host_is_trusted_news(url)
    if is_trusted_news:
        score += 2.0
        if query_looks_time_sensitive(query):
            score += 3.0
    if host_is_low_signal_aggregator(url):
        score -= 2.0

    explicit_years = set(re.findall(r"\b20\d{2}\b", str(query or "")))
    if explicit_years:
        score += 1.8 if any(year in searchable for year in explicit_years) else -1.0

    search_rank = int(candidate.get("search_rank") or 10)
    query_variant_index = int(candidate.get("query_variant_index") or 0)
    score += max(0.0, 1.5 - (search_rank - 1) * 0.12)
    score -= query_variant_index * 0.15
    score += source_recency_score(candidate.get("published_at"), query)
    score += requested_period_score(candidate.get("published_at"), query)
    if str(candidate.get("result_type") or "").startswith("news"):
        score += 3.0
    return score


def score_web_source(source: dict[str, Any], query: str) -> float:
    score = score_search_candidate(source, query)
    text = str(source.get("text") or "")
    if source.get("ok") and text:
        score += 2.0
    elif source.get("snippet"):
        score += 0.6

    text_length = len(text)
    if text_length >= 1000:
        score += 1.0
    elif text_length >= 350:
        score += 0.5

    if source.get("error"):
        score -= 0.8
    return score


def build_source_from_candidate(candidate: dict[str, Any], query: str) -> dict[str, Any] | None:
    url = normalize_search_url(candidate.get("url") or "")
    if not url:
        return None
    if not is_public_http_url(url, resolve_hostname=True):
        return None

    is_rss_metadata = candidate.get("result_type") == "news_rss"
    if is_rss_metadata:
        page = {
            "ok": False,
            "final_url": url,
            "status_code": None,
            "content_type": "application/rss+xml",
            "text": "",
            "favicon_url": candidate.get("favicon_url"),
            "published_at": candidate.get("published_at"),
            "error": None,
        }
    elif robots_txt_allows(url, resolve_hostname=True):
        page = fetch_full_page(url)
    else:
        page = {
            "ok": False,
            "final_url": url,
            "status_code": None,
            "content_type": None,
            "text": "",
            "favicon_url": None,
            "published_at": None,
            "error": "robots_disallowed",
        }
    final_url = normalize_search_url(page.get("final_url") or url) or url
    title = str(candidate.get("title") or get_site_name(final_url)).strip()
    snippet = compact_text(candidate.get("snippet") or "", 360)
    page_text = compact_text(page.get("text") or "", WEB_SEARCH_PAGE_TEXT_CHARS)
    publisher_url = normalize_search_url(candidate.get("publisher_url") or "")
    authority_url = publisher_url or final_url
    favicon_url = (
        candidate.get("favicon_url") or page.get("favicon_url")
        or f"{urlparse(authority_url).scheme}://{urlparse(authority_url).netloc}/favicon.ico"
    )

    source = {
        "rank": 0,
        "title": title,
        "url": url,
        "final_url": final_url,
        "display_url": candidate.get("display_url") or get_display_url(authority_url),
        "site_name": candidate.get("site_name") or get_site_name(authority_url),
        "snippet": snippet,
        "text": page_text,
        "published_at": page.get("published_at") or candidate.get("published_at"),
        "favicon_url": favicon_url,
        "ok": bool(page.get("ok")),
        "status_code": page.get("status_code"),
        "content_type": page.get("content_type"),
        "error": page.get("error"),
        "search_rank": candidate.get("search_rank"),
        "query_variant_index": candidate.get("query_variant_index"),
        "matched_queries": candidate.get("matched_queries") or [],
        "result_type": candidate.get("result_type") or "web",
        "authority_url": authority_url,
    }
    source["score"] = score_web_source(source, query)
    return source


def run_web_search(query: str, max_results: int | None = None) -> dict[str, Any]:
    if max_results is not None:
        max_results = max(1, int(max_results))
    normalized_query = safe_query(query)
    if not normalized_query:
        return {
            "query": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "sources": [],
            "context": "",
        }

    candidates = collect_web_search_candidates(normalized_query)
    candidates.sort(
        key=lambda candidate: score_search_candidate(candidate, normalized_query),
        reverse=True,
    )
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
    best_score = float(sources[0].get("score") or 0) if sources else 0.0
    quality_floor = max(3.0, best_score - WEB_SEARCH_QUALITY_SCORE_WINDOW)
    prefer_established_sources = query_looks_time_sensitive(normalized_query) and any(
        host_is_high_signal(str(source.get("final_url") or source.get("url") or ""))
        or host_is_trusted_news(str(source.get("final_url") or source.get("url") or ""))
        for source in sources
    )
    for source in sources:
        host = str(source.get("site_name") or "")
        host_count = host_counts.get(host, 0)
        source_url = str(
            source.get("authority_url")
            or source.get("final_url")
            or source.get("url")
            or ""
        )
        is_established_source = host_is_high_signal(source_url) or host_is_trusted_news(
            source_url
        )
        authority_adjustment = (
            -5.0 if prefer_established_sources and not is_established_source else 0.0
        )
        diversity_penalty = host_count * (0.5 if is_established_source else 1.25)
        source_quality_floor = quality_floor - (1.0 if is_established_source else 0.0)
        diversity_adjusted_score = (
            float(source.get("score") or 0)
            + authority_adjustment
            - diversity_penalty
        )
        if diversity_adjusted_score < source_quality_floor:
            continue
        host_counts[host] = host_count + 1
        public_source = dict(source)
        public_source["rank"] = len(selected_sources) + 1
        public_source.pop("score", None)
        public_source.pop("search_rank", None)
        public_source.pop("query_variant_index", None)
        public_source.pop("matched_queries", None)
        public_source.pop("result_type", None)
        public_source.pop("authority_url", None)
        selected_sources.append(public_source)
        if max_results is not None and len(selected_sources) >= max_results:
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
        published_at = _compact_search_context_value(source.get("published_at") or "", 120)
        metadata = "\n".join(
            [
                f"[{rank}] {title}",
                f"Site: {site_name}",
                f"URL: {url}",
                f"Published: {published_at or 'unknown'}",
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
                "published_at": source.get("published_at"),
            }
        )

    return public


def favicon_service_url(domain_or_url: str) -> str:
    domain = get_site_name(domain_or_url)
    return f"https://www.google.com/s2/favicons?sz=64&domain={quote_plus(domain)}"
