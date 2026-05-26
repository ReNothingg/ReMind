from __future__ import annotations

import re
import secrets
from datetime import datetime
from typing import Any

from flask import request, session
from sqlalchemy import or_

from routes.api_errors import ApiError, api_error_boundary, require_authenticated_user_id
from utils.auth import Mind, MindPin, UserChatHistory, db
from utils.rate_limiting import api_limiter, rate_limit
from utils.responses import make_ok

PUBLIC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,128}$")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
HTML_TAG_RE = re.compile(r"<[^>]+>")
UNSAFE_HTML_RE = re.compile(
    r"</?\s*(?:script|style|iframe|object|embed|svg|math|link|meta|base|form|"
    r"input|button|textarea|select|option|video|audio|source|track|img|image|"
    r"foreignobject)\b"
    r"|<[^>]+\s(?:on[a-z]+\s*=|(?:href|src|xlink:href)\s*=\s*['\"]?\s*"
    r"(?:javascript:|data:text/html))",
    re.IGNORECASE,
)

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


def _viewer_id() -> int | None:
    raw = session.get("user_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


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
    allow_markup_examples: bool = False,
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
    has_invalid_markup = (
        UNSAFE_HTML_RE.search(text)
        if allow_markup_examples
        else HTML_TAG_RE.search(text)
    )
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
            raise ApiError("Category is required for Mind store", status=400, code="category_required")
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


def _payload_to_mind_fields(data: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
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
            allow_markup_examples=True,
        )
    if not partial or "starters" in data or "conversation_starters" in data:
        fields["starters"] = _normalize_starters(
            data.get("starters", data.get("conversation_starters"))
        )

    visibility = _normalize_visibility(data.get("visibility")) if not partial or "visibility" in data else None
    if visibility:
        fields["visibility"] = visibility

    if not partial or "category" in data or visibility == "store":
        fields["category"] = _normalize_category(
            data.get("category"),
            required=visibility == "store",
        )

    return fields


def resolve_mind_context_for_chat(public_id: str | None, viewer_id: int | None) -> dict[str, Any] | None:
    if not public_id:
        return None

    mind = _get_mind_or_404(public_id, viewer_id)
    if mind.is_banned:
        raise ApiError("Mind is unavailable", status=403, code="mind_unavailable")
    return {
        "id": mind.id,
        "public_id": mind.public_id,
        "name": mind.name,
        "description": mind.description,
        "instructions": mind.instructions,
        "category": mind.category,
    }


def resolve_bound_mind_context_for_chat(mind_id: int | None, viewer_id: int | None) -> dict[str, Any] | None:
    if not mind_id:
        return None

    mind = db.session.get(Mind, mind_id)
    if not mind or not _can_view_mind(mind, viewer_id):
        return None
    if mind.is_banned:
        return None

    return {
        "id": mind.id,
        "public_id": mind.public_id,
        "name": mind.name,
        "description": mind.description,
        "instructions": mind.instructions,
        "category": mind.category,
    }


def get_mind_for_session_binding(public_id: str | None, viewer_id: int | None) -> Mind | None:
    if not public_id:
        return None
    mind = _get_mind_or_404(public_id, viewer_id)
    if mind.is_banned:
        raise ApiError("Mind is unavailable", status=403, code="mind_unavailable")
    return mind


def register_mind_routes(api_bp):
    @api_bp.route("/api/minds/categories", methods=["GET"])
    @api_error_boundary("mind_categories_failed")
    def list_mind_categories():
        return make_ok({"categories": MIND_CATEGORIES})

    @api_bp.route("/api/minds", methods=["GET"])
    @api_error_boundary("mind_list_failed")
    def list_minds():
        viewer_id = _viewer_id()
        mine = (request.args.get("mine", "") or "").lower() in {"1", "true", "yes"}

        if mine:
            viewer_id = require_authenticated_user_id()
            query = Mind.query.filter(Mind.user_id == viewer_id)
        else:
            query = Mind.query.filter(
                Mind.visibility == "store",
                Mind.is_system.is_(False),
                Mind.is_banned.is_(False),
            )

        query = _apply_category(query, request.args.get("category", ""))
        query = _apply_search(query, request.args.get("q", ""))

        if mine:
            query = query.order_by(Mind.updated_at.desc(), Mind.created_at.desc())
        else:
            query = query.order_by(
                Mind.is_featured.desc(),
                Mind.is_verified.desc(),
                Mind.updated_at.desc(),
                Mind.created_at.desc(),
            )

        limit = max(1, min(request.args.get("limit", default=60, type=int) or 60, 100))
        minds = query.limit(limit).all()
        return make_ok({"minds": _serialize_minds(minds, viewer_id), "categories": MIND_CATEGORIES})

    @api_bp.route("/api/minds/pinned", methods=["GET"])
    @api_error_boundary("mind_pins_failed")
    def list_pinned_minds():
        viewer_id = require_authenticated_user_id()
        rows = (
            db.session.query(Mind, MindPin.created_at)
            .join(MindPin, MindPin.mind_id == Mind.id)
            .filter(MindPin.user_id == viewer_id)
            .filter(Mind.is_banned.is_(False))
            .order_by(MindPin.created_at.asc())
            .all()
        )
        minds = [mind for mind, _created_at in rows if _can_view_mind(mind, viewer_id)]
        return make_ok({"minds": _serialize_minds(minds, viewer_id)})

    @api_bp.route("/api/minds", methods=["POST"])
    @rate_limit(api_limiter, "Too many mind changes. Please wait.")
    @api_error_boundary("mind_create_failed")
    def create_mind():
        viewer_id = require_authenticated_user_id()
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            raise ApiError("Invalid JSON payload", status=400, code="invalid_json")

        fields = _payload_to_mind_fields(data)
        mind = Mind(
            public_id=_generate_public_id(),
            user_id=viewer_id,
            name=fields["name"],
            description=fields["description"],
            instructions=fields["instructions"],
            category=fields["category"],
            visibility=fields["visibility"],
            is_verified=False,
            is_system=False,
        )
        mind.set_starters(fields["starters"])
        db.session.add(mind)
        db.session.commit()
        return make_ok({"mind": mind.to_dict(viewer_id=viewer_id)}, status=201)

    @api_bp.route("/api/minds/<public_id>", methods=["GET"])
    @api_error_boundary("mind_get_failed")
    def get_mind(public_id):
        viewer_id = _viewer_id()
        mind = _get_mind_or_404(public_id, viewer_id)
        pinned = bool(
            viewer_id is not None
            and MindPin.query.filter_by(user_id=viewer_id, mind_id=mind.id).first()
        )
        return make_ok({"mind": mind.to_dict(viewer_id=viewer_id, pinned=pinned)})

    @api_bp.route("/api/minds/<public_id>", methods=["PUT"])
    @rate_limit(api_limiter, "Too many mind changes. Please wait.")
    @api_error_boundary("mind_update_failed")
    def update_mind(public_id):
        viewer_id = require_authenticated_user_id()
        mind = _get_mind_or_404(public_id, viewer_id)
        if not _is_owner(mind, viewer_id) or mind.is_system:
            raise ApiError("Access denied", status=403, code="access_denied")

        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            raise ApiError("Invalid JSON payload", status=400, code="invalid_json")

        fields = _payload_to_mind_fields(data, partial=True)
        for key in ("name", "description", "instructions", "category", "visibility"):
            if key in fields:
                setattr(mind, key, fields[key])
        if "starters" in fields:
            mind.set_starters(fields["starters"])
        mind.updated_at = datetime.utcnow()
        db.session.commit()
        pinned = bool(MindPin.query.filter_by(user_id=viewer_id, mind_id=mind.id).first())
        return make_ok({"mind": mind.to_dict(viewer_id=viewer_id, pinned=pinned)})

    @api_bp.route("/api/minds/<public_id>", methods=["DELETE"])
    @rate_limit(api_limiter, "Too many mind changes. Please wait.")
    @api_error_boundary("mind_delete_failed")
    def delete_mind(public_id):
        viewer_id = require_authenticated_user_id()
        mind = _get_mind_or_404(public_id, viewer_id)
        if not _is_owner(mind, viewer_id) or mind.is_system:
            raise ApiError("Access denied", status=403, code="access_denied")

        MindPin.query.filter_by(mind_id=mind.id).delete()
        UserChatHistory.query.filter_by(mind_id=mind.id).update({"mind_id": None})
        db.session.delete(mind)
        db.session.commit()
        return "", 204

    @api_bp.route("/api/minds/<public_id>/pin", methods=["POST"])
    @rate_limit(api_limiter, "Too many mind changes. Please wait.")
    @api_error_boundary("mind_pin_failed")
    def pin_mind(public_id):
        viewer_id = require_authenticated_user_id()
        mind = _get_mind_or_404(public_id, viewer_id)
        existing = MindPin.query.filter_by(user_id=viewer_id, mind_id=mind.id).first()
        if not existing:
            db.session.add(MindPin(user_id=viewer_id, mind_id=mind.id))
            db.session.commit()
        return make_ok({"mind": mind.to_dict(viewer_id=viewer_id, pinned=True)})

    @api_bp.route("/api/minds/<public_id>/pin", methods=["DELETE"])
    @rate_limit(api_limiter, "Too many mind changes. Please wait.")
    @api_error_boundary("mind_unpin_failed")
    def unpin_mind(public_id):
        viewer_id = require_authenticated_user_id()
        mind = _get_mind_or_404(public_id, viewer_id)
        MindPin.query.filter_by(user_id=viewer_id, mind_id=mind.id).delete()
        db.session.commit()
        return make_ok({"mind": mind.to_dict(viewer_id=viewer_id, pinned=False)})
