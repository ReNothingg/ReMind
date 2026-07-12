from __future__ import annotations

from types import SimpleNamespace

from ai_engine import gemini
from services.model_tools import ModelToolResult


class _FakeChunk:
    def __init__(self, parts):
        self.parts = parts


class _FakeStream(list):
    prompt_feedback = None


class _FakeChat:
    def __init__(self):
        self.messages = []

    def send_message(self, message, **kwargs):
        self.messages.append((message, kwargs))
        if len(self.messages) == 1:
            function_call = SimpleNamespace(
                name="web_search", args={"query": "current ReMind release"}
            )
            return _FakeStream(
                [_FakeChunk([SimpleNamespace(function_call=function_call, text="")])]
            )
        return _FakeStream(
            [_FakeChunk([SimpleNamespace(function_call=None, text="Final answer")])]
        )


class _FakeModel:
    def __init__(self, chat, captured, **kwargs):
        captured.update(kwargs)
        self.chat = chat

    def start_chat(self, *, history):
        assert history == []
        return self.chat


def test_gemini_pauses_for_tool_result_and_continues(monkeypatch):
    chat = _FakeChat()
    captured = {}
    monkeypatch.setattr(gemini, "_ensure_gemini_configured", lambda: None)
    monkeypatch.setattr(gemini, "build_system_prompt", lambda *_args: "system")
    monkeypatch.setattr(
        gemini,
        "model_tool_declarations",
        lambda _user_id, **_kwargs: [
            {
                "name": "web_search",
                "description": "Search",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
    )
    monkeypatch.setattr(
        gemini,
        "execute_model_tool",
        lambda *_args, **_kwargs: ModelToolResult(
            {"ok": True, "context": "tool result"},
            events=[{"status": "web_search_done"}],
            sources=[{"id": 1, "url": "https://example.com"}],
        ),
    )
    monkeypatch.setattr(
        gemini.genai,
        "GenerativeModel",
        lambda **kwargs: _FakeModel(chat, captured, **kwargs),
    )

    chunks = list(
        gemini.gemini_stream(
            "7",
            {"message": "What is current?", "history": [], "webSearch": True},
        )
    )

    assert chunks[-1] == "Final answer"
    assert {"status": "web_search_done"} in chunks
    assert {"sources": [{"id": 1, "url": "https://example.com"}]} in chunks
    assert captured["tools"][0]["function_declarations"][0]["name"] == "web_search"
    assert chat.messages[0][1]["tool_config"]["function_calling_config"]["mode"] == "ANY"
    function_result = chat.messages[1][0]
    assert function_result.role == "function"
    assert function_result.parts[0].function_response.name == "web_search"
