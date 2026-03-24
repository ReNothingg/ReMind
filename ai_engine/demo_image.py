from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path
from typing import Any

from flask import current_app
from PIL import Image, ImageDraw, ImageFilter, ImageFont

STYLE_PALETTES: dict[
    str, tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]
] = {
    "realistic": ((24, 36, 54), (61, 103, 145), (235, 167, 94)),
    "cartoon": ((57, 84, 180), (255, 126, 95), (255, 214, 102)),
    "anime": ((41, 50, 116), (195, 55, 100), (255, 175, 189)),
    "oil_painting": ((65, 36, 25), (143, 86, 59), (232, 180, 122)),
    "watercolor": ((90, 157, 173), (167, 212, 176), (247, 236, 180)),
    "pencil_sketch": ((48, 48, 48), (132, 132, 132), (226, 226, 226)),
}


def _extract_prompt(payload: Any) -> str:
    if isinstance(payload, dict):
        message = str(payload.get("message") or "").strip()
        if message:
            return message
    if isinstance(payload, str):
        return payload.strip() or "Demo image"
    return "Demo image"


def _extract_style(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "realistic"
    raw_style = str(payload.get("image_style") or "realistic").strip().lower()
    return raw_style if raw_style in STYLE_PALETTES else "realistic"


def _load_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    font_names = [
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
    ]
    for font_name in font_names:
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int
) -> list[str]:
    words = text.split()
    if not words:
        return ["Demo image"]

    lines: list[str] = []
    current_line = words[0]

    for word in words[1:]:
        candidate = f"{current_line} {word}"
        left, _, right, _ = draw.textbbox((0, 0), candidate, font=font)
        if right - left <= max_width:
            current_line = candidate
            continue

        lines.append(current_line)
        current_line = word

    lines.append(current_line)
    return lines[:4]


def _blend_channel(start: int, end: int, ratio: float) -> int:
    return int(start * (1.0 - ratio) + end * ratio)


def _generate_demo_image(prompt: str, style: str) -> Path:
    palette = STYLE_PALETTES.get(style, STYLE_PALETTES["realistic"])
    seed_hex = hashlib.sha256(f"{style}:{prompt}".encode("utf-8")).hexdigest()
    seed = int(seed_hex[:16], 16)

    width, height = 1280, 896
    image = Image.new("RGBA", (width, height), color=(0, 0, 0, 255))
    draw = ImageDraw.Draw(image, "RGBA")

    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = tuple(_blend_channel(palette[0][i], palette[1][i], ratio) for i in range(3))
        draw.line((0, y, width, y), fill=(*color, 255))

    accent_layer = Image.new("RGBA", (width, height), color=(0, 0, 0, 0))
    accent_draw = ImageDraw.Draw(accent_layer, "RGBA")
    for index in range(4):
        radius = 180 + ((seed >> (index * 6)) % 220)
        center_x = 140 + ((seed >> (index * 9)) % (width - 280))
        center_y = 120 + ((seed >> (index * 13)) % (height - 240))
        accent_draw.ellipse(
            (
                center_x - radius,
                center_y - radius,
                center_x + radius,
                center_y + radius,
            ),
            fill=(*palette[2], 72 - index * 10),
        )

    accent_layer = accent_layer.filter(ImageFilter.GaussianBlur(26))
    image = Image.alpha_composite(image, accent_layer)
    draw = ImageDraw.Draw(image, "RGBA")

    card_bounds = (72, 72, width - 72, height - 72)
    draw.rounded_rectangle(
        card_bounds,
        radius=40,
        fill=(8, 12, 18, 110),
        outline=(255, 255, 255, 30),
        width=2,
    )

    prompt_font = _load_font(58, bold=True)
    meta_font = _load_font(26)
    lines = _wrap_text(draw, prompt, prompt_font, max_width=width - 240)

    header_y = 124
    draw.text((120, header_y), "ReMind Demo Image", font=meta_font, fill=(255, 255, 255, 196))
    draw.text(
        (120, header_y + 44),
        "Any prompt becomes a generated test image.",
        font=meta_font,
        fill=(230, 236, 242, 172),
    )

    text_y = 248
    for line in lines:
        draw.text((120, text_y), line, font=prompt_font, fill=(255, 255, 255, 255))
        _, _, _, line_bottom = draw.textbbox((120, text_y), line, font=prompt_font)
        text_y = line_bottom + 18

    divider_y = height - 188
    draw.line((120, divider_y, width - 120, divider_y), fill=(255, 255, 255, 34), width=2)

    footer_text = f"Style: {style.replace('_', ' ')}"
    seed_text = f"Seed: {seed_hex[:8]}"
    draw.text((120, divider_y + 34), footer_text, font=meta_font, fill=(255, 255, 255, 190))
    seed_box = draw.textbbox((0, 0), seed_text, font=meta_font)
    seed_width = seed_box[2] - seed_box[0]
    draw.text(
        (width - 120 - seed_width, divider_y + 34),
        seed_text,
        font=meta_font,
        fill=(255, 255, 255, 190),
    )

    image_dir = Path(current_app.config["CREATE_IMAGE_FOLDER"])
    image_dir.mkdir(parents=True, exist_ok=True)
    filename = f"demo_{uuid.uuid4().hex}.png"
    output_path = image_dir / filename
    image.convert("RGB").save(output_path, format="PNG", optimize=True)
    return output_path


def demo_image_stream(_: str | None, payload: dict[str, Any]):
    prompt = _extract_prompt(payload)
    style = _extract_style(payload)

    yield {"status": "generating_image", "prompt": prompt}
    time.sleep(0.05)

    output_path = _generate_demo_image(prompt, style)
    yield {"reply_part": "Тестовое изображение готово."}
    yield {"images": [f"/images/{output_path.name}"]}
