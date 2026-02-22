import io
import json
import uuid
import time
import os
import inspect
import re
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import (
    Blueprint,
    request,
    jsonify,
    send_from_directory,
    Response,
    send_file,
    session,
    current_app,
)
from sqlalchemy import and_, text

from config import (
    BASE_PATH,
    CHATS_FOLDER,
    CREATE_IMAGE_FOLDER,
    ALLOW_GUEST_CHATS_SAVE,
)

from utils.responses import make_ok, make_error, logger
from utils.auth import UserChatHistory, ChatShare, db
from ai_engine import get_model_function
from services.chat_history import (
    resolve_session_identifier,
    build_share_url,
    load_chat_history,
    read_chat_file,
    read_chat_file_secure,
    normalize_message,
    append_messages_to_history,
    _generate_guest_session_token,
    _verify_guest_session_token,
)
from services.files import handle_file_upload
from services.voice import synthesize_text_segments
from utils.rate_limiting import rate_limit, api_limiter, upload_limiter
from utils.input_validation import InputValidator, ValidationError
from utils.observability import export_prometheus_metrics
_resolve_session_identifier = resolve_session_identifier

api_bp = Blueprint("api", __name__)
from utils.rate_limiting import RateLimiter
chat_limiter = RateLimiter(max_requests=60, time_window=3600)  # 60 per hour for chat
PUBLIC_UPLOAD_NAME_RE = re.compile(r"^[a-f0-9]{32}(?:\.[a-z0-9]{1,12})$")


def process_request_data():
    auth_user_id = session.get("user_id")

    if request.is_json:
        data = request.get_json(silent=True) or {}
        raw_identifier = str(auth_user_id) if auth_user_id else data.get("user_id", "")
        user_id = secure_filename(str(raw_identifier))[:200] or f"guest_{uuid.uuid4().hex}"
        model_name = data.get("model", "gemini")
        data.setdefault("files", [])
        if "message" in data and data["message"]:
            try:
                data["message"] = InputValidator.validate_chat_message(data["message"])
            except ValidationError as e:
                raise ValueError(str(e))

        return user_id, data, model_name
    if not request.form and not request.files:
        raise ValueError("Empty request")
    user_data = request.form.to_dict()
    raw_identifier = str(auth_user_id) if auth_user_id else user_data.get("user_id", "")
    user_id = secure_filename(str(raw_identifier))[:200] or f"guest_{uuid.uuid4().hex}"
    model_name = user_data.get("model", "gemini")
    if "message" in user_data and user_data["message"]:
        try:
            user_data["message"] = InputValidator.validate_chat_message(user_data["message"])
        except ValidationError as e:
            raise ValueError(str(e))

    uploaded = []
    try:
        for key in request.files:
            for fs in request.files.getlist(key):
                if fs and fs.filename:
                    uploaded.append(fs)
    except Exception:
        pass
    processed_files = [
        handle_file_upload(f, user_id)
        for f in uploaded
        if f and getattr(f, "filename", None)
    ]
    user_data["files"] = [f for f in processed_files if f is not None]
    if "meta" in user_data and isinstance(user_data["meta"], str):
        try:
            user_data["meta"] = json.loads(user_data["meta"])
        except Exception:
            user_data["meta"] = {}
    return user_id, user_data, model_name

@api_bp.route("/chat", methods=["POST"])
@rate_limit(chat_limiter, 'Too many chat requests. Please wait.')
def chat():
    try:
        session_identifier, user_data, model_name = process_request_data()

        db_user_id = None
        if "user_id" in session:
            try:
                val = session.get("user_id")
                if val is not None:
                    db_user_id = int(val)
            except (ValueError, TypeError):
                db_user_id = None

        resolved_session_id, share_entry = resolve_session_identifier(
            session_identifier
        )

        if share_entry and share_entry.is_public:
            if not (db_user_id and share_entry.user_id == db_user_id):
                return make_error(
                    "Чат доступен только для чтения.",
                    status=403,
                    code="chat_read_only",
                )

        history_field = user_data.get("history")
        if isinstance(history_field, list):
            history = history_field
        elif isinstance(history_field, str) and history_field.strip():
            try:
                history = json.loads(history_field)
            except json.JSONDecodeError:
                history = []
        else:
            history = load_chat_history(resolved_session_id, db_user_id)

        original_user_message = user_data.get("message", "")
        user_data["history"] = history

        user_message_parts = []
        if original_user_message:
            user_message_parts.append({"text": original_user_message})

        if user_data.get("files"):
            for file_info in user_data["files"]:
                if (
                    file_info
                    and isinstance(file_info, dict)
                    and file_info.get("url_path")
                ):
                    mime_type = file_info.get("mime_type", "")
                    part_content = {
                        "url_path": file_info.get("url_path"),
                        "mime_type": mime_type,
                        "original_name": file_info.get("original_name"),
                    }
                    if mime_type.startswith("image/"):
                        user_message_parts.append({"image": part_content})
                    else:
                        user_message_parts.append({"file": part_content})

        user_message_for_history = normalize_message(
            {"role": "user", "parts": user_message_parts}
        )

        model_func = get_model_function(model_name)
        if not model_func:
            return make_error(
                f"Model '{model_name}' not supported.",
                status=400,
                code="model_not_supported",
            )
        if not (user_data.get("message") or user_data.get("files")):
            return make_error(
                "'message' or 'files' required", status=400, code="missing_input"
            )
        if inspect.isgeneratorfunction(model_func):
            captured_app = current_app._get_current_object()

            def stream_generator():
                with captured_app.app_context():
                    full_response, final_data = "", {}
                    try:
                        for chunk in model_func(db_user_id, user_data):
                            if isinstance(chunk, dict):
                                if "widget_update" in chunk:
                                    try:
                                        yield f"data: {json.dumps({'widget_update': chunk['widget_update']})}\n\n"
                                    except Exception:
                                        pass
                                    final_data.update(
                                        {
                                            k: v
                                            for k, v in chunk.items()
                                            if k != "widget_update"
                                        }
                                    )
                                    continue
                                if "reply_part" in chunk:
                                    chunk_str = str(chunk.get("reply_part") or "")
                                    full_response += chunk_str
                                    try:
                                        yield f"data: {json.dumps({'reply_part': chunk_str})}\n\n"
                                    except Exception:
                                        yield f"data: {json.dumps({'reply_part': str(chunk_str)})}\n\n"
                                    final_data.update(
                                        {
                                            k: v
                                            for k, v in chunk.items()
                                            if k != "reply_part"
                                        }
                                    )
                                    continue
                                if (
                                    "status" in chunk
                                    or "images" in chunk
                                    or "thinkingTime" in chunk
                                    or "sources" in chunk
                                ):
                                    try:
                                        yield f"data: {json.dumps(chunk)}\n\n"
                                    except Exception:
                                        pass
                                    final_data.update(chunk)
                                    continue
                                final_data.update(chunk)
                                continue
                            else:
                                chunk_str = str(chunk)
                                full_response += chunk_str
                                yield f"data: {json.dumps({'reply_part': chunk_str})}\n\n"

                        final_data["reply"] = full_response
                        if db_user_id is None and ALLOW_GUEST_CHATS_SAVE:
                            final_data["session_token"] = _generate_guest_session_token(
                                resolved_session_id, int(time.time())
                            )
                        yield f"data: {json.dumps(final_data)}\n\n"

                    except Exception as e:
                        logger.error(
                            f"Stream error for '{model_name}': {e}", exc_info=True
                        )
                        yield f"data: {json.dumps({'error': 'stream_failed'})}\n\n"

                    finally:
                        model_parts = []
                        try:
                            if full_response:
                                model_parts.append({"text": full_response})
                        except Exception:
                            pass
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
                            )
                        except Exception as e:
                            logger.warning(f"Failed to save both messages: {e}")
                            try:
                                append_messages_to_history(
                                    resolved_session_id,
                                    [user_message_for_history],
                                    model_name,
                                    db_user_id,
                                )
                            except Exception as e2:
                                logger.error(f"Failed to save user message: {e2}")

            resp = Response(stream_generator(), mimetype="text/event-stream")
            try:
                resp.headers["Cache-Control"] = "no-cache"
                resp.headers["X-Accel-Buffering"] = "no"
            except Exception:
                pass
            return resp
        else:
            model_output = model_func(db_user_id, user_data)
            model_parts = []
            try:
                if isinstance(model_output, dict) and model_output.get("reply"):
                    model_parts.append({"text": str(model_output.get("reply"))})
                elif not isinstance(model_output, dict):
                    model_parts.append({"text": str(model_output)})
            except Exception as e:
                logger.exception(f"Error constructing model parts: {e}")
            new_messages_batch = [
                user_message_for_history,
                {"role": "model", "parts": model_parts},
            ]
            try:
                append_messages_to_history(
                    resolved_session_id, new_messages_batch, model_name, db_user_id
                )
            except Exception as e:
                logger.warning(f"Failed to save both messages: {e}")
                try:
                    append_messages_to_history(
                        resolved_session_id, [user_message_for_history], model_name, db_user_id
                    )
                except Exception as e2:
                    logger.error(f"Failed to save user message: {e2}")
            is_direct_image = False
            if "DirectImageResponse" in str(type(model_output)):
                 is_direct_image = True
            if not is_direct_image and model_name.lower() == 'mindart':
                try:
                    from ai_engine.MindArt import DirectImageResponse
                    if isinstance(model_output, DirectImageResponse):
                        is_direct_image = True
                except ImportError:
                    pass

            if is_direct_image:
                return send_file(
                    io.BytesIO(model_output.image_bytes),
                    mimetype=model_output.mime_type,
                )

            if isinstance(model_output, dict):
                response_data = {"ok": True, **model_output}
            else:
                response_data = {"ok": True, "reply": str(model_output)}

            if db_user_id is None and ALLOW_GUEST_CHATS_SAVE:
                guest_token = _generate_guest_session_token(
                    resolved_session_id, int(time.time())
                )
                response_data["session_token"] = guest_token

            if isinstance(model_output, dict):
                return jsonify(response_data)
            return make_ok(response_data)

    except Exception as e:
        logger.error(f"Error in /chat: {e}", exc_info=True)
        return make_error(
            "Internal server error.", status=500, code="chat_unexpected_error"
        )

@api_bp.route("/sessions/<session_id>/history", methods=["GET"])
def get_session_history(session_id):
    try:
        resolved_session_id, share_entry = resolve_session_identifier(session_id)
        db_user_id = None
        if "user_id" in session:
            try:
                db_user_id = int(session.get("user_id"))
            except Exception:
                db_user_id = None

        is_public = bool(share_entry and share_entry.is_public)
        is_owner = bool(
            db_user_id
            and share_entry
            and share_entry.user_id == db_user_id
        )

        if is_public:
            chat = (
                UserChatHistory.query.filter_by(
                    session_id=resolved_session_id
                ).first()
                if resolved_session_id
                else None
            )
            history = chat.get_messages() if chat else load_chat_history(
                resolved_session_id
            )
            title = chat.title if chat else None

            return make_ok(
                {
                    "session_id": resolved_session_id,
                    "history": history,
                    "title": title,
                    "is_public": True,
                    "is_owner": is_owner,
                    "public_id": share_entry.public_id if share_entry else None,
                    "share_url": build_share_url(share_entry.public_id)
                    if share_entry
                    else None,
                    "read_only": not is_owner,
                }
            )

        if db_user_id is not None:
            chat = UserChatHistory.query.filter_by(
                user_id=db_user_id, session_id=resolved_session_id
            ).first()
            if chat:
                return make_ok(
                    {
                        "session_id": resolved_session_id,
                        "history": chat.get_messages(),
                        "title": chat.title,
                        "is_public": False,
                        "is_owner": True,
                    }
                )

        if not ALLOW_GUEST_CHATS_SAVE and "user_id" not in session:
            return make_ok(
                {"session_id": resolved_session_id, "history": [], "title": None}
            )

        safe_session_id = secure_filename(str(resolved_session_id))
        data = read_chat_file_secure(safe_session_id, require_auth=True)
        history = data.get("history", []) if isinstance(data, dict) else []
        title = data.get("title")

        return make_ok(
            {
                "session_id": resolved_session_id,
                "history": history,
                "title": title,
                "is_public": False,
                "is_owner": False,
            }
        )
    except Exception as e:
        return make_error("Failed to get chat history", status=500)

@api_bp.route("/sessions", methods=["GET"])
def list_sessions():
    sessions = []
    db_user_id = None
    page = request.args.get("page", default=1, type=int) or 1
    page_size = request.args.get("page_size", default=50, type=int) or 50
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    total = 0
    has_more = False

    if "user_id" in session:
        try:
            db_user_id = int(session.get("user_id"))
            base_query = (
                db.session.query(
                    UserChatHistory,
                    ChatShare.public_id,
                    ChatShare.is_public,
                )
                .outerjoin(
                    ChatShare,
                    and_(
                        ChatShare.user_id == db_user_id,
                        ChatShare.session_id == UserChatHistory.session_id,
                    ),
                )
                .filter(UserChatHistory.user_id == db_user_id)
            )
            total = base_query.count()
            has_more = (page * page_size) < total

            rows = (
                base_query.order_by(
                    UserChatHistory.updated_at.desc(),
                    UserChatHistory.created_at.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            for chat, public_id, is_public in rows:
                last_updated = 0
                if chat.updated_at:
                    last_updated = chat.updated_at.timestamp()
                elif chat.created_at:
                    last_updated = chat.created_at.timestamp()

                messages = chat.get_messages()
                last_msg_text = ""
                if messages:
                    last = messages[-1]
                    parts = last.get("parts", [])
                    if parts and isinstance(parts[0], dict):
                        last_msg_text = parts[0].get("text", "")

                sessions.append(
                    {
                        "session_id": chat.session_id,
                        "last_updated": last_updated,
                        "title": chat.title or "Новый чат",
                        "last_message": last_msg_text[:60],
                        "is_public": bool(is_public),
                        "public_id": public_id,
                    }
                )
        except Exception as e:
            logger.error(f"DB List Sessions error: {e}")

    request_ids = request.args.get("ids")
    if not db_user_id and request_ids and ALLOW_GUEST_CHATS_SAVE:
        try:
            id_list = request_ids.split(",")[:100]
            token_map = {}
            raw_tokens = request.headers.get("X-Guest-Tokens", "")
            if raw_tokens and len(raw_tokens) <= 16384:
                parsed_tokens = json.loads(raw_tokens)
                if isinstance(parsed_tokens, dict):
                    token_map = parsed_tokens

            for sid in id_list:
                safe_sid = secure_filename(sid.strip())
                if not safe_sid:
                    continue

                token = token_map.get(sid.strip()) or token_map.get(safe_sid)
                if not token or not _verify_guest_session_token(token, safe_sid):
                    continue

                data = read_chat_file(safe_sid)
                if data:
                    history = data.get("history", [])
                    last_msg = ""
                    if history:
                        last = history[-1]
                        parts = last.get("parts", [])
                        if parts and isinstance(parts[0], dict):
                            last_msg = parts[0].get("text", "")

                    sessions.append(
                        {
                            "session_id": safe_sid,
                            "last_updated": data.get("last_updated", 0),
                            "title": data.get("title", "Новый чат"),
                            "last_message": last_msg[:60],
                        }
                    )
        except Exception:
            logger.warning("Guest session listing rejected due to invalid token map")

    if not db_user_id:
        sessions.sort(key=lambda s: s.get("last_updated", 0), reverse=True)
        total = len(sessions)
        start = (page - 1) * page_size
        end = start + page_size
        has_more = end < total
        sessions = sessions[start:end]

    return make_ok(
        {
            "sessions": sessions,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": has_more,
        }
    )

@api_bp.route("/sessions", methods=["POST"])
def create_session():
    if "user_id" in session:
        try:
            db_user_id = int(session.get("user_id"))
            data = request.get_json(silent=True) or {}
            raw_session_id = data.get("session_id")
            if raw_session_id:
                try:
                    session_id = InputValidator.validate_session_id(str(raw_session_id))
                except ValidationError as e:
                    return make_error(str(e), status=400, code="invalid_session_id")
            else:
                session_id = f"user_{uuid.uuid4().hex}"

            raw_title = data.get("title", "Новый чат")
            title = str(raw_title).strip()[:200] if raw_title else "Новый чат"
            if not title:
                title = "Новый чат"

            chat = UserChatHistory(
                user_id=db_user_id,
                session_id=session_id,
                title=title,
            )
            db.session.add(chat)
            db.session.commit()
            return make_ok({"session_id": session_id})
        except Exception as e:
            db.session.rollback()
            return make_error("Failed to create session", 500)

    return make_ok(
        {"session_id": f"guest_{uuid.uuid4().hex}"}
    )

@api_bp.route("/sessions/<session_id>/share", methods=["POST"])
def share_session(session_id):
    from utils.csrf_protection import get_csrf_token_from_request, validate_csrf_token
    from utils.audit_log import log_audit_event, AuditEvents

    if "user_id" not in session:
        return make_error("Требуется авторизация", status=401, code="auth_required")
    csrf_token = get_csrf_token_from_request()
    if not csrf_token or not validate_csrf_token(csrf_token):
        log_audit_event(AuditEvents.SECURITY_CSRF_FAILURE, {'endpoint': 'share_session'})
        return make_error("CSRF validation failed", status=403, code="csrf_failed")

    try:
        db_user_id = int(session.get("user_id"))
    except Exception:
        return make_error("Требуется авторизация", status=401, code="auth_required")

    resolved_session_id, share_entry = resolve_session_identifier(session_id)

    chat = UserChatHistory.query.filter_by(
        user_id=db_user_id, session_id=resolved_session_id
    ).first()
    if not chat:
        return make_error(
            "Чат не найден или не принадлежит вам", status=404, code="not_found"
        )

    payload = request.get_json(silent=True) or {}
    make_public = bool(payload.get("is_public", True))

    if share_entry is None:
        share_entry = ChatShare(
            user_id=db_user_id,
            session_id=resolved_session_id,
            public_id=f"p_{uuid.uuid4().hex}",
            is_public=make_public,
        )
        db.session.add(share_entry)
    else:
        share_entry.is_public = make_public
        share_entry.updated_at = datetime.utcnow()

    try:
        db.session.commit()
        log_audit_event(AuditEvents.MODIFY_CHAT_SHARE, {
            'session_id': resolved_session_id,
            'is_public': make_public
        }, db_user_id)
    except Exception as e:
        db.session.rollback()
        return make_error("Не удалось обновить доступ", status=500)

    return make_ok(
        {
            "session_id": resolved_session_id,
            "is_public": share_entry.is_public,
            "public_id": share_entry.public_id,
            "share_url": build_share_url(share_entry.public_id),
            "read_only": False,
        }
    )

@api_bp.route("/sessions/<session_id>", methods=["DELETE"])
def delete_session(session_id):
    from utils.audit_log import log_audit_event, AuditEvents
    if "user_id" not in session:
        return make_error("Authentication required", status=401, code="auth_required")

    db_user_id = None
    try:
        db_user_id = int(session.get("user_id"))
        chat = UserChatHistory.query.filter_by(
            user_id=db_user_id, session_id=session_id
        ).first()
        if chat:
            db.session.delete(chat)
            db.session.commit()
            log_audit_event(AuditEvents.DELETE_CHAT, {
                'session_id': session_id
            }, db_user_id)
        else:
            return make_error("Chat not found", status=404, code="not_found")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Delete session error: {e}")
        return make_error("Failed to delete chat", status=500)

    return "", 204

@api_bp.route("/voice/")
@api_bp.route("/voice/index.html")
def voice_index():
    return send_from_directory(str(BASE_PATH / "voice"), "index.html")

@api_bp.route("/voice/<path:filename>")
def voice_static(filename):
    return send_from_directory(str(BASE_PATH / "voice"), filename)

@api_bp.route("/<path:path>")
def serve_static(path):
    return send_from_directory(current_app.static_folder, path)

@api_bp.route("/")
def root_index():
    return send_from_directory(current_app.static_folder, "index.html")

@api_bp.route("/c/<path:anything>")
def spa_chat_route(anything):
    return send_from_directory(current_app.static_folder, "index.html")

@api_bp.route("/translate", methods=["POST"])
def translate():
    payload = request.get_json(silent=True) or {}
    text = payload.get("text")
    target_lang = payload.get("target_lang", "en")

    if not isinstance(text, str) or not text.strip():
        return make_error("text required", status=400, code="text_required")

    if not isinstance(target_lang, str) or not target_lang.strip():
        return make_error("target_lang required", status=400, code="target_lang_required")
    try:
        text = InputValidator.validate_chat_message(text, max_length=10000)
    except ValidationError as e:
        return make_error(str(e), status=400, code="invalid_text")

    import re
    if not re.match(r"^[a-zA-Z]{2,3}(-[a-zA-Z]{2,4})?$", target_lang.strip()):
        return make_error("Invalid target_lang", status=400, code="invalid_target_lang")
    from config import GEMINI_API_KEY, GEMINI_MODEL_NAME
    if not GEMINI_API_KEY:
        return make_error("Translation is temporarily unavailable", status=503, code="translation_unavailable")

    try:
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

        resp = model.generate_content(
            prompt,
            generation_config={"temperature": 0},
        )
        translated_text = getattr(resp, "text", None) or ""
        translated_text = translated_text.strip()

        if not translated_text:
            return make_error("Translation failed", status=500, code="translation_failed")

        return make_ok({"translated_text": translated_text})
    except Exception as e:
        logger.warning(f"Translation error: {e}")
        return make_error("Translation failed", status=500, code="translation_failed")

@api_bp.route("/get-link-metadata", methods=["POST"])
def get_link_metadata():
    return make_ok({})

@api_bp.route("/synthesize", methods=["POST"])
def synthesize():
    payload = request.get_json(silent=True) or {}
    text = payload.get("text")
    if not text:
        return make_error("text required", status=400)
    try:
        return make_ok({"segments": synthesize_text_segments(text)})
    except Exception:
        return make_error("Synthesis failed", status=500)

@api_bp.route("/uploads/<path:filename>")
def uploaded_file_route(filename):
    safe_name = secure_filename(filename)
    if not PUBLIC_UPLOAD_NAME_RE.match(safe_name):
        return make_error("Not found", status=404, code="not_found")
    return send_from_directory(
        str(current_app.config["UPLOAD_FOLDER"]), safe_name
    )

@api_bp.route("/images/<path:filename>")
def generated_image_route(filename):
    return send_from_directory(
        str(current_app.config["CREATE_IMAGE_FOLDER"]), secure_filename(filename)
    )


@api_bp.route("/openapi.json", methods=["GET"])
def openapi_spec():
    spec_path = BASE_PATH / "openapi" / "openapi.json"
    if not spec_path.exists():
        return make_error("OpenAPI contract not found", status=404, code="not_found")
    return send_file(str(spec_path), mimetype="application/json")


@api_bp.route("/health", methods=["GET"])
def health():
    started_at = time.perf_counter()
    checks = {}
    status = "ok"
    http_status = 200

    try:
        db.session.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except Exception as exc:
        checks["database"] = {"status": "fail", "reason": "unreachable"}
        logger.error(f"Health-check database probe failed: {exc}")
        status = "fail"
        http_status = 503

    storage_checks = {}
    for cfg_key in ("UPLOAD_FOLDER", "CHATS_FOLDER", "CREATE_IMAGE_FOLDER"):
        folder = current_app.config.get(cfg_key)
        writable = bool(folder and os.path.isdir(folder) and os.access(folder, os.W_OK))
        storage_checks[cfg_key.lower()] = {
            "status": "ok" if writable else "fail",
            "path": str(folder),
        }
        if not writable:
            status = "fail"
            http_status = 503
    checks["storage"] = storage_checks

    session_redis = current_app.config.get("SESSION_REDIS")
    if session_redis is not None:
        try:
            session_redis.ping()
            checks["redis"] = {"status": "ok"}
        except Exception as exc:
            checks["redis"] = {"status": "degraded", "reason": "unreachable"}
            logger.warning(f"Health-check redis probe failed: {exc}")
            if status == "ok":
                status = "degraded"

    now_mono = time.perf_counter()
    startup_mono = current_app.config.get("APP_STARTED_MONOTONIC", now_mono)
    include_full = (request.args.get("full", "") or "").lower() in {"1", "true", "yes"}

    payload = {
        "ok": status != "fail",
        "status": status,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "uptime_seconds": round(max(0.0, now_mono - startup_mono), 3),
        "latency_ms": round((time.perf_counter() - started_at) * 1000.0, 3),
    }
    if include_full or status != "ok":
        payload["checks"] = checks

    return jsonify(payload), http_status


@api_bp.route("/metrics", methods=["GET"])
def metrics():
    return Response(
        export_prometheus_metrics(),
        mimetype="text/plain; version=0.0.4; charset=utf-8",
    )

@api_bp.route("/api/privacy/export", methods=["GET"])
def export_user_data():

    if "user_id" not in session:
        return make_error("Authentication required", status=401, code="auth_required")

    try:
        from utils.privacy import export_user_data as do_export
        from utils.audit_log import log_audit_event, AuditEvents

        user_id = int(session.get("user_id"))
        data = do_export(user_id)

        log_audit_event(AuditEvents.ACCESS_USER_DATA, {'action': 'export'}, user_id)

        return make_ok({"data": data})
    except Exception as e:
        logger.error(f"Data export error: {e}")
        return make_error("Failed to export data", status=500)

@api_bp.route("/api/privacy/delete", methods=["POST"])
def delete_user_data():

    if "user_id" not in session:
        return make_error("Authentication required", status=401, code="auth_required")

    try:
        from utils.privacy import delete_user_data as do_delete
        from utils.csrf_protection import get_csrf_token_from_request, validate_csrf_token
        csrf_token = get_csrf_token_from_request()
        if not csrf_token or not validate_csrf_token(csrf_token):
            return make_error("CSRF validation failed", status=403, code="csrf_failed")

        user_id = int(session.get("user_id"))

        payload = request.get_json(silent=True) or {}
        delete_account = payload.get("delete_account", False)

        results = do_delete(user_id, delete_account=delete_account)

        if delete_account:
            session.clear()

        return make_ok({"deleted": results})
    except Exception as e:
        logger.error(f"Data deletion error: {e}")
        return make_error("Failed to delete data", status=500)
