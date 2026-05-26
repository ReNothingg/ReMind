from services.telegram_chat_history import TelegramChatHistoryStore, TelegramUserProfile


def test_telegram_history_store_creates_switches_and_lists_sessions(tmp_path):
    store = TelegramChatHistoryStore(base_folder=tmp_path)
    profile = TelegramUserProfile(
        telegram_id=101,
        is_premium=True,
        username="remind_user",
        first_name="Ada",
        last_name="Lovelace",
        language_code="ru",
    )

    first_session = store.get_or_create_active_session(profile)
    assert first_session.session_id
    assert store.get_active_session_id(profile.telegram_id) == first_session.session_id

    updated_session = store.append_exchange(
        profile=profile,
        session_id=first_session.session_id,
        user_text="Расскажи про aiogram",
        reply_text="aiogram — это асинхронный фреймворк для Telegram-ботов.",
        model_name="gemini",
    )
    assert updated_session.title.startswith("Расскажи про aiogram")

    second_session = store.create_session(profile)
    assert second_session.session_id != first_session.session_id
    assert store.get_active_session_id(profile.telegram_id) == second_session.session_id

    switched_session = store.switch_active_session(profile.telegram_id, first_session.session_id)
    assert switched_session is not None
    assert switched_session.session_id == first_session.session_id

    sessions = store.list_sessions(profile.telegram_id, limit=5)
    assert [session.session_id for session in sessions] == [
        first_session.session_id,
        second_session.session_id,
    ]

    history = store.load_history(profile.telegram_id, first_session.session_id)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "model"
