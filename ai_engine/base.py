from __future__ import annotations

from typing import Any, Dict, Generator

from ai_engine.gemini import gemini_stream as _provider_stream


def base_stream(user_id: str, user_message_data: Dict[str, Any]) -> Generator[str, None, None]:
    yield from _provider_stream(user_id, user_message_data)
