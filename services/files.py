import base64
import re
import uuid
from pathlib import Path

from PIL import Image

from config import (
    ALLOWED_IMAGE_EXTENSIONS,
    PIL_AVAILABLE,
    UPLOAD_FOLDER,
)
from utils.input_validation import InputValidator
from utils.secure_upload import (
    is_safe_to_serve,
    validate_file_content,
    validate_filename,
    validate_mime_type,
)

ALLOWED_FILE_EXTENSIONS = {
    "txt",
    "md",
    "pdf",
    "csv",
    "json",
    "js",
    "py",
    "html",
    "css",
    "c",
    "cpp",
    "h",
    "java",
    "rs",
    "go",
    "ts",
    "xml",
    "yaml",
    "yml",
}
STORED_UPLOAD_NAME_RE = re.compile(r"^[a-f0-9]{32}(?:\.[a-z0-9]{1,12})?$")
MODEL_TEXT_FILE_MAX_CHARS = 100000


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
    is_valid, error, safe_filename_result = validate_filename(file_storage.filename)
    if not is_valid:
        return None

    extension = (
        safe_filename_result.rsplit(".", 1)[1].lower() if "." in safe_filename_result else ""
    )
    mimetype = file_storage.mimetype or "application/octet-stream"
    extension_is_image = extension in ALLOWED_IMAGE_EXTENSIONS
    is_image = extension_is_image and mimetype.startswith("image/")
    if not extension_is_image and extension not in ALLOWED_FILE_EXTENSIONS:
        return None
    final_filename = f"{uuid.uuid4().hex}.{extension}" if extension else uuid.uuid4().hex
    filepath = UPLOAD_FOLDER / final_filename

    try:
        file_storage.save(str(filepath))
    except Exception:
        return None
    is_valid, error = validate_file_content(str(filepath))
    if not is_valid:
        _safe_unlink(filepath)
        return None
    is_valid, detected_mime = validate_mime_type(str(filepath))
    if not is_valid:
        _safe_unlink(filepath)
        return None
    if detected_mime:
        mimetype = detected_mime
    is_image = extension_is_image and mimetype.startswith("image/")

    model_part = {}
    if is_image and PIL_AVAILABLE:
        try:
            with Image.open(filepath) as img:
                img.verify()
            with Image.open(filepath) as img:
                max_dimension = 50000  # 50000x50000 pixels max
                if img.size[0] > max_dimension or img.size[1] > max_dimension:
                    filepath.unlink()
                    return None

            with open(filepath, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("utf-8")
            model_part = {"inline_data": {"mime_type": mimetype, "data": encoded}}
        except Exception:
            _safe_unlink(filepath)
            return None
    else:
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read(100000)  # лимит чтления текста дло 100KB
            safe_display_name = InputValidator.sanitize_output(file_storage.filename)
            model_part = {"text": f"--- File: {safe_display_name} ---\n{text}\n--- End File ---"}
        except Exception:
            safe_display_name = InputValidator.sanitize_output(file_storage.filename)
            model_part = {"text": f"[Binary file: {safe_display_name}]"}
    if not is_safe_to_serve(str(filepath)):
        _safe_unlink(filepath)
        return None

    return {
        "path": str(filepath),
        "url_path": f"/uploads/{final_filename}",
        "mime_type": mimetype,
        "original_name": InputValidator.sanitize_output(file_storage.filename),
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
    is_valid, detected_mime = validate_mime_type(str(filepath))
    if not is_valid or not detected_mime:
        return None

    original_name = InputValidator.sanitize_output(
        str(file_info.get("original_name") or filename)
    )[:255]
    try:
        if detected_mime.startswith("image/"):
            encoded = base64.b64encode(filepath.read_bytes()).decode("utf-8")
            model_part = {
                "inline_data": {"mime_type": detected_mime, "data": encoded}
            }
        else:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as file_obj:
                text = file_obj.read(MODEL_TEXT_FILE_MAX_CHARS)
            model_part = {
                "text": f"--- File: {original_name} ---\n{text}\n--- End File ---"
            }
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
