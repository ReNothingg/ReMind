from __future__ import annotations

import io
import re
from pathlib import Path

from flask import (
    Response,
    current_app,
    request,
    send_file,
    send_from_directory,
    session,
)
from werkzeug.utils import secure_filename

from backend.errors import ApiError
from backend.responses import make_ok
from backend.routes.api_errors import api_error_boundary
from backend.routes.chat_request import process_request_data
from backend.security.input_validation import InputValidator, ValidationError
from backend.security.rate_limiting import RateLimiter, anonymous_rate_limit, rate_limit
from backend.security.url_security import UnsafeUrlError, validate_public_http_url
from backend.services.chat.attachments import find_upload_reference
from backend.services.chat.cancellation import generation_scope, request_cancellation
from backend.services.chat.generation import ChatImage, generate_chat
from backend.services.chat.streaming import ChatStream
from backend.services.translation import TranslationUnavailableError, translate_text
from backend.services.voice import TTS_MAX_CHARS, synthesize_text_segments

PUBLIC_UPLOAD_NAME_RE = re.compile(r"^[a-f0-9]{32}(?:\.[a-z0-9]{1,12})$")


translation_limiter = RateLimiter(max_requests=60, time_window=3600, namespace="translation")
cancellation_limiter = RateLimiter(max_requests=120, time_window=60, namespace="chat_cancel")


anonymous_translation_limiter = RateLimiter(
    max_requests=10, time_window=3600, namespace="anonymous_translation"
)


synthesize_limiter = RateLimiter(max_requests=30, time_window=3600, namespace="synthesize")


anonymous_synthesize_limiter = RateLimiter(
    max_requests=5, time_window=3600, namespace="anonymous_synthesize"
)


ANONYMOUS_TRANSLATION_MAX_CHARS = 2000


def _resolve_db_user_id() -> int | None:
    raw_user_id = session.get("user_id")
    if raw_user_id is None:
        return None
    try:
        return int(raw_user_id)
    except (TypeError, ValueError):
        return None


def register_chat_routes(api_bp):
    @api_bp.post("/chat/cancel")
    @anonymous_rate_limit(cancellation_limiter)
    @rate_limit(cancellation_limiter)
    @api_error_boundary("chat_cancel_unavailable")
    def cancel_chat():
        raw = request.get_json(silent=True) if (request.content_length or 0) <= 1024 else None
        if not isinstance(raw, dict) or set(raw) != {"session_id", "request_id", "cancel_token"}:
            raise ApiError("invalid_generation_token", status=400, code="invalid_generation_token")
        scope = generation_scope(
            _resolve_db_user_id(), raw["session_id"], raw["request_id"], raw["cancel_token"]
        )
        if scope is None:
            raise ApiError("invalid_generation_token", status=400, code="invalid_generation_token")
        if not request_cancellation(current_app.config.get("REDIS_URL"), scope):
            raise ApiError("chat_cancel_unavailable", status=503, code="chat_cancel_unavailable")
        return make_ok({"accepted": True}, 202)

    @api_bp.route("/chat", methods=["POST"])
    @api_error_boundary("chat_unexpected_error")
    def chat():
        session_id, payload, model_name = process_request_data()
        result = generate_chat(
            session_id,
            payload,
            model_name,
            db_user_id=_resolve_db_user_id(),
            remote_addr=request.remote_addr,
        )
        if isinstance(result, ChatStream):
            response = Response(result.events, headers=result.headers, mimetype="text/event-stream")
            response.headers["Cache-Control"] = "no-cache"
            response.headers["X-Accel-Buffering"] = "no"
            return response
        if isinstance(result, ChatImage):
            return send_file(io.BytesIO(result.data), mimetype=result.mime_type)
        return make_ok(result)

    @api_bp.route("/translate", methods=["POST"])
    @anonymous_rate_limit(anonymous_translation_limiter)
    @rate_limit(translation_limiter)
    @api_error_boundary("translation_failed")
    def translate():
        payload = request.get_json(silent=True) or {}
        text = payload.get("text")
        target_lang = payload.get("target_lang", "en")

        if not isinstance(text, str) or not text.strip():
            raise ApiError("text required", status=400, code="text_required")
        if not isinstance(target_lang, str) or not target_lang.strip():
            raise ApiError("target_lang required", status=400, code="target_lang_required")

        max_length = 10000 if _resolve_db_user_id() is not None else ANONYMOUS_TRANSLATION_MAX_CHARS
        text = InputValidator.validate_chat_message(text, max_length=max_length)
        if not re.match(r"^[a-zA-Z]{2,3}(-[a-zA-Z]{2,4})?$", target_lang.strip()):
            raise ApiError("Invalid target_lang", status=400, code="invalid_target_lang")

        try:
            translated_text, used_fallback = translate_text(text, target_lang.strip())
        except TranslationUnavailableError as exc:
            raise ApiError(
                "Translation is temporarily unavailable",
                status=503,
                code="translation_unavailable",
            ) from exc
        return make_ok({"translated_text": translated_text, "fallback": used_fallback})

    @api_bp.route("/get-link-metadata", methods=["POST"])
    @api_error_boundary("link_metadata_failed")
    def get_link_metadata():
        payload = request.get_json(silent=True) or {}
        url = payload.get("url")
        if not isinstance(url, str):
            raise ApiError("URL is required", status=400, code="url_required")
        try:
            validated_url = validate_public_http_url(url)
        except UnsafeUrlError as exc:
            raise ApiError(str(exc), status=400, code="invalid_url") from exc
        return make_ok({"url": validated_url})

    @api_bp.route("/synthesize", methods=["POST"])
    @anonymous_rate_limit(anonymous_synthesize_limiter)
    @rate_limit(synthesize_limiter)
    @api_error_boundary("synthesize_failed")
    def synthesize():
        payload = request.get_json(silent=True) or {}
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ApiError("text required", status=400, code="text_required")
        try:
            text = InputValidator.validate_chat_message(text, max_length=TTS_MAX_CHARS)
        except ValidationError as exc:
            raise ApiError(str(exc), status=400, code="invalid_text") from exc
        return make_ok({"segments": synthesize_text_segments(text)})

    @api_bp.route("/uploads/<path:filename>")
    @api_error_boundary("upload_not_found")
    def uploaded_file_route(filename):
        safe_name = secure_filename(filename)
        if safe_name != filename or not PUBLIC_UPLOAD_NAME_RE.fullmatch(safe_name):
            raise ApiError("Not found", status=404, code="not_found")
        access_and_reference = find_upload_reference(safe_name, _resolve_db_user_id())
        if access_and_reference is None:
            raise ApiError("Not found", status=404, code="not_found")

        _access, attachment = access_and_reference
        extension = Path(safe_name).suffix.lower().lstrip(".")
        as_attachment = extension not in {"gif", "jpeg", "jpg", "png", "webp"}
        original_name = str(attachment.get("original_name") or "").replace("\\", "/")
        download_name = Path(original_name).name.replace("\r", "").replace("\n", "")[:255]
        response = send_from_directory(
            str(current_app.config["UPLOAD_FOLDER"]),
            safe_name,
            as_attachment=as_attachment,
            download_name=(download_name or safe_name) if as_attachment else None,
        )
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @api_bp.route("/images/<path:filename>")
    @api_error_boundary("image_not_found")
    def generated_image_route(filename):
        generated_name = secure_filename(Path(filename).name)
        generated_dir = Path(current_app.config["CREATE_IMAGE_FOLDER"])
        if (
            generated_name
            and generated_name == filename
            and (generated_dir / generated_name).is_file()
        ):
            return send_from_directory(str(generated_dir), generated_name)

        static_folder = current_app.static_folder
        if static_folder:
            static_images_dir = Path(static_folder) / "images"
            if static_images_dir.is_dir():
                return send_from_directory(str(static_images_dir), filename)

        raise ApiError("Not found", status=404, code="not_found")
