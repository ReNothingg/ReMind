from __future__ import annotations

from datetime import datetime

from flask import request, session

from backend.db.models import Mind, MindPin, UserChatHistory, db
from backend.errors import ApiError
from backend.responses import make_ok
from backend.routes.api_errors import api_error_boundary, require_authenticated_user_id
from backend.security.rate_limiting import api_limiter, rate_limit
from backend.services.minds import (
    MIND_CATEGORIES,
    _apply_category,
    _apply_search,
    _can_view_mind,
    _generate_public_id,
    _get_mind_or_404,
    _is_owner,
    _payload_to_mind_fields,
    _serialize_minds,
)


def _viewer_id() -> int | None:
    raw = session.get("user_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


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

        page = max(1, request.args.get("page", default=1, type=int) or 1)
        requested_page_size = request.args.get(
            "page_size",
            default=request.args.get("limit", default=60, type=int),
            type=int,
        )
        page_size = max(1, min(requested_page_size or 60, 100))
        total = query.count()
        minds = query.offset((page - 1) * page_size).limit(page_size).all()
        return make_ok(
            {
                "minds": _serialize_minds(minds, viewer_id),
                "categories": MIND_CATEGORIES,
                "page": page,
                "page_size": page_size,
                "total": total,
                "has_more": page * page_size < total,
            }
        )

    @api_bp.route("/api/minds/pinned", methods=["GET"])
    @api_error_boundary("mind_pins_failed")
    def list_pinned_minds():
        viewer_id = require_authenticated_user_id()
        page = max(1, request.args.get("page", default=1, type=int) or 1)
        page_size = max(
            1,
            min(request.args.get("page_size", default=60, type=int) or 60, 100),
        )
        query = (
            db.session.query(Mind, MindPin.created_at)
            .join(MindPin, MindPin.mind_id == Mind.id)
            .filter(MindPin.user_id == viewer_id)
            .filter(Mind.is_banned.is_(False))
            .order_by(MindPin.created_at.asc())
        )
        total = query.count()
        rows = query.offset((page - 1) * page_size).limit(page_size).all()
        minds = [mind for mind, _created_at in rows if _can_view_mind(mind, viewer_id)]
        return make_ok(
            {
                "minds": _serialize_minds(minds, viewer_id),
                "page": page,
                "page_size": page_size,
                "total": total,
                "has_more": page * page_size < total,
            }
        )

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
