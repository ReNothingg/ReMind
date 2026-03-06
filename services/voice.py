import base64
import io

from gtts import gTTS
from gtts import lang as gtts_langs
from langdetect import LangDetectException, detect

from config import DEFAULT_LANGUAGE

TTS_MAX_CHARS = 1000


def synthesize_text_segments(text: str) -> list:
    if not text.strip():
        return []
    lang = DEFAULT_LANGUAGE
    try:
        if len(text) > 10 and (d := detect(text)) in gtts_langs.tts_langs():
            lang = d
    except LangDetectException:
        pass
    info = {"original_text": text, "lang": lang, "audio_base64": None, "error": None}
    try:
        tts, fp = gTTS(text=text, lang=lang, slow=False), io.BytesIO()
        tts.write_to_fp(fp)
        info["audio_base64"] = base64.b64encode(fp.getvalue()).decode("utf-8")
    except Exception as e:
        info["error"] = str(e)
    return [info]
