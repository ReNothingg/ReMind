from __future__ import annotations

import time

from sqlalchemy import update

from backend.db.models import AgentWorkspaceSlot, db
from backend.errors import ApiError
from backend.services import workspaces
from backend.services.agent_models import MODEL_ID, capabilities

PREFIX = "codex/"


def describe(owner, *, refresh=False):
    slot = workspaces.existing(owner)
    if not slot or not workspaces.capacity():
        return {
            "configured": bool(workspaces.capacity()),
            "connected": False,
            "models": [],
            "limits": [],
        }
    if (
        not refresh
        and slot.codex_catalog is not None
        and slot.codex_catalog_time > time.time() - 60
    ):
        return slot.codex_catalog
    generation, workspace = slot.generation, slot.workspace_id
    raw = workspaces.rpc(slot, "codex/status", owner=owner, timeout=22)
    models = []
    if raw.get("connected"):
        for item in raw.get("models") or []:
            slug = item.get("model") or item.get("id")
            if not isinstance(slug, str) or not MODEL_ID.fullmatch(slug):
                continue
            models.append(
                {
                    "id": PREFIX + slug,
                    "title": item.get("displayName") or slug,
                    "subtitle": "Codex",
                    "source": "codex",
                    "provider": "openai",
                    "stage": "release",
                    **capabilities(item, codex=True),
                }
            )
    data = {
        "configured": True,
        "connected": bool(raw.get("connected")),
        "plan": raw.get("plan"),
        "loginState": raw.get("loginState", "idle"),
        "email": raw.get("email"),
        "limits": raw.get("limits") or [],
        "models": models,
    }
    changed = db.session.execute(
        update(AgentWorkspaceSlot)
        .where(
            AgentWorkspaceSlot.id == slot.id,
            AgentWorkspaceSlot.generation == generation,
            AgentWorkspaceSlot.workspace_id == workspace,
            AgentWorkspaceSlot.user_id == owner,
        )
        .values(codex_catalog=data, codex_catalog_time=int(time.time()))
    )
    db.session.commit()
    if not changed.rowcount:
        raise ApiError("workspace_session_expired", status=401, code="workspace_session_expired")
    return data


def catalog(owner):
    if not owner:
        return []
    slot = workspaces.existing(owner)
    if not slot or not (slot.codex_catalog or {}).get("connected"):
        return []
    try:
        return describe(owner)["models"]
    except ApiError:
        return []


def start(owner):
    result = workspaces.rpc(workspaces.reserve(owner), "codex/login", owner=owner, timeout=25)
    return {"url": result["url"], "code": result["code"]}


def unlink(owner):
    slot = workspaces.existing(owner)
    if slot:
        generation = slot.generation
        workspaces.rpc(slot, "codex/logout", owner=owner, timeout=15)
        db.session.execute(
            update(AgentWorkspaceSlot)
            .where(
                AgentWorkspaceSlot.id == slot.id,
                AgentWorkspaceSlot.user_id == owner,
                AgentWorkspaceSlot.generation == generation,
            )
            .values(codex_catalog=None, codex_catalog_time=0)
        )
        db.session.commit()
