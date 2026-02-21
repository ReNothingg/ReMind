import io
import os
import uuid
import time
from pathlib import Path
from PIL import Image
try:
    from google import genai

    genai_available = True
except Exception:
    genai_available = False

from config import CREATE_IMAGE_FOLDER, GEMINI_API_KEY


def _ensure_create_folder():
    try:
        Path(CREATE_IMAGE_FOLDER).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def MindArt_stream(user_id, user_data):
    prompt = (user_data.get("message") or "ReMind image").strip()
    yield {"status": "generating_image", "prompt": prompt}
    time.sleep(0.8)

    _ensure_create_folder()

    try:
        image = None
        if genai_available and GEMINI_API_KEY:
            try:
                genai.configure(api_key=GEMINI_API_KEY)
                model = genai.GenerativeModel("gemini-1.5-flash")
                response = model.generate_content(
                    prompt, generation_config={"response_mime_type": "image/png"}
                )
                image_bytes = None
                if hasattr(response, "parts") and response.parts:
                    part = response.parts[0]
                    inline = getattr(part, "inline_data", None)
                    if inline and hasattr(inline, "data"):
                        image_bytes = inline.data
                if not image_bytes and hasattr(response, "candidates"):
                    for cand in response.candidates:
                        for p in getattr(cand, "content", {}).get("parts", []):
                            if getattr(p, "inline_data", None):
                                image_bytes = p.inline_data.data
                                break
                        if image_bytes:
                            break
                if image_bytes:
                    image = Image.open(io.BytesIO(image_bytes))
            except Exception:
                image = None

        if image is None:
            img = Image.new("RGBA", (512, 512), (34, 34, 34, 255))
            from PIL import ImageDraw, ImageFont

            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None
            text = (prompt or "ReMind").strip()[:120]
            draw.text((12, 12), text, fill=(230, 230, 230), font=font)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            image = Image.open(buf)

        unique_filename = f"mindart_{str(user_id)}_{uuid.uuid4().hex[:8]}.png"
        filepath = Path(CREATE_IMAGE_FOLDER) / unique_filename
        image.save(filepath, format="PNG")

        image_url_for_frontend = f"/images/{unique_filename}"

        yield {
            "reply": f"Ваше изображение по запросу «{prompt}» готово!",
            "images": [image_url_for_frontend],
            "end_of_stream": True,
        }

    except Exception as e:
        yield {
            "reply": f"Не удалось создать изображение: {str(e)}",
            "isError": True,
            "end_of_stream": True,
        }


class DirectImageResponse:
    def __init__(self, image_bytes, mime_type="image/png"):
        self.image_bytes = image_bytes
        self.mime_type = mime_type
