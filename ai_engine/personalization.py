import os
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional
from flask import request

from utils.auth import UserSettings, User

logger = logging.getLogger(__name__)


def _load_template_file(filename: str) -> Optional[str]:
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(script_dir, filename)
        if not os.path.exists(path):
            logger.debug(f"Template file not found: {path}")
            return None
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.exception(f"Error loading template file {filename}: {e}")
        return None


def get_user_settings_by_id(user_id: Optional[int]) -> Dict[str, Any]:
    if not user_id:
        return {}
    try:
        u = User.query.get(int(user_id))
        if not u:
            return {}
        settings = UserSettings.query.filter_by(user_id=u.id).first()
        return settings.get_settings() if settings else {}
    except Exception as e:
        logger.exception(f"Failed to load user settings for {user_id}: {e}")
        return {}


def build_interaction_metadata(user_data: dict, history: list) -> Dict[str, Any]:
    meta = {}
    if isinstance(user_data, dict):
        raw_meta = user_data.get("meta")
        if isinstance(raw_meta, str):
            try:
                meta = json.loads(raw_meta)
            except Exception:
                meta = {}
        elif isinstance(raw_meta, dict):
            meta = raw_meta
    try:
        req_theme = request.cookies.get("theme") or request.headers.get("X-Theme") or ""
    except Exception:
        req_theme = ""
    try:
        req_device_pixel_ratio = getattr(request, "device_pixel_ratio", None)
    except Exception:
        req_device_pixel_ratio = None
    try:
        req_user_agent = request.headers.get("User-Agent", "")
    except Exception:
        req_user_agent = ""
    try:
        req_platform_type = request.headers.get("Sec-CH-UA-Platform", "")
    except Exception:
        req_platform_type = ""

    metadata = {
        "screen_dimensions": meta.get("screen_dimensions"),
        "page_dimensions": meta.get("page_dimensions"),
        "theme": meta.get("theme") or req_theme,
        "device_pixel_ratio": meta.get("device_pixel_ratio") or req_device_pixel_ratio,
        "user_agent": meta.get("user_agent") or req_user_agent,
        "platform_type": meta.get("platform_type") or req_platform_type,
        "device_type": meta.get("device_type"),
        "local_hour": meta.get("local_hour") or datetime.utcnow().hour,
        "time_since_visit_seconds": meta.get("time_since_visit_seconds"),
        "avg_conversation_depth": meta.get("avg_conversation_depth")
        or (len(history) if isinstance(history, list) else 0),
        "avg_message_length": meta.get("avg_message_length")
        or _compute_avg_message_length(history),
        "active_days_last_30": meta.get("active_days_last_30") or None,
        "interface_language": meta.get("interface_language") or "ru",
    }

    return metadata


def _compute_avg_message_length(history: list) -> int:
    try:
        if not history or not isinstance(history, list):
            return 0
        lengths = []
        for msg in history:
            parts = msg.get("parts") or []
            text = ""
            for p in parts:
                if isinstance(p, dict) and p.get("text"):
                    text += str(p.get("text", ""))
                elif isinstance(p, str):
                    text += p
            if text:
                lengths.append(len(text))
        if not lengths:
            return 0
        return int(sum(lengths) / len(lengths))
    except Exception as e:
        logger.exception(f"Failed to compute average message length: {e}")
        return 0


def render_user_md_with_settings(user_id: Optional[int], metadata: dict) -> str:
    template = _load_template_file("user.md")
    if not template:
        return ""

    settings = get_user_settings_by_id(user_id)
    mapping = {
        "PREFERRED_NAME": settings.get("personalization_nickname")
        or settings.get("username")
        or metadata.get("personalization_nickname")
        or "",
        "ROLE": settings.get("personalization_profession")
        or metadata.get("personalization_profession")
        or "",
        "OTHER_INFORMATION": settings.get("personalization_more")
        or metadata.get("personalization_more")
        or "",
        "USER_INSTRUCTIONS": settings.get("personalization_instructions")
        or metadata.get("personalization_instructions")
        or "",
        "DIMENSIONS": _format_dimensions(
            metadata.get("screen_dimensions") or metadata.get("page_dimensions")
        ),
        "THEME": metadata.get("theme") or "",
        "PLATFORM_TYPE": metadata.get("platform_type") or "",
        "DEVICE_TYPE": metadata.get("device_type") or "",
        "USER_AGENT": metadata.get("user_agent") or "",
        "LOCAL_HOUR": str(metadata.get("local_hour") or ""),
        "AVG_MESSAGE_LENGTH": str(metadata.get("avg_message_length") or ""),
        "AVG_CONVERSATION_DEPTH": str(metadata.get("avg_conversation_depth") or ""),
        "INTERFACE_LANGUAGE": metadata.get("interface_language") or "ru",
    }

    out = template
    for key, val in mapping.items():
        out = out.replace(f"{{{{{key}}}}}", str(val))

    return out


def _format_dimensions(dim: Optional[dict]) -> str:
    if not dim:
        return ""
    try:
        w = dim.get("width")
        h = dim.get("height")
        return f"{w}x{h}" if w and h else ""
    except Exception:
        return ""


def build_system_prompt(user_id: Optional[int], user_data: dict) -> str:
    base = _load_template_file("prompt.md") or ""
    history = user_data.get("history") or []
    metadata = build_interaction_metadata(user_data, history)
    user_md = render_user_md_with_settings(user_id, metadata)
    if base and user_md:
        return base + "\n\n" + "PERSONALIZATION FOR USER:\n" + user_md
    if user_md:
        return user_md
    return base
