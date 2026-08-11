from types import SimpleNamespace

from ai_engine import gemini
from services.model_tools import ModelToolResult


def _chunk(*parts):
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=list(parts)))]
    )


def _text(value: str, *, thought: bool = False):
    return SimpleNamespace(text=value, thought=thought, function_call=None)


def _function(name: str, arguments: dict):
    return SimpleNamespace(
        text=None,
        thought=False,
        function_call=SimpleNamespace(name=name, args=arguments),
    )


def _configure_fake_gemini(monkeypatch, rounds):
    sent_messages = []

    class FakeChat:
        def send_message_stream(self, message, config=None):
            assert config is None
            sent_messages.append(message)
            return iter(rounds.pop(0))

    class FakeClient:
        def __init__(self, **_kwargs):
            self.chats = SimpleNamespace(create=lambda **_kwargs: FakeChat())

        def close(self):
            return None

    monkeypatch.setattr(gemini, "GEMINI_API_KEY", "configured")
    monkeypatch.setattr(gemini.genai, "Client", FakeClient)
    monkeypatch.setattr(gemini, "build_system_prompt", lambda *_args: "system")
    monkeypatch.setattr(gemini, "model_tool_declarations", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(gemini, "_generation_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        gemini,
        "execute_model_tool",
        lambda _name, arguments, **_kwargs: ModelToolResult({
            "ok": True,
            "stdout": "25502500\n" if "** 2" in arguments["code"] else "5050\n",
            "duration_ms": 1,
            "artifacts": [],
        }),
    )
    return sent_messages


def _stream_events():
    return list(
        gemini.gemini_stream(
            "42",
            {
                "message": "Run two calculations",
                "request_id": "request-1",
                "toolsEnabled": True,
            },
        )
    )


def test_multiple_tool_rounds_stay_inside_one_thinking_process(monkeypatch):
    rounds = [
        [
            _chunk(
                _text("Planning the first calculation.", thought=True),
                _text("Thought 1: now I will run code."),
                _function("python_execute", {
                    "code": "print(sum(range(1, 101)))",
                    "purpose": "Calculate and validate the requested sum.",
                }),
            )
        ],
        [
            _chunk(
                _text("The first calculation succeeded.", thought=True),
                _text("Thought 2: use that result for the next calculation."),
                _function("python_execute", {
                    "code": "value = 5050\nprint(value ** 2)",
                    "purpose": "Use the verified sum to calculate its square.",
                }),
            )
        ],
        [
            _chunk(
                _text("Both calculations succeeded.", thought=True),
                _text("The sum is 5050 and its square is 25502500."),
            )
        ],
    ]
    _configure_fake_gemini(monkeypatch, rounds)
    events = _stream_events()

    public_chunks = [event for event in events if isinstance(event, str)]
    assert public_chunks == ["The sum is 5050 and its square is 25502500."]

    thought_parts = [
        event["internal_reply_part"]
        for event in events
        if isinstance(event, dict) and "internal_reply_part" in event
    ]
    assert len(thought_parts) == 1
    assert "Planning the first calculation." in thought_parts[0]
    assert "Thought 1: now I will run code." in thought_parts[0]
    assert "Thought 2: use that result for the next calculation." in thought_parts[0]
    assert thought_parts[0].count("python_activity") == 8
    assert "The first calculation succeeded." in thought_parts[0]
    assert "Both calculations succeeded." in thought_parts[0]
    assert events.index({"internal_reply_part": thought_parts[0]}) < events.index(public_chunks[0])


def test_direct_post_tool_answer_does_not_trigger_a_synthetic_model_round(monkeypatch):
    rounds = [
        [
            _chunk(
                _text("Preparing the calculation.", thought=True),
                _function("python_execute", {
                    "code": "print(sum(range(1, 101)))",
                    "purpose": "Calculate the requested sum.",
                }),
            )
        ],
        [_chunk(_text("Unchecked draft: 5050."))],
    ]
    sent_messages = _configure_fake_gemini(monkeypatch, rounds)

    events = _stream_events()

    assert [event for event in events if isinstance(event, str)] == ["Unchecked draft: 5050."]
    thought_part = next(
        event["internal_reply_part"]
        for event in events
        if isinstance(event, dict) and "internal_reply_part" in event
    )
    assert "Calculate the requested sum." not in thought_part
    assert len(sent_messages) == 2
