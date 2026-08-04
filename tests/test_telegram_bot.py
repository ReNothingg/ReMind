from __future__ import annotations

import pytest
import requests
from flask import Flask

from ai_engine.personalization import build_system_prompt
from services import telegram_bot
from utils.auth import (
    AuthIdentity,
    TelegramInlineResult,
    TelegramSubjectError,
    User,
    UserChatHistory,
    _find_or_create_telegram_user,
    _telegram_bot_user_id,
    _telegram_placeholder_email,
    db,
)


def _test_app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite://",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SECRET_KEY="telegram-test-secret",
    )
    db.init_app(app)
    return app


def _linked_profile() -> tuple[User, dict]:
    user = User(
        username="telegram_user",
        name="Telegram User",
        email="telegram@example.com",
        is_confirmed=True,
    )
    db.session.add(user)
    db.session.flush()
    db.session.add(
        AuthIdentity(
            user_id=user.id,
            provider="telegram",
            provider_user_id="123456789",
        )
    )
    db.session.commit()
    return user, {
        "id": 123456789,
        "is_bot": False,
        "first_name": "Telegram",
        "last_name": "User",
        "username": "telegram_user",
        "language_code": "ru-RU",
    }


def test_telegram_login_upgrades_legacy_oidc_subject_to_bot_user_id():
    app = _test_app()
    with app.app_context():
        db.create_all()
        oidc_subject = "1234567890123456789"
        bot_user_id = "987654321"
        user = User(
            username="legacy_telegram",
            name="Legacy Telegram",
            email=_telegram_placeholder_email(oidc_subject),
            is_confirmed=True,
            oauth_provider="telegram",
            oauth_id=oidc_subject,
        )
        db.session.add(user)
        db.session.flush()
        db.session.add(
            AuthIdentity(
                user_id=user.id,
                provider="telegram",
                provider_user_id=oidc_subject,
            )
        )
        db.session.commit()

        resolved = _find_or_create_telegram_user(
            {"sub": oidc_subject, "id": int(bot_user_id), "name": "Legacy Telegram"}
        )

        assert resolved.id == user.id
        identity = AuthIdentity.query.filter_by(user_id=user.id, provider="telegram").one()
        assert identity.provider_user_id == bot_user_id
        assert resolved.oauth_id == bot_user_id
        assert resolved.email == _telegram_placeholder_email(bot_user_id)
        assert resolved.to_dict()["telegram_bot_ready"] is True


def test_new_telegram_login_uses_bot_api_id_instead_of_oidc_subject():
    app = _test_app()
    with app.app_context():
        db.create_all()
        user = _find_or_create_telegram_user(
            {
                "sub": "1234567890123456789",
                "id": 987654321,
                "name": "Telegram User",
                "preferred_username": "telegram_user",
            }
        )

        assert user.oauth_id == "987654321"
        assert user.auth_identities[0].provider_user_id == "987654321"
        assert user.email == _telegram_placeholder_email("987654321")
        assert user.to_dict()["telegram_bot_ready"] is True


@pytest.mark.parametrize("value", [None, True, 0, -1, 0x10000000000, "not-a-number"])
def test_telegram_bot_user_id_rejects_invalid_claims(value):
    with pytest.raises(TelegramSubjectError):
        _telegram_bot_user_id({"id": value})


def test_api_transport_errors_do_not_expose_bot_token(monkeypatch):
    api = telegram_bot.TelegramBotAPI("123456:super-secret-token")

    def fail(*_args, **_kwargs):
        raise requests.ConnectionError("network unavailable")

    monkeypatch.setattr(api._session, "post", fail)
    try:
        api.call("getMe")
    except telegram_bot.TelegramAPIError as exc:
        assert "super-secret-token" not in str(exc)
        assert exc.method == "getMe"
    else:
        raise AssertionError("TelegramAPIError was not raised")


def test_rich_messages_are_split_without_data_loss():
    source = ("A" * 20_000) + "\n\n" + ("B" * 20_000)
    chunks = telegram_bot._split_rich_message(source)
    assert len(chunks) == 2
    assert "".join(chunks) == source.replace("\n\n", "")
    assert all(len(chunk) <= telegram_bot._MAX_RICH_MESSAGE_CHARS for chunk in chunks)


def test_linked_generation_persists_personalized_telegram_session(monkeypatch):
    app = _test_app()
    with app.app_context():
        db.create_all()
        user, profile = _linked_profile()
        linked = telegram_bot._linked_user(profile)
        assert linked is not None
        chat = telegram_bot._chat_for_context(
            linked,
            "telegram_private",
            "private",
            {"channel": "telegram_private"},
            create=True,
        )
        assert chat is not None

        def fake_model(_user_id, user_data):
            assert user_data["telegram_context"]["username"] == "telegram_user"
            assert user_data["meta"]["platform_type"] == "Telegram"
            assert user_data["thinkingLevel"] == "medium"
            assert user_data["toolsEnabled"] is False
            assert user_data["webSearch"] is False
            assert user_data["autoWebSearch"] is False
            yield {
                "thinking_update": {
                    "id": "thought-1",
                    "status": "streaming",
                    "contentDelta": "summary",
                }
            }
            yield {"internal_reply_part": "<think>summary</think>"}
            yield "Hello **Telegram**"

        monkeypatch.setattr(telegram_bot, "get_model_function", lambda _model: fake_model)
        answer = telegram_bot._generate_answer(
            linked,
            "Hello?",
            source="telegram_private",
            chat_payload={"type": "private"},
            session_chat=chat,
            request_id="tg_42",
            brief=False,
            persist=True,
        )

        assert answer == "Hello **Telegram**"
        stored = db.session.get(UserChatHistory, chat.id)
        assert stored is not None
        assert stored.source == "telegram_private"
        assert stored.title == "Hello?"
        history = stored.get_messages()
        assert len(history) == 2
        assert history[0]["parts"][0]["text"] == "Hello?"
        assert "<think>summary</think>" in history[1]["parts"][0]["text"]
        assert history[1]["request_id"] == "tg_42"
        assert user.id == stored.user_id


def test_inline_generation_is_minimal_stateless_and_has_no_tools(monkeypatch):
    app = _test_app()
    with app.app_context():
        db.create_all()
        _user, profile = _linked_profile()
        linked = telegram_bot._linked_user(profile)
        assert linked is not None

        def fake_model(_user_id, user_data):
            assert user_data["thinkingLevel"] == "minimal"
            assert user_data["toolsEnabled"] is False
            assert user_data["history"] == []
            yield "Short answer"

        monkeypatch.setattr(telegram_bot, "get_model_function", lambda _model: fake_model)
        answer = telegram_bot._generate_answer(
            linked,
            "Short question",
            source="telegram_inline",
            chat_payload={"type": "private"},
            session_chat=None,
            request_id="tg_inline_preview_1",
            brief=True,
            persist=False,
        )

        assert answer == "Short answer"


def test_inline_answer_payload_uses_plain_message_content():
    payload = telegram_bot._inline_answer_payload("Короткий ответ")
    assert payload == {"message_text": "Короткий ответ"}
    assert "rich_message" not in payload

    long_answer = "A" * 5000
    payload = telegram_bot._inline_answer_payload(long_answer, force_plain=True)
    assert "message_text" in payload
    assert len(payload["message_text"]) <= telegram_bot._INLINE_RESULT_TEXT_CHARS


def test_telegram_output_strips_unsupported_widget_blocks():
    raw = 'Before\n```canmore\n{"function":"x"}\n```\n<beatbox>{}</beatbox>\nAfter'
    assert telegram_bot._visible_answer(raw) == "Before\n\n\nAfter"


def test_thinking_draft_uses_localized_label_and_blocks_tag_injection():
    draft = telegram_bot._thinking_draft("ru", "Проверяю </tg-thinking> данные")
    assert draft.startswith("<tg-thinking>ИИ рассуждает…")
    assert draft.count("</tg-thinking>") == 1
    assert "Проверяю  данные" in draft


def test_telegram_system_prompt_excludes_all_tool_instructions():
    prompt = build_system_prompt(
        None,
        {
            "toolsEnabled": False,
            "history": [],
            "telegram_context": {
                "channel": "telegram_private",
                "response_mode": "full",
            },
        },
    )

    assert "Namespace: canmore" not in prompt
    assert "Namespace: BeatBox" not in prompt
    assert "No tools or interactive ReMind widgets are available in Telegram" in prompt


def test_chosen_inline_result_is_persisted_once():
    app = _test_app()
    with app.app_context():
        db.create_all()
        user, profile = _linked_profile()
        record = TelegramInlineResult(
            result_id="inline-result-1",
            user_id=user.id,
            telegram_user_id="123456789",
            query_text="Short question",
            answer="Short answer",
            language="ru",
        )
        db.session.add(record)
        db.session.commit()

        chosen = {"result_id": record.result_id, "from": profile, "query": record.query_text}
        telegram_bot.handle_chosen_inline_result(chosen)
        telegram_bot.handle_chosen_inline_result(chosen)

        db.session.refresh(record)
        assert record.selected_at is not None
        chats = UserChatHistory.query.filter_by(user_id=user.id, source="telegram_inline").all()
        assert len(chats) == 1
        assert len(chats[0].get_messages()) == 2
