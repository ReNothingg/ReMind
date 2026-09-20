from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from services.tool_protocol import ModelToolResult
from services.web_search import (
    fetch_full_page,
    get_site_name,
    public_sources,
    run_web_search,
)
from utils.rate_limiting import RateLimiter

web_limiter = RateLimiter(max_requests=120, time_window=3600, namespace="web_tools")


@dataclass
class ResearchSession:
    rate_key: str = "guest"
    allowed_urls: set[str] = field(default_factory=set)
    sources: dict[int, dict[str, Any]] = field(default_factory=dict)
    source_ids: dict[str, int] = field(default_factory=dict)
    pages: dict[str, dict[str, Any]] = field(default_factory=dict)

    def register(self, source: dict[str, Any]) -> dict[str, Any]:
        url = str(source.get("final_url") or source.get("url") or "")
        key = navigation_url_key(url)
        if key not in self.source_ids:
            if len(self.sources) >= 96:
                raise ValueError("source_limit_reached")
            self.source_ids[key] = len(self.source_ids) + 1
        source_id = self.source_ids[key]
        item = {**source, "url": url, "rank": source_id}
        self.sources[source_id] = {**self.sources.get(source_id, {}), **item}
        self.allowed_urls.add(key)
        return item

    def execute(self, name: str, arguments: dict[str, Any]) -> ModelToolResult:
        try:
            if name in {"web_search", "web_search_batch"}:
                return self.search(arguments)
            return self.read(name, arguments)
        except ValueError as exc:
            return ModelToolResult({"ok": False, "error": str(exc)})

    def search(self, arguments: dict[str, Any]) -> ModelToolResult:
        queries = list(dict.fromkeys(arguments.get("queries") or [arguments.get("query", "")]))
        if not queries or len(queries) > 3 or any(not query.strip() for query in queries):
            raise ValueError("invalid_query")
        if any(_has_credentials(query) for query in queries):
            raise ValueError("private_data_in_web_request")
        domains = list(
            dict.fromkeys(domain.lower().rstrip(".") for domain in arguments.get("domains", []))
        )
        if any(
            not re.fullmatch(
                r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+",
                domain,
            )
            for domain in domains
        ):
            raise ValueError("invalid_domain")
        time_limit = {"day": "d", "week": "w", "month": "m", "year": "y"}.get(
            str(arguments.get("freshness") or "")
        )
        for _query in queries:
            if not web_limiter.evaluate(f"web_tools:{self.rate_key}").allowed:
                raise ValueError("web_rate_limit")

        def search_one(query: str) -> dict[str, Any]:
            search_query = query.strip()
            if domains:
                search_query += " (" + " OR ".join(f"site:{domain}" for domain in domains) + ")"
            try:
                return run_web_search(
                    search_query,
                    max_results=6,
                    fetch_pages=False,
                    timelimit=time_limit,
                    domains=domains,
                )
            except Exception:
                return {"error": "search_provider_unavailable", "sources": []}

        with ThreadPoolExecutor(max_workers=min(3, len(queries))) as pool:
            batches = list(pool.map(search_one, queries))
        public: list[dict[str, Any]] = []
        groups = []
        for query, batch in zip(queries, batches, strict=True):
            results = []
            for source in batch.get("sources", []):
                registered = self.register({**source, "evidence": "search_snippet"})
                public.extend(public_sources({"sources": [registered]}))
                results.append(
                    {
                        key: registered.get(key)
                        for key in ("rank", "title", "url", "snippet", "published_at", "evidence")
                    }
                )
            groups.append({"query": query, "sources": results, "error": batch.get("error")})
        ok = any(not batch.get("error") for batch in batches)
        public = list({source["rank"]: source for source in public}.values())
        status = (
            "web_search_done" if public else "web_search_no_results" if ok else "web_search_failed"
        )
        return ModelToolResult(
            {
                "ok": ok,
                "results": groups,
                "partial": any(batch.get("error") for batch in batches),
                "error": None if ok else "search_provider_unavailable",
                "evidence": "search_snippets_only",
            },
            events=[{"status": status, "query": " · ".join(queries), "sources": public}],
            sources=public,
        )

    def read(self, name: str, arguments: dict[str, Any]) -> ModelToolResult:
        source_id = arguments.get("source_id")
        url = arguments.get("url")
        if bool(source_id) == bool(url):
            raise ValueError("provide_url_or_source_id")
        if source_id is not None:
            source = self.sources.get(source_id)
            if source is None:
                raise ValueError("source_not_available")
            url = source["url"]
        url = str(url or "")
        if _has_credentials(url):
            raise ValueError("private_data_in_web_request")
        key = navigation_url_key(url)
        if key not in self.allowed_urls:
            raise ValueError("url_not_in_context")
        page = self.pages.get(key)
        if page is None:
            if len(self.pages) >= 12:
                raise ValueError("page_limit_reached")
            if not web_limiter.evaluate(f"web_tools:{self.rate_key}").allowed:
                raise ValueError("web_rate_limit")
            page = fetch_full_page(url, max_chars=100_000)
            if not page.get("ok") or not page.get("text"):
                return ModelToolResult(
                    {"ok": False, "error": page.get("error") or "readable_text_unavailable"}
                )
            self.pages[key] = page
        registered = self.register(
            {
                "url": page["final_url"],
                "title": get_site_name(page["final_url"]),
                "snippet": page["text"][:360],
                "evidence": "page_text",
            }
        )
        public = public_sources({"sources": [registered]})
        text = page["text"]
        common = {
            "ok": True,
            "source_id": registered["rank"],
            "url": registered["url"],
            "total_characters": len(text),
            "page_truncated": bool(page.get("truncated")),
        }
        if name == "web_links":
            offset = arguments.get("offset", 0)
            links = page.get("links", [])
            selected = links[offset : offset + 10]
            for link in selected:
                self.allowed_urls.add(navigation_url_key(link["url"]))
            output = {
                **common,
                "links": selected,
                "next_offset": (
                    offset + len(selected) if offset + len(selected) < len(links) else None
                ),
            }
        elif name == "web_find":
            matches = []
            for match in re.finditer(re.escape(arguments["query"]), text, re.IGNORECASE):
                start = max(0, match.start() - 240)
                matches.append(
                    {
                        "line": text.count("\n", 0, match.start()) + 1,
                        "offset": start,
                        "text": text[start : start + 1000],
                    }
                )
                if len(matches) > 20:
                    break
            output = {**common, "matches": matches[:20], "truncated": len(matches) > 20}
        else:
            offset = arguments.get("offset", 0)
            limit = arguments.get("max_characters", 12000)
            if offset > len(text):
                raise ValueError("offset_out_of_range")
            end = min(len(text), offset + limit)
            output = {
                **common,
                "offset": offset,
                "text": text[offset:end],
                "next_offset": end if end < len(text) else None,
            }
        return ModelToolResult(output, sources=public)


def _has_credentials(text: str) -> bool:
    return bool(
        re.search(
            r"(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|AIza[A-Za-z0-9_-]{20,}|-----BEGIN[^-]*PRIVATE KEY-----|Bearer\s+[A-Za-z0-9._-]{16,})",
            text,
            re.I,
        )
    )


def navigation_url_key(url: str) -> str:
    return str(url or "").strip().split("#", 1)[0]
