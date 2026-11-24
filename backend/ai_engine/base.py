from __future__ import annotations

from typing import Any, Dict, Generator

from backend.ai_engine.agent import agent_stream


def base_stream(user_id: str, user_message_data: Dict[str, Any]) -> Generator[Any, None, None]:
    yield from agent_stream(user_id, user_message_data)
