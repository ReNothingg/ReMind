from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import and_

from backend.config import UPLOAD_FOLDER
from backend.db.models import ChatShare, UserChatHistory
from backend.errors import ApiError
from backend.responses import logger
from backend.services.context_usage import normalize_context_usage
from backend.services.files import handle_file_upload
from backend.services.tools.canvas_tools import normalize_canvas_textdoc


def _find_uploaded_file_reference(value: Any, url_path: str) -> dict[str, Any] | None:
    if isinstance(value, list):
        for item in value:
            if reference := _find_uploaded_file_reference(item, url_path):
                return reference
        return None
    if not isinstance(value, dict):
        return None

    for attachment_key in ("file", "image"):
        attachment = value.get(attachment_key)
        if isinstance(attachment, dict) and attachment.get("url_path") == url_path:
            return attachment
    for item in value.values():
        if reference := _find_uploaded_file_reference(item, url_path):
            return reference
    return None


def _chat_uploaded_file_reference(chat: UserChatHistory, url_path: str) -> dict[str, Any] | None:
    return _find_uploaded_file_reference(chat.get_messages(), url_path)


def find_upload_reference(filename: str, user_id: int | None) -> tuple[str, dict[str, Any]] | None:
    url_path = f"/uploads/{filename}"
    if user_id is not None:
        owner_candidates = UserChatHistory.query.filter(
            UserChatHistory.user_id == user_id,
            UserChatHistory.messages_data.contains(url_path),
        ).all()
        for chat in owner_candidates:
            if reference := _chat_uploaded_file_reference(chat, url_path):
                return "owner", reference

    public_candidates = (
        UserChatHistory.query.join(
            ChatShare,
            and_(
                ChatShare.user_id == UserChatHistory.user_id,
                ChatShare.session_id == UserChatHistory.session_id,
            ),
        )
        .filter(
            ChatShare.is_public.is_(True),
            UserChatHistory.messages_data.contains(url_path),
        )
        .all()
    )
    for chat in public_candidates:
        if reference := _chat_uploaded_file_reference(chat, url_path):
            return "public", reference
    return None


def stored_attachment_parts(message: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(message, dict):
        return []
    return [
        dict(part)
        for part in message.get("parts", [])
        if isinstance(part, dict) and ("image" in part or "file" in part)
    ]


def cleanup_temporary_uploads(user_data: dict[str, Any]) -> None:
    upload_root = Path(UPLOAD_FOLDER).resolve()
    for file_info in user_data.get("files", []):
        if not isinstance(file_info, dict) or not file_info.get("path"):
            continue
        try:
            path = Path(str(file_info["path"])).resolve()
            if path.parent == upload_root and path.is_file():
                path.unlink()
        except OSError:
            logger.warning("Could not remove a temporary chat upload", exc_info=True)


def persist_pending_uploads(user_data: dict[str, Any], session_id: str) -> list[dict[str, Any]]:
    pending_uploads = user_data.pop("_pending_uploads", [])
    processed_files: list[dict[str, Any]] = []
    for file_storage in pending_uploads:
        try:
            file_info = handle_file_upload(file_storage, session_id)
        except Exception as exc:
            cleanup_temporary_uploads({"files": processed_files})
            raise ApiError(
                "The attachment could not be processed.",
                status=400,
                code="attachment_processing_failed",
            ) from exc
        if file_info is None:
            cleanup_temporary_uploads({"files": processed_files})
            raise ApiError(
                "The attachment could not be processed.",
                status=400,
                code="attachment_processing_failed",
            )
        processed_files.append(file_info)
    user_data["files"] = processed_files
    return processed_files


def build_user_message_parts(original_message: str, files: list[dict]) -> list[dict]:
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


def _build_model_message_parts(
    reply_text: str,
    images: Any,
    python_artifacts: Any = None,
) -> list[dict]:
    parts: list[dict] = []
    if reply_text:
        parts.append({"text": reply_text})

    for image_part in _coerce_image_parts(images):
        parts.append({"image": image_part})

    if isinstance(python_artifacts, list):
        for artifact in python_artifacts:
            if not isinstance(artifact, dict) or not artifact.get("url_path"):
                continue
            attachment: dict[str, Any] = {
                "url_path": str(artifact.get("url_path")),
                "mime_type": str(artifact.get("mime_type") or "application/octet-stream"),
                "original_name": str(artifact.get("original_name") or "artifact"),
                "size": _safe_attachment_size(artifact.get("size")),
                "source": "tool" if artifact.get("source") == "tool" else "python",
            }
            if isinstance(artifact.get("metadata"), dict):
                attachment["metadata"] = dict(artifact["metadata"])
            if isinstance(artifact.get("preview"), str) and artifact["preview"]:
                attachment.setdefault("metadata", {})["inline_result"] = True
            if attachment["mime_type"].startswith("image/"):
                parts.append({"image": attachment})
            else:
                parts.append({"file": attachment})

    return parts


def _safe_attachment_size(value: Any) -> int:
    try:
        return max(0, min(12 * 1024 * 1024, int(value)))
    except (TypeError, ValueError):
        return 0


def build_model_message_for_history(
    reply_text: str,
    images: Any,
    sources: Any,
    python_artifacts: Any = None,
    github_tool: Any = None,
    canvas_textdoc: Any = None,
    canvas_updates: Any = None,
    request_id: str | None = None,
    delivery_status: str | None = None,
    message_id: str | None = None,
    context_usage: Any = None,
) -> dict:
    message: dict[str, Any] = {
        "id": message_id or f"a_{uuid.uuid4().hex}",
        "role": "model",
        "parts": _build_model_message_parts(reply_text, images, python_artifacts),
    }
    if isinstance(sources, list) and sources:
        message["sources"] = sources
    if usage := normalize_context_usage(context_usage):
        message["context_usage"] = usage
    if isinstance(github_tool, dict) and github_tool:
        message["github_tool"] = github_tool
    normalized_canvas = normalize_canvas_textdoc(canvas_textdoc)
    if normalized_canvas:
        message["canvas_textdoc"] = normalized_canvas
    if isinstance(canvas_updates, list) and canvas_updates:
        message["canvas_updates"] = canvas_updates
    if request_id:
        message["request_id"] = request_id
    if delivery_status in {"complete", "interrupted"}:
        message["delivery_status"] = delivery_status
    return message
