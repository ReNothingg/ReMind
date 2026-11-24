from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock, Timer

from flask import current_app

from backend.agent_profile import supports_delegation
from backend.ai_engine.errors import ProviderRequestError
from backend.security.rate_limiting import RateLimiter
from backend.services.agent_plugins import disabled_skills
from backend.services.agent_runtime_settings import load_agent_runtime
from backend.services.chat.cancellation import GenerationControl, GenerationStopped, interruptible
from backend.services.deepseek_web import has_web_credentials
from backend.services.model_access import can_user_access_model, list_accessible_models
from backend.services.tools.tool_protocol import ModelToolResult

MAX_TASKS_PER_TURN = 6
TASK_TIMEOUT_SECONDS = 38
delegation_limiter = RateLimiter(max_requests=24, time_window=3600, namespace="agent_delegation")


@dataclass(frozen=True)
class DelegationRoute:
    model: str
    effort: str | None = None


def _requested_route(task, parent, settings):
    model = task.get("model")
    effort = task.get("reasoning_effort") or None
    if model:
        if not settings["subagentModelSelection"] or model not in settings["subagentAllowedModels"]:
            return None, "subagent_model_not_allowed"
        return DelegationRoute(model, effort), None
    if effort:
        return None, "subagent_effort_requires_model"
    default = settings["subagentModel"] or parent.model
    if not supports_delegation(default):
        return None, "subagent_model_unavailable"
    return DelegationRoute(default, parent.effort if default == parent.model else None), None


@dataclass(frozen=True)
class DelegationChild:
    tree: DelegationTree
    depth: int


class DelegationTree:
    def __init__(self, owner, max_depth, max_active):
        self.owner = owner
        self.max_depth = max_depth
        self.max_active = max_active
        self.active = 0
        self.active_codex = 0
        self.started = 0
        self.lock = Lock()

    def _reserve(self, model, limit):
        with self.lock:
            if self.started >= MAX_TASKS_PER_TURN:
                return "subagent_task_limit"
            codex = model.startswith("codex/")
            if self.active >= min(self.max_active, limit) or (codex and self.active_codex >= 2):
                return "subagent_capacity"
            if not delegation_limiter.evaluate(f"agent_delegation:user_{self.owner}").allowed:
                return "subagent_rate_limit"
            self.started += 1
            self.active += 1
            self.active_codex += int(codex)
        return None

    def _release(self, model):
        with self.lock:
            self.active -= 1
            self.active_codex -= int(model.startswith("codex/"))

    def _available_at_depth(self, settings, depth):
        return (
            depth < min(self.max_depth, settings["subagentMaxDepth"])
            and "subagents" not in disabled_skills(self.owner)
        )

    def models(self, depth):
        settings = load_agent_runtime(self.owner, fresh=True)
        if not settings["subagentModelSelection"] or not self._available_at_depth(settings, depth):
            return ModelToolResult({"ok": False, "error": "subagent_model_selection_disabled"})
        allowed = set(settings["subagentAllowedModels"])
        entries = [
            {
                "id": model["id"],
                "title": model["title"],
                "reasoning_efforts": model.get("thinkingLevels", []),
            }
            for model in list_accessible_models(self.owner)
            if model["id"] in allowed
        ]
        return ModelToolResult({"ok": True, "models": entries})

    def run(self, tasks, depth, parent, parent_control):
        settings = load_agent_runtime(self.owner, fresh=True)
        if not self._available_at_depth(settings, depth):
            return ModelToolResult({"ok": False, "error": "subagent_depth_limit"})
        if parent_control:
            parent_control.check()
        app = current_app._get_current_object()
        results = []
        capacity = min(self.max_active, settings["subagentMaxActive"], len(tasks))
        with ThreadPoolExecutor(max_workers=capacity) as pool:
            for task in tasks:
                title, prompt = task["title"].strip(), task["task"].strip()
                if (
                    not title
                    or not prompt
                    or has_web_credentials(title)
                    or has_web_credentials(prompt)
                ):
                    results.append({"title": title, "ok": False, "error": "subagent_invalid_task"})
                    continue
                route, error = _requested_route(task, parent, settings)
                if error:
                    results.append({"title": title, "ok": False, "error": error})
                    continue
                if failure := self._reserve(route.model, settings["subagentMaxActive"]):
                    results.append({"title": title, "ok": False, "error": failure})
                    continue
                try:
                    results.append(
                        pool.submit(
                            self._run_one, app, task, route, parent, depth, parent_control
                        )
                    )
                except RuntimeError:
                    self._release(route.model)
                    results.append({"title": title, "ok": False, "error": "subagent_unavailable"})
            results = [entry if isinstance(entry, dict) else entry.result() for entry in results]
        if parent_control:
            parent_control.check()
        ok = any(entry["ok"] for entry in results)
        return ModelToolResult(
            {"ok": ok, "results": results, "error": None if ok else "subagent_failed"}
        )

    def _run_one(self, app, task, route, parent, depth, parent_control):
        from backend.ai_engine import get_model_function

        title, prompt = task["title"].strip(), task["task"].strip()
        deadline = None
        try:
            time_limit = (
                parent_control.timeout(TASK_TIMEOUT_SECONDS)
                if parent_control
                else TASK_TIMEOUT_SECONDS
            )
            control = GenerationControl(time_limit=time_limit)
            deadline = Timer(time_limit, control.stop)
            deadline.daemon = True
            deadline.start()
            with app.app_context(), interruptible(parent_control, control.stop):
                handler = get_model_function(route.model)
                if not handler or not can_user_access_model(route.model, self.owner):
                    return {"title": title, "ok": False, "error": "subagent_model_unavailable"}
                if task.get("reasoning_effort"):
                    model = next(
                        (item for item in list_accessible_models(self.owner) if item["id"] == route.model),
                        {},
                    )
                    if route.effort not in model.get("thinkingLevels", ()):
                        return {"title": title, "ok": False, "error": "subagent_effort_unavailable"}
                settings = load_agent_runtime(self.owner, fresh=True)
                if not self._available_at_depth(settings, depth):
                    return {"title": title, "ok": False, "error": "subagent_depth_limit"}
                current, error = _requested_route(task, parent, settings)
                if current != route:
                    return {
                        "title": title,
                        "ok": False,
                        "error": error or "subagent_model_not_allowed",
                    }
                control.check()
                stream = handler(
                    self.owner,
                    {
                        "message": f"{title}\n\n{prompt}",
                        "model": route.model,
                        "thinkingLevel": route.effort,
                        "serviceTier": "standard",
                        "temporary_chat": True,
                        "_delegation": DelegationChild(self, depth + 1),
                        "_generation_control": control,
                    },
                )
                try:
                    answer = ""
                    for event in stream:
                        control.check()
                        if isinstance(event, str):
                            answer += event[: max(0, 8000 - len(answer))]
                    if answer.strip():
                        return {"title": title, "ok": True, "model": route.model, "answer": answer}
                finally:
                    stream.close()
        except GenerationStopped:
            return {"title": title, "ok": False, "error": "subagent_timed_out"}
        except ProviderRequestError:
            pass
        finally:
            if deadline:
                deadline.cancel()
            self._release(route.model)
        return {"title": title, "ok": False, "error": "subagent_unavailable"}
