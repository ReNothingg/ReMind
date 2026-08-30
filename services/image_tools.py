from __future__ import annotations

import io
import math
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from config import UPLOAD_FOLDER
from services.python_runner import resolve_input_files
from utils.rate_limiting import RateLimiter

MAX_SOURCE_PIXELS = 25_000_000
MAX_CROP_EDGE = 4096
MAX_FEEDBACK_EDGE = 2048
MAX_TILE_EDGE = 1024
MAX_TILE_COUNT = 9
MAX_DELIVERED_IMAGE_BYTES = 8 * 1024 * 1024
image_tool_limiter = RateLimiter(max_requests=120, time_window=3600, namespace="image_tool")


@dataclass(slots=True)
class ImageToolResult:
    output: dict[str, Any]
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    model_artifacts: list[dict[str, Any]] = field(default_factory=list)
    reusable_files: list[dict[str, Any]] = field(default_factory=list)


def _bounded_int(value: Any, *, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, min(maximum, parsed))


def _required_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _rate_limit(user_id: int | None) -> dict[str, Any] | None:
    if user_id is None:
        return {"ok": False, "error": "image_tool_unavailable"}
    state = image_tool_limiter.evaluate(f"image_tool:user_{int(user_id)}")
    if state.allowed:
        return None
    return {
        "ok": False,
        "error": "image_tool_rate_limit_exceeded",
        "retry_after_seconds": max(1, state.reset_at - int(time.time())),
    }


def _resolve_image(input_files: Any, requested_name: Any) -> tuple[str, Path] | None:
    name = str(requested_name or "").strip()
    if not name:
        return None
    for available_name, path in resolve_input_files(input_files):
        if available_name == name:
            return available_name, path
    return None


def _load_image(path: Path) -> Image.Image:
    with Image.open(path) as opened:
        if (
            opened.width <= 0
            or opened.height <= 0
            or opened.width * opened.height > MAX_SOURCE_PIXELS
        ):
            raise ValueError("image_dimensions_not_supported")
        opened.load()
        return ImageOps.exif_transpose(opened).copy()


def _encode_image(
    image: Image.Image, *, max_edge: int, jpeg_quality: int = 92
) -> tuple[bytes, str, str]:
    rendered = image.copy()
    rendered.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    has_alpha = rendered.mode in {"RGBA", "LA"} or (
        rendered.mode == "P" and "transparency" in rendered.info
    )
    buffer = io.BytesIO()
    if has_alpha:
        rendered.convert("RGBA").save(buffer, format="PNG")
        return buffer.getvalue(), "image/png", ".png"
    rendered.convert("RGB").save(buffer, format="JPEG", quality=jpeg_quality, optimize=True)
    return buffer.getvalue(), "image/jpeg", ".jpg"


def _model_artifact(
    image: Image.Image,
    *,
    name: str,
    source_box: tuple[int, int, int, int],
    max_edge: int,
) -> dict[str, Any]:
    data, mime_type, extension = _encode_image(
        image,
        max_edge=min(MAX_FEEDBACK_EDGE, max_edge),
        jpeg_quality=85,
    )
    artifact_name = f"{Path(name).stem}{extension}"[:180]
    return {
        "original_name": artifact_name,
        "mime_type": mime_type,
        "data": data,
        "metadata": {
            "kind": "image_crop",
            "source_box": list(source_box),
            "width": image.width,
            "height": image.height,
        },
    }


def _persist_image(
    image: Image.Image,
    *,
    base_name: str,
    source_box: tuple[int, int, int, int],
    max_edge: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    data, mime_type, extension = _encode_image(image, max_edge=max_edge)
    if not data or len(data) > MAX_DELIVERED_IMAGE_BYTES:
        raise ValueError("image_output_too_large")
    stored_name = f"{uuid.uuid4().hex}{extension}"
    upload_root = Path(UPLOAD_FOLDER).resolve()
    upload_root.mkdir(parents=True, exist_ok=True)
    target = (upload_root / stored_name).resolve()
    if target.parent != upload_root:
        raise ValueError("invalid_output_path")
    try:
        with target.open("xb") as handle:
            handle.write(data)
        os.chmod(target, 0o600)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    original_name = f"{base_name}{extension}"[:180]
    metadata = {
        "kind": "image_crop",
        "source_box": list(source_box),
        "width": image.width,
        "height": image.height,
    }
    artifact = {
        "url_path": f"/uploads/{stored_name}",
        "original_name": original_name,
        "mime_type": mime_type,
        "size": len(data),
        "metadata": metadata,
    }
    reusable_file = {
        "path": str(target),
        "url_path": artifact["url_path"],
        "original_name": original_name,
        "mime_type": mime_type,
    }
    return artifact, reusable_file


def crop_image(
    arguments: dict[str, Any],
    *,
    input_files: Any,
    allow_artifacts: bool,
    user_id: int | None = None,
) -> ImageToolResult:
    limited = _rate_limit(user_id)
    if limited:
        return ImageToolResult(limited)
    resolved = _resolve_image(input_files, arguments.get("filename"))
    if resolved is None:
        return ImageToolResult({"ok": False, "error": "image_not_found"})
    filename, path = resolved
    try:
        source = _load_image(path)
    except (OSError, ValueError, Image.DecompressionBombError):
        return ImageToolResult({"ok": False, "error": "invalid_image"})

    source_width, source_height = source.size
    x = _required_int(arguments.get("x"))
    y = _required_int(arguments.get("y"))
    width = _required_int(arguments.get("width"))
    height = _required_int(arguments.get("height"))
    if None in {x, y, width, height}:
        return ImageToolResult({"ok": False, "error": "invalid_crop"})
    assert x is not None and y is not None and width is not None and height is not None
    if (
        x < 0
        or y < 0
        or width <= 0
        or height <= 0
        or x >= source_width
        or y >= source_height
        or x + width > source_width
        or y + height > source_height
    ):
        return ImageToolResult(
            {
                "ok": False,
                "error": "crop_out_of_bounds",
                "source_width": source_width,
                "source_height": source_height,
            }
        )

    box = (x, y, x + width, y + height)
    crop = source.crop(box)
    max_edge = _bounded_int(
        arguments.get("max_output_edge"),
        minimum=256,
        maximum=MAX_CROP_EDGE,
        default=MAX_FEEDBACK_EDGE,
    )
    base_name = f"crop-{x}-{y}-{width}-{height}"
    model_artifact = _model_artifact(
        crop,
        name=f"{base_name}.jpg",
        source_box=box,
        max_edge=max_edge,
    )
    artifacts: list[dict[str, Any]] = []
    reusable_files: list[dict[str, Any]] = []
    if bool(arguments.get("deliver_to_user")) and allow_artifacts:
        try:
            artifact, reusable_file = _persist_image(
                crop,
                base_name=base_name,
                source_box=box,
                max_edge=max_edge,
            )
        except (OSError, ValueError):
            return ImageToolResult(
                {
                    "ok": False,
                    "error": "image_delivery_failed",
                    "attached_to_model": True,
                },
                model_artifacts=[model_artifact],
            )
        else:
            artifacts.append(artifact)
            reusable_files.append(reusable_file)

    return ImageToolResult(
        {
            "ok": True,
            "filename": filename,
            "source_width": source_width,
            "source_height": source_height,
            "crop": {"x": x, "y": y, "width": width, "height": height},
            "attached_to_model": True,
            "delivered_to_user": bool(artifacts),
        },
        artifacts=artifacts,
        model_artifacts=[model_artifact],
        reusable_files=reusable_files,
    )


def tile_image(
    arguments: dict[str, Any], *, input_files: Any, user_id: int | None = None
) -> ImageToolResult:
    limited = _rate_limit(user_id)
    if limited:
        return ImageToolResult(limited)
    resolved = _resolve_image(input_files, arguments.get("filename"))
    if resolved is None:
        return ImageToolResult({"ok": False, "error": "image_not_found"})
    filename, path = resolved
    try:
        source = _load_image(path)
    except (OSError, ValueError, Image.DecompressionBombError):
        return ImageToolResult({"ok": False, "error": "invalid_image"})

    rows = _required_int(arguments.get("rows"))
    columns = _required_int(arguments.get("columns"))
    if rows is None or columns is None or not 1 <= rows <= 3 or not 1 <= columns <= 3:
        return ImageToolResult({"ok": False, "error": "invalid_grid"})
    if rows * columns > MAX_TILE_COUNT:
        return ImageToolResult({"ok": False, "error": "too_many_tiles"})
    overlap_percent = _bounded_int(
        arguments.get("overlap_percent"), minimum=0, maximum=25, default=5
    )
    max_edge = _bounded_int(
        arguments.get("max_tile_edge"),
        minimum=512,
        maximum=MAX_TILE_EDGE,
        default=1024,
    )
    source_width, source_height = source.size
    model_artifacts: list[dict[str, Any]] = []
    tiles: list[dict[str, Any]] = []
    for row in range(rows):
        for column in range(columns):
            base_left = math.floor(column * source_width / columns)
            base_top = math.floor(row * source_height / rows)
            base_right = math.ceil((column + 1) * source_width / columns)
            base_bottom = math.ceil((row + 1) * source_height / rows)
            margin_x = round((base_right - base_left) * overlap_percent / 200)
            margin_y = round((base_bottom - base_top) * overlap_percent / 200)
            box = (
                max(0, base_left - margin_x),
                max(0, base_top - margin_y),
                min(source_width, base_right + margin_x),
                min(source_height, base_bottom + margin_y),
            )
            tile = source.crop(box)
            tile_name = f"tile-r{row + 1}-c{column + 1}.jpg"
            model_artifacts.append(
                _model_artifact(tile, name=tile_name, source_box=box, max_edge=max_edge)
            )
            tiles.append(
                {
                    "row": row + 1,
                    "column": column + 1,
                    "x": box[0],
                    "y": box[1],
                    "width": box[2] - box[0],
                    "height": box[3] - box[1],
                    "attachment_name": tile_name,
                }
            )

    return ImageToolResult(
        {
            "ok": True,
            "filename": filename,
            "source_width": source_width,
            "source_height": source_height,
            "rows": rows,
            "columns": columns,
            "overlap_percent": overlap_percent,
            "tiles": tiles,
            "attached_to_model": True,
        },
        model_artifacts=model_artifacts,
    )
