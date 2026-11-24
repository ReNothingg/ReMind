import re

from backend.ai_engine.skills import SKILL_BY_ID, SKILLS
from backend.db.models import AgentPlugin, User, db
from backend.errors import ApiError

PLUGIN_ID = re.compile(r"[a-z][a-z0-9-]{2,63}")
VERSION = re.compile(r"(?:0|[1-9][0-9]{0,5})(?:\.(?:0|[1-9][0-9]{0,5})){2}")
PACKAGE_FIELDS = {"id", "name", "version", "description", "instructions", "skills"}
MAX_CUSTOM_PLUGINS = 12
BUILTIN_PREFIX = "builtin:"


def plugin_error(code, status=400):
    return ApiError(code, status=status, code=code)


def _text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise plugin_error("plugin_invalid_manifest")
    return value.strip()


def validate_manifest(value):
    if not isinstance(value, dict) or set(value) != PACKAGE_FIELDS:
        raise plugin_error("plugin_invalid_manifest")
    plugin_id = value.get("id")
    version = value.get("version")
    skills = value.get("skills")
    if (
        not isinstance(plugin_id, str)
        or not PLUGIN_ID.fullmatch(plugin_id)
        or not isinstance(version, str)
        or not VERSION.fullmatch(version)
        or not isinstance(skills, list)
        or len(skills) > 12
        or any(not isinstance(skill, str) or skill not in SKILL_BY_ID for skill in skills)
    ):
        raise plugin_error("plugin_invalid_manifest")
    return {
        "id": plugin_id,
        "name": _text(value["name"], 100),
        "version": version,
        "description": _text(value["description"], 500),
        "instructions": _text(value["instructions"], 4000),
        "skills": list(dict.fromkeys(skills)),
    }


def _custom_plugins(owner):
    return AgentPlugin.query.filter_by(user_id=owner).filter(
        AgentPlugin.manifest.is_not(None), ~AgentPlugin.plugin_id.startswith(BUILTIN_PREFIX)
    )


def disabled_skills(owner):
    if owner is None:
        return frozenset()
    rows = (
        AgentPlugin.query.filter_by(user_id=owner, enabled=False)
        .filter(AgentPlugin.plugin_id.startswith(BUILTIN_PREFIX))
        .all()
    )
    return frozenset(row.plugin_id.removeprefix(BUILTIN_PREFIX) for row in rows)


def active_instructions(owner, available):
    if owner is None:
        return []
    rows = (
        _custom_plugins(owner)
        .filter_by(enabled=True)
        .order_by(AgentPlugin.created_at, AgentPlugin.plugin_id)
        .all()
    )
    return [
        {"name": row.manifest["name"], "instructions": row.manifest["instructions"]}
        for row in rows
        if set(row.manifest["skills"]) <= available
    ]


def serialize_custom(plugin):
    return {"kind": "custom", **plugin.manifest, "enabled": plugin.enabled}


def catalog(owner):
    disabled = disabled_skills(owner)
    return {
        "builtins": [
            {
                "id": skill.id,
                "title_key": skill.title_key,
                "description_key": skill.description_key,
                "enabled": skill.id not in disabled,
            }
            for skill in SKILLS
        ],
        "custom": [
            serialize_custom(plugin)
            for plugin in _custom_plugins(owner).order_by(AgentPlugin.created_at)
        ],
    }


def install_plugin(owner, document):
    manifest = validate_manifest(document)
    user = User.query.filter_by(id=owner).with_for_update().one_or_none()
    if user is None:
        raise plugin_error("auth_required", 401)
    current = db.session.get(AgentPlugin, (owner, manifest["id"]))
    if current:
        raise plugin_error("plugin_already_installed", 409)
    if _custom_plugins(owner).count() >= MAX_CUSTOM_PLUGINS:
        raise plugin_error("plugin_limit", 409)
    plugin = AgentPlugin(user_id=owner, plugin_id=manifest["id"], manifest=manifest, enabled=True)
    db.session.add(plugin)
    db.session.commit()
    return serialize_custom(plugin)


def _custom(owner, plugin_id):
    if not PLUGIN_ID.fullmatch(plugin_id):
        raise plugin_error("plugin_not_found", 404)
    plugin = _custom_plugins(owner).filter_by(plugin_id=plugin_id).with_for_update().one_or_none()
    if plugin is None:
        raise plugin_error("plugin_not_found", 404)
    return plugin


def edit_plugin(owner, plugin_id, payload):
    plugin = _custom(owner, plugin_id)
    if not isinstance(payload, dict) or not payload or set(payload) - {"enabled", "manifest"}:
        raise plugin_error("plugin_invalid_manifest")
    if "enabled" in payload:
        if type(payload["enabled"]) is not bool:
            raise plugin_error("plugin_invalid_manifest")
        plugin.enabled = payload["enabled"]
    if "manifest" in payload:
        manifest = validate_manifest(payload["manifest"])
        if manifest["id"] != plugin_id:
            raise plugin_error("plugin_invalid_manifest")
        plugin.manifest = manifest
    db.session.commit()
    return serialize_custom(plugin)


def set_builtin(owner, skill_id, enabled):
    if skill_id not in SKILL_BY_ID:
        raise plugin_error("plugin_not_found", 404)
    if type(enabled) is not bool:
        raise plugin_error("plugin_invalid_manifest")
    if User.query.filter_by(id=owner).with_for_update().one_or_none() is None:
        raise plugin_error("auth_required", 401)
    plugin_id = BUILTIN_PREFIX + skill_id
    plugin = db.session.get(AgentPlugin, (owner, plugin_id))
    if enabled and plugin:
        db.session.delete(plugin)
    elif not enabled and not plugin:
        db.session.add(AgentPlugin(user_id=owner, plugin_id=plugin_id, enabled=False))
    db.session.commit()


def remove_plugin(owner, plugin_id):
    db.session.delete(_custom(owner, plugin_id))
    db.session.commit()
