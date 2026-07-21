import base64
import re
import unicodedata
import uuid
from pathlib import Path
from typing import Any

from PIL import Image
from werkzeug.datastructures import FileStorage

from config import (
    ALLOWED_IMAGE_EXTENSIONS,
    PIL_AVAILABLE,
    UPLOAD_FOLDER,
)
from utils.input_validation import InputValidator
from utils.secure_upload import (
    is_safe_to_serve,
    validate_file_content,
    validate_mime_type,
)

ALLOWED_FILE_EXTENSIONS = {
    "csv",
    "css",
    "go",
    "json",
    "java",
    "md",
    "rs",
    "ts",
    "txt",
    "xml",
    "yaml",
    "yml",
}
CHAT_IMAGE_MIME_TYPES = {
    "gif": "image/gif",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
CHAT_IMAGE_PIL_FORMATS = {
    "gif": "GIF",
    "jpeg": "JPEG",
    "jpg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
}
CHAT_TEXT_MIME_TYPES = {
    "csv": "text/csv",
    "css": "text/css",
    "go": "text/plain",
    "java": "text/plain",
    "json": "application/json",
    "md": "text/markdown",
    "rs": "text/plain",
    "ts": "text/plain",
    "txt": "text/plain",
    "xml": "application/xml",
    "yaml": "application/yaml",
    "yml": "application/yaml",
}
CHAT_TEXTUAL_DETECTED_MIME_TYPES = {
    "application/json",
    "application/xml",
    "application/x-yaml",
    "application/yaml",
}
CHAT_UPLOAD_MAX_FILES = 10
CHAT_UPLOAD_MAX_TOTAL_BYTES = 8 * 1024 * 1024
CHAT_UPLOAD_EXTENSION_RE = re.compile(r"^[a-z0-9]{1,12}$")


def _validate_chat_filename(filename: object) -> tuple[bool, str | None, str | None]:
    """Validate a display name without transliterating legitimate Unicode names.

    Chat files are stored under generated UUIDs, so the original name never
    becomes a filesystem path. We still reject path separators, control
    characters and malformed extensions before deriving the stored suffix.
    """
    if not isinstance(filename, str) or not filename.strip():
        return False, "Invalid filename", None

    normalized = unicodedata.normalize("NFC", filename.strip())
    if len(normalized) > 255:
        return False, "Filename too long (max 255 characters)", None
    if "/" in normalized or "\\" in normalized:
        return False, "Filename must not contain a path", None
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        for character in normalized
    ):
        return False, "Filename contains control characters", None

    name_parts = normalized.rsplit(".", 1)
    if len(name_parts) != 2 or not name_parts[0].strip():
        return False, "Filename must have a name and extension", None
    extension = name_parts[1].lower()
    if not CHAT_UPLOAD_EXTENSION_RE.fullmatch(extension):
        return False, "Filename has an invalid extension", None

    return True, None, normalized


def _file_storage_size(file_storage: FileStorage) -> int:
    stream = getattr(file_storage, "stream", None)
    if stream is not None:
        try:
            position = stream.tell()
            stream.seek(0, 2)
            size = int(stream.tell())
            stream.seek(position)
            return max(0, size)
        except (AttributeError, OSError, TypeError, ValueError):
            pass
    try:
        return max(0, int(file_storage.content_length or 0))
    except (AttributeError, TypeError, ValueError):
        return 0


def validate_chat_uploads(
    file_storages: list[FileStorage],
) -> tuple[bool, str | None, str | None]:
    if len(file_storages) > CHAT_UPLOAD_MAX_FILES:
        return False, "too_many_files", f"A maximum of {CHAT_UPLOAD_MAX_FILES} files is allowed."

    total_bytes = 0
    for file_storage in file_storages:
        is_valid, error, safe_name = _validate_chat_filename(getattr(file_storage, "filename", ""))
        if not is_valid or not safe_name:
            return False, "unsupported_file_type", error or "Unsupported file type."

        extension = safe_name.rsplit(".", 1)[-1].lower()
        if extension not in ALLOWED_IMAGE_EXTENSIONS and extension not in ALLOWED_FILE_EXTENSIONS:
            return False, "unsupported_file_type", f"File type .{extension} is not supported."

        size = _file_storage_size(file_storage)
        if size <= 0:
            return False, "empty_file", "Empty files are not supported."
        total_bytes += size
        if total_bytes > CHAT_UPLOAD_MAX_TOTAL_BYTES:
            max_mb = CHAT_UPLOAD_MAX_TOTAL_BYTES // (1024 * 1024)
            return False, "upload_too_large", f"Attachments can total up to {max_mb} MB."

    return True, None, None


STORED_UPLOAD_NAME_RE = re.compile(r"^[a-f0-9]{32}(?:\.[a-z0-9]{1,12})?$")
MODEL_TEXT_FILE_MAX_CHARS = 100000


def _read_model_text(filepath: Path) -> str | None:
    try:
        raw = filepath.read_bytes()
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeError):
        return None

    if "\x00" in text:
        return None
    control_count = sum(
        1 for character in text if ord(character) < 32 and character not in "\t\n\r"
    )
    if control_count > max(4, len(text) // 100):
        return None
    return text[:MODEL_TEXT_FILE_MAX_CHARS]


def _classify_chat_file(filepath: Path, extension: str) -> tuple[str, str | None] | None:
    """Validate actual file bytes and return a stable MIME/model text pair."""
    is_valid, detected_mime = validate_mime_type(str(filepath))

    if extension in CHAT_IMAGE_MIME_TYPES:
        if not is_valid or detected_mime != CHAT_IMAGE_MIME_TYPES[extension] or not PIL_AVAILABLE:
            return None
        try:
            with Image.open(filepath) as image:
                image_format = image.format
                image.verify()
        except Exception:
            return None
        if image_format != CHAT_IMAGE_PIL_FORMATS[extension]:
            return None
        return detected_mime, None

    if extension not in CHAT_TEXT_MIME_TYPES:
        return None
    text = _read_model_text(filepath)
    if text is None:
        return None
    if not is_valid:
        return None
    if detected_mime and not (
        detected_mime.startswith("text/")
        or detected_mime in CHAT_TEXTUAL_DETECTED_MIME_TYPES
        or detected_mime == "application/octet-stream"
    ):
        return None
    return CHAT_TEXT_MIME_TYPES[extension], text


def _safe_unlink(filepath):
    try:
        filepath.unlink()
    except OSError:
        pass


def handle_file_upload(file_storage, user_id):
    if not file_storage or not file_storage.filename:
        return None
    try:
        InputValidator.validate_text(str(user_id), min_length=1, max_length=100)
    except Exception:
        return None
    is_valid, error, safe_filename_result = _validate_chat_filename(file_storage.filename)
    if not is_valid:
        return None

    extension = (
        safe_filename_result.rsplit(".", 1)[1].lower() if "." in safe_filename_result else ""
    )
    extension_is_image = extension in ALLOWED_IMAGE_EXTENSIONS
    if not extension_is_image and extension not in ALLOWED_FILE_EXTENSIONS:
        return None
    final_filename = f"{uuid.uuid4().hex}.{extension}" if extension else uuid.uuid4().hex
    filepath = UPLOAD_FOLDER / final_filename

    try:
        file_storage.save(str(filepath))
        is_valid, error = validate_file_content(str(filepath))
        if not is_valid:
            _safe_unlink(filepath)
            return None
        classification = _classify_chat_file(filepath, extension)
        if classification is None:
            _safe_unlink(filepath)
            return None
        mimetype, text = classification

        model_part = {}
        if extension_is_image:
            with Image.open(filepath) as img:
                max_dimension = 50000  # 50000x50000 pixels max
                if img.size[0] > max_dimension or img.size[1] > max_dimension:
                    filepath.unlink()
                    return None

            with open(filepath, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("utf-8")
            model_part = {"inline_data": {"mime_type": mimetype, "data": encoded}}
        else:
            if text is None:
                _safe_unlink(filepath)
                return None
            model_part = {"text": f"--- File: {safe_filename_result} ---\n{text}\n--- End File ---"}
        if not is_safe_to_serve(str(filepath)):
            _safe_unlink(filepath)
            return None
    except Exception:
        _safe_unlink(filepath)
        return None

    return {
        "path": str(filepath),
        "url_path": f"/uploads/{final_filename}",
        "mime_type": mimetype,
        "original_name": safe_filename_result,
        "model_part": model_part,
    }


def restore_stored_file_for_model(
    file_info: dict,
    *,
    max_bytes: int | None = None,
) -> dict | None:
    """Rebuild a provider payload for an already-authorized stored attachment."""
    if not isinstance(file_info, dict):
        return None
    url_path = str(file_info.get("url_path") or "").split("?", 1)[0]
    if not url_path.startswith("/uploads/"):
        return None
    filename = url_path.removeprefix("/uploads/")
    if not STORED_UPLOAD_NAME_RE.fullmatch(filename):
        return None
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_IMAGE_EXTENSIONS and extension not in ALLOWED_FILE_EXTENSIONS:
        return None

    upload_root = Path(UPLOAD_FOLDER).resolve()
    filepath = (upload_root / filename).resolve()
    if filepath.parent != upload_root or not filepath.is_file() or not is_safe_to_serve(filepath):
        return None
    is_valid, _error = validate_file_content(str(filepath))
    if not is_valid:
        return None
    file_size = filepath.stat().st_size
    if max_bytes is not None and file_size > max(0, max_bytes):
        return None
    classification = _classify_chat_file(filepath, extension)
    if classification is None:
        return None
    detected_mime, text = classification

    raw_original_name = str(file_info.get("original_name") or filename)
    original_name_valid, _name_error, normalized_original_name = _validate_chat_filename(
        raw_original_name
    )
    original_name = normalized_original_name if original_name_valid else filename
    try:
        if extension in ALLOWED_IMAGE_EXTENSIONS:
            encoded = base64.b64encode(filepath.read_bytes()).decode("utf-8")
            model_part: dict[str, Any] = {
                "inline_data": {"mime_type": detected_mime, "data": encoded}
            }
        else:
            if text is None:
                return None
            model_part = {"text": f"--- File: {original_name} ---\n{text}\n--- End File ---"}
    except (OSError, UnicodeError):
        return None

    return {
        "path": str(filepath),
        "url_path": f"/uploads/{filename}",
        "mime_type": detected_mime,
        "original_name": original_name,
        "size": file_size,
        "model_part": model_part,
    }
