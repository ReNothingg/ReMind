import json
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from flask import request

from ai_engine.prompt_templates import load_prompt, load_prompt_section, render_prompt
from config import PYTHON_RUNNER_ENABLED
from utils.auth import User, UserSettings, db

logger = logging.getLogger(__name__)


def get_user_settings_by_id(user_id: Optional[int]) -> Dict[str, Any]:
    if not user_id:
        return {}
    try:
        u = db.session.get(User, int(user_id))
        if not u:
            return {}
        settings = UserSettings.query.filter_by(user_id=u.id).first()
        return settings.get_settings() if settings else {}
    except Exception as e:
        logger.exception(f"Failed to load user settings for {user_id}: {e}")
        return {}


def get_user_profile_by_id(user_id: Optional[int]) -> Dict[str, Any]:
    if not user_id:
        return {}
    try:
        user = db.session.get(User, int(user_id))
        if not user:
            return {}
        return {
            "username": user.username or "",
            "name": user.name or "",
            "email": user.email or "",
        }
    except Exception as e:
        logger.exception(f"Failed to load user profile for {user_id}: {e}")
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


def render_user_md_with_settings(
    user_id: Optional[int],
    metadata: dict,
    telegram_context: dict[str, Any] | None = None,
) -> str:
    settings = get_user_settings_by_id(user_id)
    user_profile = get_user_profile_by_id(user_id)
    telegram_profile = telegram_context if isinstance(telegram_context, dict) else {}
    telegram_first_name = re.sub(
        r"\s+", " ", str(telegram_profile.get("first_name") or "")
    ).strip()[:200]
    telegram_username = re.sub(r"\s+", " ", str(telegram_profile.get("username") or "")).strip()[
        :200
    ]
    account_name = (
        user_profile.get("name")
        or telegram_first_name
        or user_profile.get("username")
        or telegram_username
        or ""
    )
    mapping = {
        "PREFERRED_NAME": account_name or "",
        "ROLE": settings.get("personalization_profession")
        or metadata.get("personalization_profession")
        or "",
        "OTHER_INFORMATION": settings.get("personalization_more")
        or metadata.get("personalization_more")
        or "",
        "USER_INSTRUCTIONS": settings.get("personalization_instructions")
        or metadata.get("personalization_instructions")
        or "",
        "SCREEN_DIMENSIONS": _format_dimensions(metadata.get("screen_dimensions")),
        "PAGE_DIMENSIONS": _format_dimensions(metadata.get("page_dimensions")),
        "THEME": metadata.get("theme") or "",
        "PLATFORM_TYPE": metadata.get("platform_type") or "",
        "DEVICE_TYPE": metadata.get("device_type") or "",
        "USER_AGENT": metadata.get("user_agent") or "",
        "TIME_SINCE_VISIT_SECONDS": _format_numeric_metadata(
            metadata.get("time_since_visit_seconds"), default="0"
        ),
        "DEVICE_PIXEL_RATIO": _format_numeric_metadata(metadata.get("device_pixel_ratio")),
        "LOCAL_HOUR": _format_numeric_metadata(metadata.get("local_hour")),
        "AVG_MESSAGE_LENGTH": _format_numeric_metadata(metadata.get("avg_message_length")),
        "CONVERSATION_DEPTH": _format_numeric_metadata(
            metadata.get("avg_conversation_depth"), default="0"
        ),
        "INTERFACE_LANGUAGE": metadata.get("interface_language") or "ru",
    }

    return render_prompt("user.md", mapping)


def user_has_github_connection(user_id: Optional[int]) -> bool:
    if not user_id:
        return False
    try:
        from services.github_app import github_app_configured
        from utils.auth import GitHubInstallation

        if not github_app_configured():
            return False
        return GitHubInstallation.query.filter_by(user_id=int(user_id)).first() is not None
    except Exception as e:
        logger.exception(f"Failed to resolve GitHub tool connection for {user_id}: {e}")
        return False


def render_github_tool_prompt(user_id: Optional[int]) -> str:
    if not user_has_github_connection(user_id):
        return ""

    tool_prompt = load_prompt("tools/github.md")
    if not tool_prompt:
        return ""
    return tool_prompt.strip()


def render_web_tool_prompt() -> str:
    tool_prompt = load_prompt_section("tools/web.md", "Assistant System Prompt")
    if not tool_prompt:
        return ""
    return tool_prompt.strip()


def render_visualize_tool_prompt() -> str:
    tool_prompt = load_prompt_section("tools/visualize.md", "ReMind Assistant System Prompt")
    if not tool_prompt:
        return ""
    return tool_prompt.strip()


def render_python_tool_prompt() -> str:
    tool_prompt = load_prompt_section("tools/python.md", "ReMind Assistant System Prompt")
    if not tool_prompt:
        return ""
    return tool_prompt.strip()


def render_current_canvas_textdoc(user_data: dict[str, Any]) -> str:
    canvas = user_data.get("canvas_textdoc") if isinstance(user_data, dict) else None
    if not isinstance(canvas, dict):
        return ""

    name = str(canvas.get("name") or "").strip()
    textdoc_type = str(canvas.get("type") or "").strip()
    content = str(canvas.get("content") or "")
    fence_language = "text"
    if textdoc_type.startswith("code/"):
        raw_language = textdoc_type.split("/", 1)[1].strip().lower()
        if re.match(r"^[a-z0-9_-]{1,32}$", raw_language):
            fence_language = raw_language
    content = _truncate_prompt_value(content, 24_000)

    return render_prompt(
        "context/current_canvas.md",
        {
            "NAME": name,
            "TYPE": textdoc_type,
            "FENCE_LANGUAGE": fence_language,
            "CONTENT": content,
        },
    )


def render_beatbox_state_prompt(user_data: dict[str, Any]) -> str:
    beatbox_state = user_data.get("beatbox_state") if isinstance(user_data, dict) else None
    if not isinstance(beatbox_state, dict):
        return ""

    try:
        serialized_state = json.dumps(beatbox_state, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return ""

    serialized_state = _truncate_prompt_value(serialized_state, 24_000)

    return render_prompt(
        "context/beatbox_state.md",
        {"BEATBOX_STATE_JSON": serialized_state},
    )


def render_telegram_context_prompt(user_data: dict[str, Any]) -> str:
    context = user_data.get("telegram_context") if isinstance(user_data, dict) else None
    if not isinstance(context, dict):
        return ""

    def clean(key: str, max_chars: int = 200) -> str:
        return re.sub(r"\s+", " ", str(context.get(key) or "")).strip()[:max_chars]

    return render_prompt(
        "context/telegram.md",
        {
            "CHANNEL": clean("channel", 40),
            "TELEGRAM_FIRST_NAME": clean("first_name"),
            "TELEGRAM_LAST_NAME": clean("last_name"),
            "TELEGRAM_USERNAME": clean("username"),
            "TELEGRAM_LANGUAGE": clean("language_code", 20),
            "CHAT_TYPE": clean("chat_type", 40),
            "CHAT_TITLE": clean("chat_title"),
            "RESPONSE_MODE": clean("response_mode", 40),
        },
    )


def _truncate_prompt_value(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value

    marker = load_prompt("context/truncation_marker.md")
    return value[:max_chars] + (f"\n{marker}" if marker else "")


def _format_dimensions(dim: Optional[dict]) -> str:
    if not isinstance(dim, dict):
        return ""

    width = _format_numeric_metadata(dim.get("width"))
    height = _format_numeric_metadata(dim.get("height"))
    if not width or not height:
        return ""
    return f"{width}x{height}"


def _format_numeric_metadata(value: Any, default: str = "") -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    if isinstance(value, float) and not math.isfinite(value):
        return default
    return str(value)


def _current_datetime() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_system_prompt(user_id: Optional[int], user_data: dict) -> str:
    base = render_prompt("prompt.md", {"currentDateTime": _current_datetime()})
    tools_enabled = user_data.get("toolsEnabled", True) is not False
    history = user_data.get("history") or []
    metadata = build_interaction_metadata(user_data, history)
    telegram_context = (
        user_data.get("telegram_context")
        if isinstance(user_data.get("telegram_context"), dict)
        else None
    )
    user_md = render_user_md_with_settings(user_id, metadata, telegram_context)
    web_tool_prompt = (
        render_web_tool_prompt()
        if tools_enabled
        and str(user_data.get("webSearch") or user_data.get("autoWebSearch") or "").strip().lower()
        in {"1", "true", "yes", "on"}
        else ""
    )
    widget_tool_prompt = render_prompt("tools/widgets.md", {}) if tools_enabled else ""
    visualize_tool_prompt = (
        render_visualize_tool_prompt() if tools_enabled and telegram_context is None else ""
    )
    python_tool_prompt = (
        render_python_tool_prompt()
        if (
            tools_enabled
            and telegram_context is None
            and user_id is not None
            and PYTHON_RUNNER_ENABLED
        )
        else ""
    )
    current_canvas_textdoc = render_current_canvas_textdoc(user_data) if tools_enabled else ""
    beatbox_state_prompt = render_beatbox_state_prompt(user_data) if tools_enabled else ""
    github_tool_prompt = render_github_tool_prompt(user_id) if tools_enabled else ""
    telegram_context_prompt = render_telegram_context_prompt(user_data)
    mind_prompt = render_active_mind_prompt(user_data.get("active_mind"))
    prompt = "\n\n".join(section for section in (base, user_md) if section)

    tool_prompts = [
        tool
        for tool in [
            widget_tool_prompt,
            visualize_tool_prompt,
            python_tool_prompt,
            web_tool_prompt,
            current_canvas_textdoc,
            beatbox_state_prompt,
            github_tool_prompt,
            telegram_context_prompt,
        ]
        if tool
    ]
    if tool_prompts:
        prompt = prompt + "\n\n" + "\n\n".join(tool_prompts)

    if mind_prompt:
        return prompt + "\n\n" + mind_prompt
    return prompt


def render_active_mind_prompt(active_mind: Any) -> str:
    if not isinstance(active_mind, dict):
        return ""

    name = str(active_mind.get("name") or "").strip()
    description = str(active_mind.get("description") or "").strip()
    instructions = str(active_mind.get("instructions") or "").strip()
    if not name or not instructions:
        return ""

    return render_prompt(
        "context/active_mind.md",
        {
            "MIND_NAME": name,
            "MIND_DESCRIPTION": description,
            "MIND_INSTRUCTIONS": instructions,
        },
    )
