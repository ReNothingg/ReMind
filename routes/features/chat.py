from __future__ import annotations

import inspect
import io
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, cast

from flask import Flask, Response, current_app, request, send_file, send_from_directory, session
from werkzeug.utils import secure_filename

from ai_engine import get_model_function
from config import ALLOW_GUEST_CHATS_SAVE
from routes.api_errors import ApiError, api_error_boundary
from services.chat_history import (
    _generate_guest_session_token,
    append_messages_to_history,
    chat_file_exists,
    has_valid_guest_session_token,
    load_chat_history,
    normalize_message,
    resolve_session_identifier,
)
from services.files import handle_file_upload
from services.voice import synthesize_text_segments
from utils.input_validation import InputValidator, ValidationError
from utils.rate_limiting import RateLimiter, rate_limit
from utils.responses import logger, make_ok

PUBLIC_UPLOAD_NAME_RE = re.compile(r"^[a-f0-9]{32}(?:\.[a-z0-9]{1,12})$")
chat_limiter = RateLimiter(max_requests=60, time_window=3600)


def _resolve_db_user_id() -> int | None:
    raw_user_id = session.get("user_id")
    if raw_user_id is None:
        return None
    try:
        return int(raw_user_id)
    except (TypeError, ValueError):
        return None


def _validate_message_in_payload(payload: dict) -> None:
    message = payload.get("message")
    if not message:
        return
    try:
        payload["message"] = InputValidator.validate_chat_message(message)
    except ValidationError as exc:
        raise ApiError(str(exc), status=400, code="invalid_message") from exc


def _extract_uploaded_files() -> list:
    uploaded_files = []
    for key in request.files:
        for file_storage in request.files.getlist(key):
            if file_storage and file_storage.filename:
                uploaded_files.append(file_storage)
    return uploaded_files


def _extract_session_identifier(payload: dict[str, Any]) -> Any:
    return payload.get("session_id") or payload.get("user_id")


def _has_files_payload(value) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    if isinstance(value, str):
        return bool(value.strip())
    return True


def process_request_data() -> tuple[str, dict[str, Any], str]:
    auth_user_id = session.get("user_id")

    def resolve_session_id(raw_identifier: Any) -> str:
        if raw_identifier is None or not str(raw_identifier).strip():
            if auth_user_id is not None:
                raise ApiError(
                    "Session ID is required for authenticated chats.",
                    status=400,
                    code="missing_session_id",
                )
            return f"guest_{uuid.uuid4().hex}"

        safe_identifier = secure_filename(str(raw_identifier))[:200]
        if not safe_identifier:
            raise ApiError("Invalid session ID", status=400, code="invalid_session_id")
        return safe_identifier

    if request.is_json:
        data: dict[str, Any] = request.get_json(silent=True) or {}
        session_id = resolve_session_id(_extract_session_identifier(data))
        model_name = data.get("model", "gemini")
        data["session_id"] = session_id
        data.setdefault("files", [])
        if auth_user_id is None and _has_files_payload(data.get("files")):
            raise ApiError(
                "File uploads are unavailable in guest mode.",
                status=403,
                code="guest_file_upload_disabled",
            )
        _validate_message_in_payload(data)
        return session_id, data, model_name

    if not request.form and not request.files:
        raise ApiError("Empty request", status=400, code="empty_request")

    user_data: dict[str, Any] = request.form.to_dict()
    session_id = resolve_session_id(_extract_session_identifier(user_data))
    model_name = user_data.get("model", "gemini")
    user_data["session_id"] = session_id
    _validate_message_in_payload(user_data)

    uploaded_files = _extract_uploaded_files()
    if auth_user_id is None and uploaded_files:
        raise ApiError(
            "File uploads are unavailable in guest mode.",
            status=403,
            code="guest_file_upload_disabled",
        )
    processed_files = [
        handle_file_upload(file_storage, session_id) for file_storage in uploaded_files
    ]
    user_data["files"] = [file_info for file_info in processed_files if file_info is not None]

    if "meta" in user_data and isinstance(user_data["meta"], str):
        try:
            user_data["meta"] = json.loads(user_data["meta"])
        except json.JSONDecodeError:
            user_data["meta"] = {}

    return session_id, user_data, model_name


def _build_user_message_parts(original_message: str, files: list[dict]) -> list[dict]:
    parts: list[dict] = []
    if original_message:
        parts.append({"text": original_message})

    for file_info in files or []:
        if not isinstance(file_info, dict) or not file_info.get("url_path"):
            continue

        mime_type = file_info.get("mime_type", "")
        part_content = {
            "url_path": file_info.get("url_path"),
            "mime_type": mime_type,
            "original_name": file_info.get("original_name"),
        }
        if mime_type.startswith("image/"):
            parts.append({"image": part_content})
        else:
            parts.append({"file": part_content})

    return parts


def _coerce_image_parts(images: Any) -> list[dict[str, str]]:
    if isinstance(images, str):
        raw_images = [images]
    elif isinstance(images, (list, tuple)):
        raw_images = list(images)
    else:
        return []

    normalized_images: list[dict[str, str]] = []
    for image in raw_images:
        if isinstance(image, str):
            url_path = image.strip()
            mime_type = ""
            original_name = ""
        elif isinstance(image, dict):
            url_path = str(
                image.get("url_path") or image.get("url") or image.get("path") or ""
            ).strip()
            mime_type = str(image.get("mime_type") or "").strip()
            original_name = str(image.get("original_name") or "").strip()
        else:
            continue

        if not url_path:
            continue

        image_part = {"url_path": url_path}
        if mime_type:
            image_part["mime_type"] = mime_type
        if original_name:
            image_part["original_name"] = original_name
        normalized_images.append(image_part)

    return normalized_images


def _build_model_message_parts(reply_text: str, images: Any) -> list[dict]:
    parts: list[dict] = []
    if reply_text:
        parts.append({"text": reply_text})

    for image_part in _coerce_image_parts(images):
        parts.append({"image": image_part})

    return parts


def _resolve_history(
    user_data: dict[str, Any], resolved_session_id: str, db_user_id: int | None
) -> list:
    history_field = user_data.get("history")
    if isinstance(history_field, list):
        return history_field
    if isinstance(history_field, str) and history_field.strip():
        try:
            return json.loads(history_field)
        except json.JSONDecodeError:
            return []
    guest_file_access_allowed = db_user_id is None and has_valid_guest_session_token(
        resolved_session_id
    )
    return load_chat_history(
        resolved_session_id,
        db_user_id,
        allow_file_fallback=guest_file_access_allowed,
        require_guest_token=guest_file_access_allowed,
    )


def _allow_guest_file_persistence(resolved_session_id: str, db_user_id: int | None) -> bool:
    if db_user_id is not None or not ALLOW_GUEST_CHATS_SAVE:
        return False
    if has_valid_guest_session_token(resolved_session_id):
        return True
    return not chat_file_exists(resolved_session_id)


def _stream_chat_response(
    model_name: str,
    model_func,
    db_user_id: int | None,
    user_data: dict,
    resolved_session_id: str,
    user_message_for_history: dict,
    allow_guest_file_persistence: bool,
):
    captured_app = cast(Flask, cast(Any, current_app)._get_current_object())

    def stream_generator():
        with captured_app.app_context():
            full_response = ""
            final_data = {}
            try:
                for chunk in model_func(db_user_id, user_data):
                    if isinstance(chunk, dict):
                        if "widget_update" in chunk:
                            yield f"data: {json.dumps({'widget_update': chunk['widget_update']})}\n\n"
                            final_data.update(
                                {k: v for k, v in chunk.items() if k != "widget_update"}
                            )
                            continue

                        if "reply_part" in chunk:
                            chunk_str = str(chunk.get("reply_part") or "")
                            full_response += chunk_str
                            yield f"data: {json.dumps({'reply_part': chunk_str})}\n\n"
                            final_data.update({k: v for k, v in chunk.items() if k != "reply_part"})
                            continue

                        if any(
                            key in chunk for key in ("status", "images", "thinkingTime", "sources")
                        ):
                            yield f"data: {json.dumps(chunk)}\n\n"
                            final_data.update(chunk)
                            continue

                        final_data.update(chunk)
                        continue

                    chunk_str = str(chunk)
                    full_response += chunk_str
                    yield f"data: {json.dumps({'reply_part': chunk_str})}\n\n"

                final_data["reply"] = full_response
                final_data["sessionId"] = resolved_session_id
                if allow_guest_file_persistence:
                    final_data["session_token"] = _generate_guest_session_token(
                        resolved_session_id, int(time.time())
                    )
                yield f"data: {json.dumps(final_data)}\n\n"

            except RuntimeError as exc:
                logger.error("Stream runtime error for '%s': %s", model_name, exc, exc_info=True)
                yield f"data: {json.dumps({'error': 'stream_failed'})}\n\n"

            finally:
                reply_text = str(final_data.get("reply") or full_response or "")
                model_parts = _build_model_message_parts(reply_text, final_data.get("images"))
                new_messages_batch = [
                    user_message_for_history,
                    {"role": "model", "parts": model_parts},
                ]
                try:
                    append_messages_to_history(
                        resolved_session_id,
                        new_messages_batch,
                        model_name,
                        db_user_id,
                        allow_guest_file_persistence=allow_guest_file_persistence,
                    )
                except OSError as exc:
                    logger.warning("Failed to persist stream messages: %s", exc)
                    append_messages_to_history(
                        resolved_session_id,
                        [user_message_for_history],
                        model_name,
                        db_user_id,
                        allow_guest_file_persistence=allow_guest_file_persistence,
                    )

    response = Response(stream_generator(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


def _maybe_return_direct_image(model_output):
    image_bytes = getattr(model_output, "image_bytes", None)
    mime_type = getattr(model_output, "mime_type", None)
    if not isinstance(image_bytes, (bytes, bytearray)) or not isinstance(mime_type, str):
        return None

    return send_file(io.BytesIO(image_bytes), mimetype=mime_type)


def register_chat_routes(api_bp):
    @api_bp.route("/chat", methods=["POST"])
    @rate_limit(chat_limiter, "Too many chat requests. Please wait.")
    @api_error_boundary("chat_unexpected_error")
    def chat():
        session_identifier, user_data, model_name = process_request_data()
        db_user_id = _resolve_db_user_id()

        resolved_session_id, share_entry = resolve_session_identifier(session_identifier)
        if (
            share_entry
            and share_entry.is_public
            and not (db_user_id and share_entry.user_id == db_user_id)
        ):
            raise ApiError("Чат доступен только для чтения.", status=403, code="chat_read_only")

        history = _resolve_history(user_data, resolved_session_id, db_user_id)
        allow_guest_file_persistence = _allow_guest_file_persistence(
            resolved_session_id, db_user_id
        )
        original_user_message = user_data.get("message", "")
        user_data["history"] = history

        user_message_parts = _build_user_message_parts(
            original_user_message, user_data.get("files", [])
        )
        user_message_for_history = normalize_message({"role": "user", "parts": user_message_parts})

        model_func = get_model_function(model_name)
        if not model_func:
            raise ApiError(
                f"Model '{model_name}' not supported.", status=400, code="model_not_supported"
            )
        if not (user_data.get("message") or user_data.get("files")):
            raise ApiError("'message' or 'files' required", status=400, code="missing_input")

        if inspect.isgeneratorfunction(model_func):
            return _stream_chat_response(
                model_name=model_name,
                model_func=model_func,
                db_user_id=db_user_id,
                user_data=user_data,
                resolved_session_id=resolved_session_id,
                user_message_for_history=user_message_for_history,
                allow_guest_file_persistence=allow_guest_file_persistence,
            )

        model_output = model_func(db_user_id, user_data)
        if isinstance(model_output, dict):
            model_parts = _build_model_message_parts(
                str(model_output.get("reply") or ""),
                model_output.get("images"),
            )
        else:
            model_parts = _build_model_message_parts(str(model_output), None)

        new_messages_batch = [user_message_for_history, {"role": "model", "parts": model_parts}]
        append_messages_to_history(
            resolved_session_id,
            new_messages_batch,
            model_name,
            db_user_id,
            allow_guest_file_persistence=allow_guest_file_persistence,
        )

        direct_image_response = _maybe_return_direct_image(model_output)
        if direct_image_response is not None:
            return direct_image_response

        if isinstance(model_output, dict):
            response_data = {"ok": True, **model_output}
        else:
            response_data = {"ok": True, "reply": str(model_output)}

        if allow_guest_file_persistence:
            response_data["session_token"] = _generate_guest_session_token(
                resolved_session_id, int(time.time())
            )
        response_data["sessionId"] = resolved_session_id

        return make_ok(response_data)

    @api_bp.route("/translate", methods=["POST"])
    @api_error_boundary("translation_failed")
    def translate():
        payload = request.get_json(silent=True) or {}
        text = payload.get("text")
        target_lang = payload.get("target_lang", "en")

        if not isinstance(text, str) or not text.strip():
            raise ApiError("text required", status=400, code="text_required")
        if not isinstance(target_lang, str) or not target_lang.strip():
            raise ApiError("target_lang required", status=400, code="target_lang_required")

        text = InputValidator.validate_chat_message(text, max_length=10000)
        if not re.match(r"^[a-zA-Z]{2,3}(-[a-zA-Z]{2,4})?$", target_lang.strip()):
            raise ApiError("Invalid target_lang", status=400, code="invalid_target_lang")

        from config import GEMINI_API_KEY, GEMINI_MODEL_NAME

        if not GEMINI_API_KEY:
            raise ApiError(
                "Translation is temporarily unavailable", status=503, code="translation_unavailable"
            )

        import google.generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)
        model_name = GEMINI_MODEL_NAME or "gemini-1.5-flash"
        model = genai.GenerativeModel(model_name)

        prompt = (
            "Translate the following text to the target language.\n"
            f"Target language: {target_lang.strip()}\n"
            "Rules: Return ONLY the translated text. Do not add quotes, explanations, markdown, or extra lines.\n\n"
            f"{text}"
        )

        response = model.generate_content(prompt, generation_config={"temperature": 0})
        translated_text = (getattr(response, "text", None) or "").strip()
        if not translated_text:
            raise ApiError("Translation failed", status=500, code="translation_failed")
        return make_ok({"translated_text": translated_text})

    @api_bp.route("/get-link-metadata", methods=["POST"])
    def get_link_metadata():
        return make_ok({})

    @api_bp.route("/synthesize", methods=["POST"])
    @api_error_boundary("synthesize_failed")
    def synthesize():
        payload = request.get_json(silent=True) or {}
        text = payload.get("text")
        if not text:
            raise ApiError("text required", status=400, code="text_required")
        return make_ok({"segments": synthesize_text_segments(text)})

    @api_bp.route("/uploads/<path:filename>")
    @api_error_boundary("upload_not_found")
    def uploaded_file_route(filename):
        safe_name = secure_filename(filename)
        if not PUBLIC_UPLOAD_NAME_RE.match(safe_name):
            raise ApiError("Not found", status=404, code="not_found")
        return send_from_directory(str(current_app.config["UPLOAD_FOLDER"]), safe_name)

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
