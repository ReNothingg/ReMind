from __future__ import annotations

import os
import platform
import sys
import time
from datetime import datetime, timedelta
from typing import Any

from flask import current_app, request
from sqlalchemy import func, or_, text

from routes.api_errors import ApiError, api_error_boundary, require_authenticated_user_id
from utils.auth import (
    Mind,
    MindPin,
    User,
    UserChatHistory,
    db,
    is_account_disabled,
    is_admin_user,
    is_super_admin_user,
)
from utils.responses import make_ok

MAX_PAGE_SIZE = 100
ADMIN_REASON_MAX_LENGTH = 280


def _current_admin_user() -> User:
    user_id = require_authenticated_user_id()
    user = db.session.get(User, user_id)
    if not user or is_account_disabled(user) or not is_admin_user(user):
        raise ApiError("Admin access required", status=403, code="admin_required")
    return user


def _current_super_admin_user() -> User:
    user = _current_admin_user()
    if not is_super_admin_user(user):
        raise ApiError("Root admin access required", status=403, code="root_admin_required")
    return user


def _request_json() -> dict[str, Any]:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        raise ApiError("Invalid JSON payload", status=400, code="invalid_json")
    return payload


def _clean_reason(value: Any) -> str | None:
    if value is None:
        return None
    reason = str(value).strip()
    if not reason:
        return None
    if len(reason) > ADMIN_REASON_MAX_LENGTH:
        raise ApiError("Reason is too long", status=400, code="validation_error")
    return reason


def _bool_from_payload(payload: dict[str, Any], key: str) -> bool | None:
    if key not in payload:
        return None
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    raise ApiError(f"{key} must be boolean", status=400, code="validation_error")


def _pagination() -> tuple[int, int]:
    page = max(1, request.args.get("page", default=1, type=int) or 1)
    page_size = max(
        1,
        min(request.args.get("page_size", default=25, type=int) or 25, MAX_PAGE_SIZE),
    )
    return page, page_size


def _serialize_user_for_admin(
    user: User,
    *,
    chat_counts: dict[int, int] | None = None,
    mind_counts: dict[int, int] | None = None,
) -> dict[str, Any]:
    user_id = int(user.id)
    return {
        "id": user_id,
        "username": user.username,
        "name": user.name,
        "email": user.email,
        "is_confirmed": bool(user.is_confirmed),
        "is_admin": is_admin_user(user),
        "is_super_admin": is_super_admin_user(user),
        "is_banned": bool(user.is_banned),
        "is_blocked": bool(user.is_blocked),
        "moderation_reason": user.moderation_reason,
        "oauth_provider": user.oauth_provider,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "mind_count": int((mind_counts or {}).get(user_id, 0)),
        "chat_count": int((chat_counts or {}).get(user_id, 0)),
    }


def _serialize_mind_for_admin(mind: Mind) -> dict[str, Any]:
    owner = db.session.get(User, mind.user_id) if mind.user_id else None
    return {
        "id": mind.id,
        "public_id": mind.public_id,
        "name": mind.name,
        "description": mind.description,
        "category": mind.category,
        "visibility": mind.visibility,
        "is_verified": bool(mind.is_verified),
        "is_featured": bool(mind.is_featured),
        "is_banned": bool(mind.is_banned),
        "is_system": bool(mind.is_system),
        "moderation_reason": mind.moderation_reason,
        "owner": (
            {
                "id": owner.id,
                "username": owner.username,
                "email": owner.email,
            }
            if owner
            else None
        ),
        "created_at": mind.created_at.isoformat() if mind.created_at else None,
        "updated_at": mind.updated_at.isoformat() if mind.updated_at else None,
    }


def _load_group_counts(model, user_ids: list[int]) -> dict[int, int]:
    if not user_ids:
        return {}
    rows = (
        db.session.query(model.user_id, func.count(model.id))
        .filter(model.user_id.in_(user_ids))
        .group_by(model.user_id)
        .all()
    )
    return {int(user_id): int(count) for user_id, count in rows}


def _storage_status() -> list[dict[str, Any]]:
    items = []
    for cfg_key in ("UPLOAD_FOLDER", "CHATS_FOLDER", "CREATE_IMAGE_FOLDER"):
        folder = current_app.config.get(cfg_key)
        path = str(folder) if folder else ""
        items.append(
            {
                "key": cfg_key.lower(),
                "path": path,
                "exists": bool(path and os.path.isdir(path)),
                "writable": bool(path and os.path.isdir(path) and os.access(path, os.W_OK)),
            }
        )
    return items


def _server_snapshot() -> dict[str, Any]:
    now_mono = time.perf_counter()
    started_mono = current_app.config.get("APP_STARTED_MONOTONIC", now_mono)
    started_at = current_app.config.get("APP_STARTED_AT")

    database = {"status": "ok"}
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        database = {"status": "fail"}

    redis_status = {"status": "not_configured"}
    session_redis = current_app.config.get("SESSION_REDIS")
    if session_redis is not None:
        try:
            session_redis.ping()
            redis_status = {"status": "ok"}
        except Exception:
            redis_status = {"status": "degraded"}

    load_average = None
    if hasattr(os, "getloadavg"):
        try:
            load_average = list(os.getloadavg())
        except OSError:
            load_average = None

    memory = {"max_rss_bytes": None}
    try:
        import resource

        raw_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_bytes = raw_rss if sys.platform == "darwin" else raw_rss * 1024
        memory = {"max_rss_bytes": int(rss_bytes)}
    except Exception:
        pass

    return {
        "status": "ok" if database["status"] == "ok" else "degraded",
        "uptime_seconds": round(max(0.0, now_mono - started_mono), 3),
        "started_at": started_at.isoformat() if hasattr(started_at, "isoformat") else None,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "process": {
            "pid": os.getpid(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "memory": memory,
            "load_average": load_average,
        },
        "components": {
            "database": database,
            "redis": redis_status,
            "storage": _storage_status(),
        },
    }


def _dashboard_stats() -> dict[str, Any]:
    since = datetime.utcnow() - timedelta(hours=24)
    return {
        "users": {
            "total": User.query.count(),
            "confirmed": User.query.filter(User.is_confirmed.is_(True)).count(),
            "admins": User.query.filter(or_(User.is_admin.is_(True), User.id == 1)).count(),
            "banned": User.query.filter(User.is_banned.is_(True)).count(),
            "blocked": User.query.filter(User.is_blocked.is_(True)).count(),
            "new_24h": User.query.filter(User.created_at >= since).count(),
        },
        "minds": {
            "total": Mind.query.count(),
            "store": Mind.query.filter(Mind.visibility == "store").count(),
            "featured": Mind.query.filter(Mind.is_featured.is_(True)).count(),
            "banned": Mind.query.filter(Mind.is_banned.is_(True)).count(),
            "verified": Mind.query.filter(Mind.is_verified.is_(True)).count(),
            "new_24h": Mind.query.filter(Mind.created_at >= since).count(),
        },
        "sessions": {
            "total": UserChatHistory.query.count(),
            "updated_24h": UserChatHistory.query.filter(UserChatHistory.updated_at >= since).count(),
        },
    }


def register_admin_routes(api_bp):
    @api_bp.route("/api/admin/overview", methods=["GET"])
    @api_error_boundary("admin_overview_failed")
    def admin_overview():
        admin = _current_admin_user()
        return make_ok(
            {
                "admin": {
                    "id": admin.id,
                    "username": admin.username,
                    "is_super_admin": is_super_admin_user(admin),
                },
                "stats": _dashboard_stats(),
                "server": _server_snapshot(),
            }
        )

    @api_bp.route("/api/admin/users", methods=["GET"])
    @api_error_boundary("admin_users_failed")
    def admin_users():
        _current_admin_user()
        page, page_size = _pagination()
        status = (request.args.get("status") or "all").strip().lower()
        search = (request.args.get("q") or "").strip()[:100]

        query = User.query
        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(User.username.ilike(like), User.name.ilike(like), User.email.ilike(like))
            )

        if status == "admin":
            query = query.filter(or_(User.is_admin.is_(True), User.id == 1))
        elif status == "banned":
            query = query.filter(User.is_banned.is_(True))
        elif status == "blocked":
            query = query.filter(User.is_blocked.is_(True))
        elif status == "unconfirmed":
            query = query.filter(User.is_confirmed.is_(False))
        elif status == "active":
            query = query.filter(User.is_banned.is_(False), User.is_blocked.is_(False))
        elif status != "all":
            raise ApiError("Invalid user status filter", status=400, code="invalid_status")

        total = query.count()
        users = (
            query.order_by(User.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        user_ids = [int(user.id) for user in users]
        mind_counts = _load_group_counts(Mind, user_ids)
        chat_counts = _load_group_counts(UserChatHistory, user_ids)
        return make_ok(
            {
                "users": [
                    _serialize_user_for_admin(
                        user,
                        mind_counts=mind_counts,
                        chat_counts=chat_counts,
                    )
                    for user in users
                ],
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": total,
                },
            }
        )

    @api_bp.route("/api/admin/users/<int:user_id>", methods=["PATCH"])
    @api_error_boundary("admin_user_update_failed")
    def admin_update_user(user_id: int):
        admin = _current_admin_user()
        target = db.session.get(User, user_id)
        if not target:
            raise ApiError("User not found", status=404, code="not_found")
        if is_super_admin_user(target):
            raise ApiError("Root admin cannot be restricted", status=403, code="root_admin_protected")
        if target.id == admin.id:
            raise ApiError("You cannot restrict your own account", status=400, code="self_update_denied")
        if is_admin_user(target) and not is_super_admin_user(admin):
            raise ApiError("Only root admin can restrict administrators", status=403, code="root_admin_required")

        payload = _request_json()
        is_banned = _bool_from_payload(payload, "is_banned")
        is_blocked = _bool_from_payload(payload, "is_blocked")
        if is_banned is not None:
            target.is_banned = is_banned
        if is_blocked is not None:
            target.is_blocked = is_blocked
        if "moderation_reason" in payload:
            target.moderation_reason = _clean_reason(payload.get("moderation_reason"))

        db.session.commit()
        return make_ok({"user": _serialize_user_for_admin(target)})

    @api_bp.route("/api/admin/users/<int:user_id>/admin", methods=["POST"])
    @api_error_boundary("admin_user_role_failed")
    def admin_update_user_role(user_id: int):
        _current_super_admin_user()
        target = db.session.get(User, user_id)
        if not target:
            raise ApiError("User not found", status=404, code="not_found")
        if is_super_admin_user(target):
            return make_ok({"user": _serialize_user_for_admin(target)})

        payload = _request_json()
        is_admin = _bool_from_payload(payload, "is_admin")
        if is_admin is None:
            raise ApiError("is_admin is required", status=400, code="validation_error")
        if is_admin and is_account_disabled(target):
            raise ApiError("Disabled account cannot become admin", status=400, code="account_disabled")

        target.is_admin = is_admin
        db.session.commit()
        return make_ok({"user": _serialize_user_for_admin(target)})

    @api_bp.route("/api/admin/minds", methods=["GET"])
    @api_error_boundary("admin_minds_failed")
    def admin_minds():
        _current_admin_user()
        page, page_size = _pagination()
        status = (request.args.get("status") or "all").strip().lower()
        search = (request.args.get("q") or "").strip()[:100]

        query = Mind.query.outerjoin(User, Mind.user_id == User.id)
        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(
                    Mind.name.ilike(like),
                    Mind.description.ilike(like),
                    Mind.public_id.ilike(like),
                    User.username.ilike(like),
                    User.email.ilike(like),
                )
            )

        if status == "featured":
            query = query.filter(Mind.is_featured.is_(True))
        elif status == "banned":
            query = query.filter(Mind.is_banned.is_(True))
        elif status == "verified":
            query = query.filter(Mind.is_verified.is_(True))
        elif status in {"store", "private", "link"}:
            query = query.filter(Mind.visibility == status)
        elif status != "all":
            raise ApiError("Invalid mind status filter", status=400, code="invalid_status")

        total = query.count()
        minds = (
            query.order_by(Mind.is_featured.desc(), Mind.updated_at.desc(), Mind.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return make_ok(
            {
                "minds": [_serialize_mind_for_admin(mind) for mind in minds],
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": total,
                },
            }
        )

    @api_bp.route("/api/admin/minds/<public_id>", methods=["PATCH"])
    @api_error_boundary("admin_mind_update_failed")
    def admin_update_mind(public_id: str):
        _current_admin_user()
        mind = Mind.query.filter_by(public_id=public_id).first()
        if not mind:
            raise ApiError("Mind not found", status=404, code="not_found")

        payload = _request_json()
        is_featured = _bool_from_payload(payload, "is_featured")
        is_banned = _bool_from_payload(payload, "is_banned")
        is_verified = _bool_from_payload(payload, "is_verified")

        if is_banned is not None:
            mind.is_banned = is_banned
            if is_banned:
                mind.is_featured = False
                MindPin.query.filter_by(mind_id=mind.id).delete()
                UserChatHistory.query.filter_by(mind_id=mind.id).update({"mind_id": None})

        if is_featured is not None:
            if is_featured and mind.visibility != "store":
                raise ApiError(
                    "Only store minds can be featured",
                    status=400,
                    code="mind_not_public",
                )
            if is_featured and mind.is_banned:
                raise ApiError(
                    "Banned mind cannot be featured",
                    status=400,
                    code="mind_unavailable",
                )
            mind.is_featured = is_featured

        if is_verified is not None:
            mind.is_verified = is_verified

        if "moderation_reason" in payload:
            mind.moderation_reason = _clean_reason(payload.get("moderation_reason"))

        mind.updated_at = datetime.utcnow()
        db.session.commit()
        return make_ok({"mind": _serialize_mind_for_admin(mind)})
