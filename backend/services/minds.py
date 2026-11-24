from __future__ import annotations

import re
import secrets
from typing import Any

from sqlalchemy import or_

from backend.ai_engine.skills import SKILL_BY_ID
from backend.db.models import Mind, MindPin, db
from backend.errors import ApiError
from backend.services.agent_skills import SKILL_REF, is_skill_reference, owned_skill_references

PUBLIC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,128}$")


CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


HTML_TAG_RE = re.compile(r"<[^>]+>")


MIND_CATEGORIES = [
    {"id": "general", "label": "Общее"},
    {"id": "education", "label": "Обучение"},
    {"id": "development", "label": "Разработка"},
    {"id": "productivity", "label": "Продуктивность"},
    {"id": "creative", "label": "Креатив"},
    {"id": "business", "label": "Бизнес"},
    {"id": "security", "label": "Безопасность"},
]


MIND_CATEGORY_IDS = {category["id"] for category in MIND_CATEGORIES}


MIND_VISIBILITIES = {"private", "link", "store"}


def _validate_public_id(value: str) -> str:
    public_id = str(value or "").strip()
    if not PUBLIC_ID_RE.fullmatch(public_id):
        raise ApiError("Invalid mind identifier", status=400, code="invalid_mind_id")
    return public_id


def _clean_text_field(
    value: Any,
    field_name: str,
    *,
    min_length: int,
    max_length: int,
    multiline: bool = False,
    allow_plain_text_markup: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ApiError(f"{field_name} is required", status=400, code="validation_error")

    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not multiline:
        text = re.sub(r"\s+", " ", text)
    else:
        text = "\n".join(line.rstrip() for line in text.split("\n"))

    if len(text) < min_length or len(text) > max_length:
        raise ApiError(
            f"{field_name} must be {min_length}-{max_length} characters",
            status=400,
            code="validation_error",
        )
    has_invalid_markup = not allow_plain_text_markup and HTML_TAG_RE.search(text)
    if CONTROL_CHARS_RE.search(text) or has_invalid_markup:
        raise ApiError(
            f"{field_name} contains invalid characters",
            status=400,
            code="validation_error",
        )
    return text


def _normalize_starters(raw_value: Any) -> list[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        items = raw_value.splitlines()
    elif isinstance(raw_value, list):
        items = raw_value
    else:
        raise ApiError("Starters must be a list", status=400, code="validation_error")

    starters: list[str] = []
    seen = set()
    for raw_item in items[:6]:
        if not isinstance(raw_item, str):
            continue
        starter = _clean_text_field(
            raw_item,
            "Starter",
            min_length=1,
            max_length=120,
            multiline=False,
        )
        key = starter.casefold()
        if key in seen:
            continue
        seen.add(key)
        starters.append(starter)
    return starters


def _normalize_visibility(value: Any) -> str:
    visibility = str(value or "private").strip().lower()
    if visibility not in MIND_VISIBILITIES:
        raise ApiError("Invalid mind visibility", status=400, code="invalid_visibility")
    return visibility


def _normalize_category(value: Any, *, required: bool = False) -> str:
    category = str(value or "").strip().lower()
    if not category:
        if required:
            raise ApiError(
                "Category is required for Mind store", status=400, code="category_required"
            )
        return "general"
    if category not in MIND_CATEGORY_IDS:
        raise ApiError("Invalid mind category", status=400, code="invalid_category")
    return category


def _generate_public_id() -> str:
    for _ in range(10):
        candidate = f"mind_{secrets.token_urlsafe(12)}"
        if not Mind.query.filter_by(public_id=candidate).first():
            return candidate
    return f"mind_{secrets.token_hex(16)}"


def _can_view_mind(mind: Mind, viewer_id: int | None) -> bool:
    if mind.is_banned and not (viewer_id is not None and mind.user_id == viewer_id):
        return False
    if mind.visibility in {"store", "link"}:
        return True
    return bool(viewer_id is not None and mind.user_id == viewer_id)


def _is_owner(mind: Mind, viewer_id: int | None) -> bool:
    return bool(viewer_id is not None and mind.user_id == viewer_id)


def _get_mind_or_404(public_id: str, viewer_id: int | None = None) -> Mind:
    mind = Mind.query.filter_by(public_id=_validate_public_id(public_id)).first()
    if not mind or not _can_view_mind(mind, viewer_id):
        raise ApiError("Mind not found", status=404, code="not_found")
    return mind


def _pinned_mind_ids(viewer_id: int | None, mind_ids: list[int]) -> set[int]:
    if viewer_id is None or not mind_ids:
        return set()
    pins = MindPin.query.filter(
        MindPin.user_id == viewer_id,
        MindPin.mind_id.in_(mind_ids),
    ).all()
    return {pin.mind_id for pin in pins}


def _serialize_minds(minds: list[Mind], viewer_id: int | None) -> list[dict[str, Any]]:
    pinned_ids = _pinned_mind_ids(viewer_id, [mind.id for mind in minds])
    return [mind.to_dict(viewer_id=viewer_id, pinned=mind.id in pinned_ids) for mind in minds]


def serialize_mind_for_session(mind_id: int | None, viewer_id: int | None) -> dict[str, Any] | None:
    if not mind_id:
        return None

    mind = db.session.get(Mind, mind_id)
    if not mind or not _can_view_mind(mind, viewer_id):
        return None
    if mind.is_banned:
        return None

    pinned = bool(
        viewer_id is not None
        and MindPin.query.filter_by(user_id=viewer_id, mind_id=mind.id).first()
    )
    return mind.to_dict(viewer_id=viewer_id, pinned=pinned)


def _apply_search(query, search_term: str):
    term = (search_term or "").strip()[:80].casefold()
    if not term:
        return query
    like = f"%{term}%"
    return query.filter(
        or_(
            Mind.name.ilike(like),
            Mind.description.ilike(like),
        )
    )


def _apply_category(query, category: str):
    normalized = (category or "").strip().lower()
    if not normalized or normalized == "all":
        return query
    if normalized not in MIND_CATEGORY_IDS:
        raise ApiError("Invalid mind category", status=400, code="invalid_category")
    return query.filter(Mind.category == normalized)


def _payload_to_mind_fields(
    data: dict[str, Any], *, partial: bool = False, owner: int | None = None
) -> dict[str, Any]:
    fields: dict[str, Any] = {}

    if not partial or "name" in data:
        fields["name"] = _clean_text_field(
            data.get("name"),
            "Name",
            min_length=2,
            max_length=80,
        )
    if not partial or "description" in data:
        fields["description"] = _clean_text_field(
            data.get("description"),
            "Description",
            min_length=8,
            max_length=280,
        )
    if not partial or "instructions" in data:
        fields["instructions"] = _clean_text_field(
            data.get("instructions"),
            "Instructions",
            min_length=16,
            max_length=8000,
            multiline=True,
            allow_plain_text_markup=True,
        )
    if not partial or "starters" in data or "conversation_starters" in data:
        fields["starters"] = _normalize_starters(
            data.get("starters", data.get("conversation_starters"))
        )
    if "allow_external_use" in data:
        if type(data["allow_external_use"]) is not bool:
            raise ApiError("invalid_mind_settings", status=400, code="validation_error")
        fields["allow_external_use"] = data["allow_external_use"]
    if "skill_ids" in data:
        ids = data["skill_ids"]
        if ids is not None and (
            not isinstance(ids, list)
            or len(ids) > len(SKILL_BY_ID) + 32
            or any(
                not isinstance(item, str) or (item not in SKILL_BY_ID and not is_skill_reference(item))
                for item in ids
            )
        ):
            raise ApiError("Invalid skill selection", status=400, code="invalid_tool_selection")
        imports = {item for item in ids or [] if is_skill_reference(item)}
        if imports and imports != owned_skill_references(owner, [item[len(SKILL_REF):] for item in imports]):
            raise ApiError("Invalid skill selection", status=400, code="invalid_tool_selection")
        fields["skill_ids"] = list(dict.fromkeys(ids)) if ids is not None else None
    if "custom_skills" in data:
        entries = data["custom_skills"]
        if not isinstance(entries, list) or len(entries) > 6:
            raise ApiError("Invalid skills", status=400, code="validation_error")
        skills = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ApiError("Invalid skill", status=400, code="validation_error")
            name = _clean_text_field(entry.get("name"), "Name", min_length=1, max_length=80)
            instructions = _clean_text_field(
                entry.get("instructions"),
                "Instructions",
                min_length=1,
                max_length=4000,
                multiline=True,
                allow_plain_text_markup=True,
            )
            if any(skill["name"].casefold() == name.casefold() for skill in skills):
                raise ApiError("Duplicate skill", status=400, code="validation_error")
            skills.append({"name": name, "instructions": instructions})
        fields["custom_skills"] = skills

    visibility = (
        _normalize_visibility(data.get("visibility"))
        if not partial or "visibility" in data
        else None
    )
    if visibility:
        fields["visibility"] = visibility

    if not partial or "category" in data or visibility == "store":
        fields["category"] = _normalize_category(
            data.get("category"),
            required=visibility == "store",
        )

    return fields


def _chat_profile(mind: Mind) -> dict[str, Any]:
    return {
        "id": mind.id,
        "public_id": mind.public_id,
        "name": mind.name,
        "description": mind.description,
        "instructions": mind.instructions,
        "category": mind.category,
        "skill_ids": mind.skill_ids,
        "owner_id": mind.user_id,
        "allow_external_use": bool(mind.allow_external_use),
        "custom_skills": mind.custom_skills or [],
    }


def require_portable_mind(profile, viewer_id):
    if profile and profile.get("owner_id") != viewer_id and not profile.get("allow_external_use"):
        raise ApiError("mind_external_disabled", status=403, code="mind_external_disabled")
    return profile


def resolve_mind_context_for_chat(
    public_id: str | None, viewer_id: int | None
) -> dict[str, Any] | None:
    if not public_id:
        return None
    mind = _get_mind_or_404(public_id, viewer_id)
    if mind.is_banned:
        raise ApiError("Mind is unavailable", status=403, code="mind_unavailable")
    return _chat_profile(mind)


def resolve_portable_mind(public_id: str | None, viewer_id: int) -> dict[str, Any] | None:
    return require_portable_mind(resolve_mind_context_for_chat(public_id, viewer_id), viewer_id)


def resolve_bound_mind_context_for_chat(
    mind_id: int | None, viewer_id: int | None
) -> dict[str, Any] | None:
    if not mind_id:
        return None

    mind = db.session.get(Mind, mind_id)
    if not mind or not _can_view_mind(mind, viewer_id):
        return None
    if mind.is_banned:
        return None

    return _chat_profile(mind)


def get_mind_for_session_binding(public_id: str | None, viewer_id: int | None) -> Mind | None:
    if not public_id:
        return None
    mind = _get_mind_or_404(public_id, viewer_id)
    if mind.is_banned:
        raise ApiError("Mind is unavailable", status=403, code="mind_unavailable")
    return mind
