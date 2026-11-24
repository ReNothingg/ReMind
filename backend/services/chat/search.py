from __future__ import annotations

from typing import Any

from backend.responses import logger
from backend.services.deepseek_web import deepseek_search
from backend.services.web_research_settings import load_web_research
from backend.services.web_search import (
    build_web_search_augmented_message,
    classify_auto_web_search_intent,
    decide_auto_web_search,
    explicit_web_search_requested,
    public_sources,
    rewrite_web_search_query,
    run_web_search,
    web_search_requested,
)


def extract_web_sources(user_data: dict[str, Any]) -> list[dict[str, Any]]:
    return public_sources(user_data.get("web_search"))


def merge_web_sources(
    existing: Any,
    incoming: Any,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    positions: dict[str, int] = {}

    for source in [
        *(existing if isinstance(existing, list) else []),
        *(incoming if isinstance(incoming, list) else []),
    ]:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or source.get("final_url") or "").strip()
        if url:
            identity = f"url:{url}"
        else:
            identity = "meta:" + "\x1f".join(
                str(source.get(field) or "").strip().casefold()
                for field in ("site_name", "title", "display_url")
            )
        if identity in positions:
            current = merged[positions[identity]]
            for key, value in source.items():
                if not current.get(key) and value:
                    current[key] = value
            continue
        positions[identity] = len(merged)
        merged.append(dict(source))

    return merged


def _execute_and_attach_web_search(
    user_data: dict[str, Any],
    original_message: str,
    search_query: str | None = None,
    decision: dict[str, Any] | None = None,
    owner: int | None = None,
) -> list[dict[str, Any]]:
    query = str(search_query or original_message or "").strip()
    settings = load_web_research(owner)
    search_payload = (
        run_web_search(query)
        if settings.search_provider == "remind"
        else deepseek_search(query, settings)
    )
    user_data["web_search"] = search_payload
    if decision:
        user_data["web_search_decision"] = decision
    user_data["message"] = build_web_search_augmented_message(original_message, search_payload)
    return public_sources(search_payload)


def _manual_web_search_requested(user_data: dict[str, Any], original_message: str) -> bool:
    return web_search_requested(user_data.get("webSearch")) or explicit_web_search_requested(
        original_message
    )


def _rewrite_search_query(original_message: str) -> dict[str, Any]:
    rewrite = rewrite_web_search_query(original_message)
    query = str(rewrite.get("query") or original_message or "").strip()
    return {
        "query": query or str(original_message or "").strip(),
        "reason": str(rewrite.get("reason") or "").strip(),
        "source": str(rewrite.get("source") or "fallback").strip() or "fallback",
    }


def _resolve_web_search_plan(
    user_data: dict[str, Any],
    original_message: str,
    *,
    auto_enabled: bool,
) -> dict[str, Any]:
    message = str(original_message or "").strip()
    plan: dict[str, Any] = {"mode": None, "query": message, "decision": None}
    if not message:
        return plan

    if _manual_web_search_requested(user_data, message):
        rewrite = _rewrite_search_query(message)
        return {
            **plan,
            "mode": "manual",
            "query": rewrite["query"],
            "rewrite": rewrite,
        }

    if not auto_enabled:
        return plan

    auto_strategy = classify_auto_web_search_intent(message)
    if auto_strategy == "skip":
        plan["decision"] = {
            "search": False,
            "query": message,
            "reason": "fast static query",
            "source": "rule",
        }
        return plan
    if auto_strategy == "search":
        rewrite = _rewrite_search_query(message)
        return {
            **plan,
            "mode": "auto",
            "query": rewrite["query"],
            "rewrite": rewrite,
            "decision": {
                "search": True,
                "query": rewrite["query"],
                "reason": "fast search intent",
                "source": "rule",
            },
        }

    decision = decide_auto_web_search(message)
    plan["decision"] = decision
    if decision.get("search"):
        plan["mode"] = "auto"
        if decision.get("source") == "model":
            plan["query"] = str(decision.get("query") or message).strip() or message
        else:
            rewrite = _rewrite_search_query(message)
            plan["query"] = rewrite["query"]
            plan["rewrite"] = rewrite
    return plan


def attach_web_search_context(
    user_data: dict[str, Any], original_message: str, *, auto_enabled: bool, owner: int | None
) -> None:
    try:
        plan = _resolve_web_search_plan(user_data, original_message, auto_enabled=auto_enabled)
        if plan.get("mode"):
            _execute_and_attach_web_search(
                user_data,
                original_message,
                search_query=plan.get("query"),
                decision=plan.get("decision"),
                owner=owner,
            )
    except Exception as exc:
        logger.warning("Web search failed: %s", exc, exc_info=True)
