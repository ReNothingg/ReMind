from __future__ import annotations

import re
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import load_only

from backend.db.models import AgentSkill, Mind, User, db
from backend.services.project_resources import owned_workspace
from backend.services.skill_packages import (
    is_script_path,
    is_skill_name,
    normalize_skill,
    skill_error,
)

SKILL_ID = re.compile(r"[a-f0-9]{32}")
SLASH = re.compile(r"^/([a-z0-9]+(?:-[a-z0-9]+)*)(?=\s|$)")
SKILL_REF = "skill:"
MAX_PERSONAL_SKILLS = 32
MAX_PROJECT_SKILLS = 16
SKILL_READ_CHARS = 8000


def is_skill_reference(value):
    return (
        isinstance(value, str)
        and value.startswith(SKILL_REF)
        and is_skill_name(value[len(SKILL_REF) :])
    )


def _scope(owner, workspace_id, *, lock=False):
    if workspace_id is None:
        return "account"
    return owned_workspace(owner, workspace_id, lock=lock).id


def _query(owner, scope):
    return AgentSkill.query.filter_by(user_id=owner, scope=scope)


def _details(row):
    properties = dict(row.properties)
    scripts = properties.pop("scriptPaths", [])
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "enabled": row.enabled,
        "resourceCount": len(row.resources) - len(scripts),
        "scriptCount": len(scripts),
        **properties,
    }


def library(owner, workspace_id=None):
    return [
        _details(row)
        for row in _query(owner, _scope(owner, workspace_id)).order_by(AgentSkill.name)
    ]


def owned_skill_references(owner, names):
    if not owner or not names:
        return set()
    return {
        SKILL_REF + name
        for (name,) in _query(owner, "account")
        .with_entities(AgentSkill.name)
        .filter(AgentSkill.name.in_(names))
    }


def install_skill(owner, workspace_id, payload):
    if not isinstance(payload, dict) or set(payload) - {"document", "replace"}:
        raise skill_error("skill_invalid_document")
    replace = payload.get("replace", False)
    if type(replace) is not bool:
        raise skill_error("skill_invalid_document")
    record = normalize_skill(payload.get("document"))
    if User.query.filter_by(id=owner).with_for_update().one_or_none() is None:
        raise skill_error("auth_required", 401)
    scope = _scope(owner, workspace_id, lock=True)
    query = _query(owner, scope)
    row = query.filter_by(name=record["name"]).with_for_update().one_or_none()
    if row and not replace:
        raise skill_error("skill_exists", 409)
    created = row is None
    if created:
        if query.count() >= (MAX_PROJECT_SKILLS if workspace_id else MAX_PERSONAL_SKILLS):
            raise skill_error("skill_library_limit", 409)
        row = AgentSkill(
            id=uuid4().hex, user_id=owner, scope=scope, workspace_id=workspace_id, enabled=True
        )
        db.session.add(row)
    for key, value in record.items():
        setattr(row, key, value)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise skill_error("skill_exists", 409) from None
    return _details(row), created


def _owned_skill(owner, workspace_id, skill_id, *, lock=True):
    if not isinstance(skill_id, str) or not SKILL_ID.fullmatch(skill_id):
        raise skill_error("skill_not_found", 404)
    query = _query(owner, _scope(owner, workspace_id)).filter_by(id=skill_id)
    row = (query.with_for_update() if lock else query).one_or_none()
    if row is None:
        raise skill_error("skill_not_found", 404)
    return row


def inspect_skill(owner, workspace_id, skill_id):
    row = _owned_skill(owner, workspace_id, skill_id, lock=False)
    return {**_details(row), "body": row.body, **_member_paths(row)}


def toggle_skill(owner, workspace_id, skill_id, payload):
    if (
        not isinstance(payload, dict)
        or set(payload) != {"enabled"}
        or type(payload["enabled"]) is not bool
    ):
        raise skill_error("skill_invalid_document")
    row = _owned_skill(owner, workspace_id, skill_id)
    row.enabled = payload["enabled"]
    db.session.commit()
    return _details(row)


def remove_skill(owner, workspace_id, skill_id):
    row = _owned_skill(owner, workspace_id, skill_id)
    if workspace_id is None:
        ref = SKILL_REF + row.name
        for mind in Mind.query.filter(Mind.user_id == owner, Mind.skill_ids.is_not(None)):
            if isinstance(mind.skill_ids, list) and ref in mind.skill_ids:
                mind.skill_ids = [item for item in mind.skill_ids if item != ref]
    db.session.delete(row)
    db.session.commit()


def session_skill_catalog(owner, workspace_id, allowed=None):
    if not owner or allowed == frozenset():
        return {}
    scopes = ("account", workspace_id) if workspace_id else ("account",)
    query = (
        AgentSkill.query.filter(
            AgentSkill.user_id == owner, AgentSkill.scope.in_(scopes), AgentSkill.enabled.is_(True)
        )
        .options(
            load_only(
                AgentSkill.id,
                AgentSkill.scope,
                AgentSkill.name,
                AgentSkill.description,
                AgentSkill.properties,
            )
        )
        .order_by(AgentSkill.workspace_id.is_(None), AgentSkill.name)
    )
    if allowed is not None:
        query = query.filter(AgentSkill.name.in_(allowed))
    skills = {}
    for row in query:
        if row.name not in skills:
            skills[row.name] = {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                **row.properties,
            }
    return skills


def requested_skill(message, catalog):
    if not isinstance(message, str) or (command := SLASH.match(message)) is None:
        return None
    name = command[1]
    skill = catalog.get(name)
    return name if skill and skill["userInvocable"] else None


def _active_skill(owner, workspace_id, skill):
    scopes = ("account", workspace_id) if workspace_id else ("account",)
    return (
        AgentSkill.query.filter(
            AgentSkill.id == skill["id"],
            AgentSkill.user_id == owner,
            AgentSkill.scope.in_(scopes),
            AgentSkill.enabled.is_(True),
        )
        .populate_existing()
        .one_or_none()
    )


def _member_paths(row):
    return {
        "resources": sorted(path for path in row.resources if not is_script_path(path)),
        "scripts": row.properties.get("scriptPaths", []),
    }


def skill_script_source(owner, workspace_id, skill, path, *, user_invoked=False):
    if not is_script_path(path):
        return None
    row = _active_skill(owner, workspace_id, skill)
    if row is None or not row.properties.get("userInvocable" if user_invoked else "modelInvocable"):
        return None
    if path not in row.properties.get("scriptPaths", []):
        return None
    return row.resources.get(path)


def skill_content(owner, workspace_id, skill, *, path=None, offset=0):
    row = _active_skill(owner, workspace_id, skill)
    if row is None:
        return {"ok": False, "error": "skill_not_found"}
    content = row.body if path is None else row.resources.get(path)
    if content is None:
        return {"ok": False, "error": "skill_resource_not_found"}
    if offset > len(content):
        return {"ok": False, "error": "invalid_offset"}
    end = offset + SKILL_READ_CHARS
    return {
        "ok": True,
        "name": row.name,
        **({"path": path} if path is not None else _member_paths(row)),
        "content": content[offset:end],
        "nextOffset": end if end < len(content) else None,
    }
