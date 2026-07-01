from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from routes.api_errors import ApiError
from utils.auth import AIResponseFeedback, UserChatHistory, UserSettings, db
from utils.input_validation import InputValidator, ValidationError
from utils.privacy import SERVICE_IMPROVEMENT_SETTING_KEY

FEEDBACK_RATINGS = {"like", "dislike"}
FEEDBACK_REASON_CODES = {
    "incorrect",
    "unsafe",
    "not_helpful",
    "too_long",
    "missing_context",
    "other",
}
MAX_FEEDBACK_COMMENT_LENGTH = 1200
MAX_FEEDBACK_TEXT_LENGTH = 32000


def _clean_optional_text(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > max_length:
        text = text[:max_length]
    return text


def _validate_comment(value: Any) -> str | None:
    comment = _clean_optional_text(value, MAX_FEEDBACK_COMMENT_LENGTH)
    if not comment:
        return None
    try:
        return InputValidator.validate_text(
            comment,
            min_length=1,
            max_length=MAX_FEEDBACK_COMMENT_LENGTH,
        )
    except ValidationError as exc:
        raise ApiError(str(exc), status=400, code="validation_error") from exc


def _normalize_reason_codes(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ApiError("reason_codes must be an array", status=400, code="validation_error")
    normalized = []
    for item in value[:8]:
        code = str(item).strip().lower()
        if code in FEEDBACK_REASON_CODES and code not in normalized:
            normalized.append(code)
    return normalized


def _service_improvement_opt_in(user_id: int) -> bool:
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    settings_data = settings.get_settings() if settings else {}
    return bool(settings_data.get(SERVICE_IMPROVEMENT_SETTING_KEY, False))


def _owned_chat(user_id: int, session_id: str) -> UserChatHistory:
    chat = UserChatHistory.query.filter_by(user_id=user_id, session_id=session_id).first()
    if not chat:
        raise ApiError("Session not found", status=404, code="not_found")
    return chat


def _matching_training_pair(
    chat: UserChatHistory, response_text: str
) -> tuple[str | None, str | None]:
    messages = chat.get_messages()
    if not response_text:
        return None, None

    response_index = -1
    matched_response = None
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").lower() not in {"model", "assistant"}:
            continue
        text = "\n".join(
            str(part.get("text") or "")
            for part in message.get("parts") or []
            if isinstance(part, dict) and part.get("text")
        ).strip()
        if text == response_text:
            response_index = index
            matched_response = _clean_optional_text(text, MAX_FEEDBACK_TEXT_LENGTH)
            break
    if response_index < 0:
        return None, None

    search_range = range(response_index - 1, -1, -1)
    for index in search_range:
        message = messages[index]
        if not isinstance(message, dict) or str(message.get("role") or "").lower() != "user":
            continue
        prompt = "\n".join(
            str(part.get("text") or "")
            for part in message.get("parts") or []
            if isinstance(part, dict) and part.get("text")
        ).strip()
        if prompt:
            return _clean_optional_text(prompt, MAX_FEEDBACK_TEXT_LENGTH), matched_response
    return None, matched_response


def _response_hash(response_text: str, message_client_id: str | None) -> str:
    hash_source = response_text or message_client_id or ""
    if not hash_source:
        raise ApiError("response_text is required", status=400, code="validation_error")
    return hashlib.sha256(hash_source.encode("utf-8")).hexdigest()


def save_ai_response_feedback(user_id: int, payload: dict[str, Any]) -> AIResponseFeedback:
    rating = str(payload.get("rating") or "").strip().lower()
    if rating not in FEEDBACK_RATINGS:
        raise ApiError("rating must be like or dislike", status=400, code="validation_error")

    session_id = str(payload.get("session_id") or "").strip()
    if not session_id or len(session_id) > 100:
        raise ApiError("session_id is required", status=400, code="validation_error")
    chat = _owned_chat(user_id, session_id)

    response_text = (
        _clean_optional_text(payload.get("response_text"), MAX_FEEDBACK_TEXT_LENGTH) or ""
    )
    message_client_id = _clean_optional_text(payload.get("message_client_id"), 120)
    response_hash = _response_hash(response_text, message_client_id)
    reason_codes = _normalize_reason_codes(payload.get("reason_codes"))
    comment = _validate_comment(payload.get("comment"))
    opt_in = _service_improvement_opt_in(user_id)

    feedback = AIResponseFeedback.query.filter_by(
        user_id=user_id,
        session_id=session_id,
        response_hash=response_hash,
    ).first()
    if not feedback:
        feedback = AIResponseFeedback(
            user_id=user_id,
            session_id=session_id,
            response_hash=response_hash,
        )
        db.session.add(feedback)

    feedback.rating = rating
    feedback.message_client_id = message_client_id
    feedback.set_reason_codes(reason_codes if rating == "dislike" else [])
    feedback.comment = comment if rating == "dislike" else None
    feedback.service_improvement_opt_in = opt_in
    prompt_text, matched_response_text = (
        _matching_training_pair(chat, response_text) if opt_in else (None, None)
    )
    feedback.prompt_text = prompt_text
    feedback.response_text = matched_response_text
    feedback.created_at = datetime.utcnow()
    db.session.commit()
    return feedback


def feedback_rating_summary() -> dict[str, Any]:
    total = AIResponseFeedback.query.count()
    likes = AIResponseFeedback.query.filter_by(rating="like").count()
    dislikes = AIResponseFeedback.query.filter_by(rating="dislike").count()
    if total <= 0:
        like_percent = 0.0
        dislike_percent = 0.0
    else:
        like_percent = round((likes / total) * 100, 2)
        dislike_percent = round((dislikes / total) * 100, 2)
    return {
        "total": int(total),
        "likes": int(likes),
        "dislikes": int(dislikes),
        "like_percent": like_percent,
        "dislike_percent": dislike_percent,
    }


def export_feedback_dataset(path: str) -> int:
    rows = AIResponseFeedback.query.order_by(AIResponseFeedback.id.asc()).all()
    with open(path, "w", encoding="utf-8") as file_obj:
        for row in rows:
            file_obj.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")
    return len(rows)
