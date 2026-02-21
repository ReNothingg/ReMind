import base64
import uuid
from PIL import Image
from config import (
    UPLOAD_FOLDER,
    ALLOWED_IMAGE_EXTENSIONS,
    PIL_AVAILABLE,
)
from utils.secure_upload import (
    validate_filename,
    validate_file_content,
    validate_mime_type,
    is_safe_to_serve,
)
from utils.input_validation import InputValidator

ALLOWED_FILE_EXTENSIONS = {
    "txt", "md", "pdf", "csv", "json", "js", "py", "html", "css",
    "c", "cpp", "h", "java", "rs", "go", "ts", "xml", "yaml", "yml",
}

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
        safe_filename_result.rsplit(".", 1)[1].lower()
        if "." in safe_filename_result
        else ""
    )
    mimetype = file_storage.mimetype or "application/octet-stream"
    is_image = mimetype.startswith("image/") and extension in ALLOWED_IMAGE_EXTENSIONS
    if not is_image and extension not in ALLOWED_FILE_EXTENSIONS:
        return None
    final_filename = f"{uuid.uuid4().hex}.{extension}" if extension else uuid.uuid4().hex
    filepath = UPLOAD_FOLDER / final_filename

    try:
        file_storage.save(str(filepath))
    except Exception:
        return None
    is_valid, error = validate_file_content(str(filepath))
    if not is_valid:
        try:
            filepath.unlink()
        except:
            pass
        return None
    is_valid, detected_mime = validate_mime_type(str(filepath))
    if not is_valid:
        try:
            filepath.unlink()
        except:
            pass
        return None
    if detected_mime:
        mimetype = detected_mime

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
            try:
                filepath.unlink()
            except:
                pass
            return None
    else:
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read(100000)  # Limit text reading to 100KB
            safe_display_name = InputValidator.sanitize_output(file_storage.filename)
            model_part = {
                "text": f"--- File: {safe_display_name} ---\n{text}\n--- End File ---"
            }
        except Exception:
            safe_display_name = InputValidator.sanitize_output(file_storage.filename)
            model_part = {"text": f"[Binary file: {safe_display_name}]"}
    if not is_safe_to_serve(str(filepath)):
        try:
            filepath.unlink()
        except:
            pass
        return None

    return {
        "path": str(filepath),
        "url_path": f"/uploads/{final_filename}",
        "mime_type": mimetype,
        "original_name": InputValidator.sanitize_output(file_storage.filename),
        "model_part": model_part,
    }
