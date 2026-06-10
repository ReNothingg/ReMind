from ai_engine.personalization import (
    build_interaction_metadata,
    build_system_prompt,
    render_user_md_with_settings,
)
from utils.auth import GitHubInstallation, db


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


def test_github_tool_prompt_is_added_only_for_connected_users(
    app, create_confirmed_user, monkeypatch
):
    import services.github_app as github_app

    monkeypatch.setattr(github_app, "github_app_configured", lambda: True)

    with app.app_context():
        connected_user_id, _, _ = create_confirmed_user()
        disconnected_user_id, _, _ = create_confirmed_user()
        installation = GitHubInstallation(
            user_id=connected_user_id,
            installation_id=123,
            account_login="ReNothingg",
            repository_selection="selected",
        )
        db.session.add(installation)
        db.session.commit()

        connected_prompt = build_system_prompt(connected_user_id, {"history": []})
        disconnected_prompt = build_system_prompt(disconnected_user_id, {"history": []})

    assert "CONNECTED TOOL: GITHUB" in connected_prompt
    assert "Required repository" in connected_prompt
    assert "CONNECTED TOOL: GITHUB" not in disconnected_prompt
