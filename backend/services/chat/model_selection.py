from __future__ import annotations

import re

from sqlalchemy.exc import IntegrityError

from backend.db.models import ChatModelSelection, UserChatHistory, db
from backend.errors import ApiError
from backend.services.agent_models import EFFORTS
from backend.services.model_access import can_user_access_model, list_accessible_models

SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")
SPEEDS = ("standard", "fast", "ultrafast")


def selection_view(chat):
    if chat is None or chat.source != "web":
        return {"next": None, "lastUsed": None}
    state = db.session.get(ChatModelSelection, chat.id)
    if not state:
        return {"next": None, "lastUsed": None}
    return {"next": state.pending or state.last_used, "lastUsed": state.last_used}


def _selection_chat(owner, session_id, *, lock=False):
    if not owner or not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
        return None
    query = UserChatHistory.query.filter_by(user_id=owner, session_id=session_id, source="web")
    return query.with_for_update().populate_existing().one_or_none() if lock else query.one_or_none()


def read_model_selection(owner, session_id):
    chat = _selection_chat(owner, session_id)
    if not chat:
        raise ApiError("not_found", status=404, code="not_found")
    return selection_view(chat)


def next_model_selection(owner, session_id):
    return selection_view(_selection_chat(owner, session_id))["next"]


def _normalize(model, data):
    spec = {"model": model}
    level = data.get("thinkingLevel") or data.get("thinking_level")
    if level in EFFORTS:
        spec["thinkingLevel"] = level
    speed = data.get("serviceTier")
    if speed in SPEEDS and speed != "standard":
        spec["serviceTier"] = speed
    return spec


def used_model_selection(model, data):
    if model in ("demo_image", "mindart") or data.get("_automation") is True:
        return None
    order = data.get("_selection_request_order")
    if type(order) is not int:
        return None
    return _normalize(model, data), order


def save_model_selection(owner, session_id, body):
    if not _selection_chat(owner, session_id):
        raise ApiError("not_found", status=404, code="not_found")
    error = "model_selection_invalid"
    if (
        not isinstance(body, dict)
        or set(body) - {"model", "thinkingLevel", "serviceTier", "expected_user_id"}
        or not isinstance(model := body.get("model"), str)
        or not model
        or len(model) > 240
        or model in ("demo_image", "mindart")
        or ("thinkingLevel" in body and body["thinkingLevel"] not in EFFORTS)
        or ("serviceTier" in body and body["serviceTier"] not in SPEEDS)
    ):
        raise ApiError(error, status=400, code=error)
    if "expected_user_id" in body and (
        type(body["expected_user_id"]) is not int or body["expected_user_id"] != owner
    ):
        raise ApiError("account_changed", status=409, code="account_changed")
    if not can_user_access_model(model, owner):
        raise ApiError("model_access_denied", status=403, code="model_access_denied")
    spec = _normalize(model, body)
    if len(spec) > 1:
        catalog = next((item for item in list_accessible_models(owner) if item["id"] == model), {})
        if "thinkingLevel" in spec and spec["thinkingLevel"] not in catalog.get("thinkingLevels", []):
            raise ApiError(error, status=400, code=error)
        if "serviceTier" in spec and spec["serviceTier"] not in catalog.get("serviceTiers", []):
            raise ApiError("model_speed_unavailable", status=400, code="model_speed_unavailable")
    for _ in range(2):
        chat = _selection_chat(owner, session_id, lock=True)
        if not chat:
            raise ApiError("not_found", status=404, code="not_found")
        state = db.session.get(ChatModelSelection, chat.id, populate_existing=True)
        if state is None:
            state = ChatModelSelection(chat_id=chat.id)
            db.session.add(state)
        state.pending = spec
        result = {"next": spec, "lastUsed": state.last_used}
        try:
            db.session.commit()
            return result
        except IntegrityError:
            db.session.rollback()
    raise ApiError("model_selection_conflict", status=409, code="model_selection_conflict")


def record_model_selection(chat, selection):
    if selection is None or chat.source != "web":
        return
    spec, request_order = selection
    state = db.session.get(ChatModelSelection, chat.id, populate_existing=True)
    if state is None:
        state = ChatModelSelection(chat_id=chat.id)
        db.session.add(state)
    if state.last_request_order is not None and request_order < state.last_request_order:
        return
    state.last_used = spec
    state.last_request_order = request_order
    if state.pending == spec:
        state.pending = None
