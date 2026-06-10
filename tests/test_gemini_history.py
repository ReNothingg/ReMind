from google.api_core import exceptions as google_exceptions

import ai_engine.gemini as gemini
from ai_engine.gemini import _format_google_api_error, _prepare_history


def test_prepare_history_strips_service_fields_and_unsupported_parts():
    history = [
        {
            "id": "m1",
            "timestamp": 1710000000,
            "role": "user",
            "parts": [
                {"text": "Привет"},
                {"image": {"url_path": "/images/test.png"}},
                {"file": {"url_path": "/uploads/test.pdf", "original_name": "test.pdf"}},
            ],
        },
        {
            "id": "m2",
            "timestamp": 1710000001,
            "role": "model",
            "parts": [{"text": "Здравствуйте"}],
        },
    ]

    prepared = _prepare_history(history)

    assert prepared == [
        {"role": "user", "parts": [{"text": "Привет"}]},
        {"role": "model", "parts": [{"text": "Здравствуйте"}]},
    ]


def test_prepare_history_skips_invalid_messages():
    prepared = _prepare_history(
        [
            {"role": "user", "parts": [{"image": {"url_path": "/images/only-image.png"}}]},
            {"role": "system", "parts": [{"text": "ignore"}]},
            "plain text",
        ]
    )

    assert prepared == []


def test_format_google_api_error_redacts_unsupported_location_details():
    error = google_exceptions.FailedPrecondition(
        "User location is not supported for the API use."
    )

    formatted = _format_google_api_error(error)

    assert formatted.startswith("<error>Сервис недоступен</error>")
    assert "Языковая модель сейчас недоступна из текущего региона" in formatted
    assert "User location is not supported" not in formatted


def test_format_google_api_error_includes_generic_message():
    error = google_exceptions.ServiceUnavailable("upstream unavailable")

    formatted = _format_google_api_error(error)

    assert formatted == (
        "<error>Ошибка API</error>"
        "Произошла ошибка при обращении к API Google: upstream unavailable"
    )


def test_gemini_stream_handles_unsupported_location_without_raw_provider_error(monkeypatch):
    class FakeChat:
        def send_message(self, _parts, stream):
            assert stream is True
            raise google_exceptions.FailedPrecondition(
                "User location is not supported for the API use."
            )

    class FakeModel:
        def __init__(self, **_kwargs):
            pass

        def start_chat(self, history):
            assert history == []
            return FakeChat()

    monkeypatch.setattr(gemini, "_ensure_gemini_configured", lambda: None)
    monkeypatch.setattr(gemini, "build_system_prompt", lambda _user_id, _payload: "prompt")
    monkeypatch.setattr(gemini.genai, "GenerativeModel", FakeModel)

    output = "".join(gemini.gemini_stream("1", {"message": "Привет"}))

    assert output.startswith("<error>Сервис недоступен</error>")
    assert "Языковая модель сейчас недоступна из текущего региона" in output
    assert "User location is not supported" not in output
