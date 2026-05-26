from ai_engine.personalization import build_interaction_metadata, render_user_md_with_settings


def test_telegram_metadata_is_rendered_into_personalization_prompt():
    history = [{"role": "user", "parts": [{"text": "Привет"}]}]
    user_data = {
        "history": history,
        "meta": {
            "interface_language": "ru",
            "telegram_id": "123456789",
            "telegram_is_premium": True,
            "telegram_username": "remind_user",
            "telegram_first_name": "Ada",
            "telegram_last_name": "Lovelace",
            "telegram_full_name": "Ada Lovelace",
            "personalization_nickname": "Ada",
            "platform_type": "Telegram Bot",
            "device_type": "telegram_bot",
        },
    }

    metadata = build_interaction_metadata(user_data, history)
    rendered = render_user_md_with_settings(None, metadata)

    assert metadata["telegram_id"] == "123456789"
    assert metadata["telegram_is_premium"] is True
    assert "Telegram ID is 123456789" in rendered
    assert "Telegram username is remind_user" in rendered
    assert "Telegram full name is Ada Lovelace" in rendered
    assert "Telegram Premium status is yes" in rendered


def test_account_name_fills_personalization_when_nickname_is_missing(
    app, create_confirmed_user
):
    with app.app_context():
        user_id, _, _ = create_confirmed_user(username="ada_user", name="Ada Lovelace")
        rendered = render_user_md_with_settings(
            user_id,
            {
                "interface_language": "en",
            },
        )

    assert "* **Preferred Name:** Ada Lovelace" in rendered
    assert "the name on their account is Ada Lovelace." in rendered
