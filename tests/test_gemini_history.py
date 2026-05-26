from ai_engine.gemini import _prepare_history


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
