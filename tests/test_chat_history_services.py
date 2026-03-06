import time

import services.chat_history as chat_history
from services.chat_history import (
    _generate_guest_session_token,
    _get_chat_access_token_from_request,
    _verify_guest_session_token,
    append_messages_to_history,
    build_share_url,
    load_chat_history,
    normalize_message,
    read_chat_file_secure,
    resolve_session_identifier,
    write_chat_file,
)
from utils.auth import ChatShare, UserChatHistory, db


def test_guest_session_tokens_and_secure_reads(app, monkeypatch, tmp_path):
    monkeypatch.setattr(chat_history, "CHATS_FOLDER", tmp_path)
    monkeypatch.setattr(chat_history, "SECRET_KEY", "pytest-secret")
    monkeypatch.setattr(chat_history, "ALLOW_GUEST_CHATS_SAVE", True)

    session_id = "guest_session_token_case"
    payload = {"history": [{"role": "user", "parts": [{"text": "hello"}]}], "title": "Guest"}
    write_chat_file(session_id, payload)

    timestamp = int(time.time())
    token = _generate_guest_session_token(session_id, timestamp)

    assert _verify_guest_session_token(token, session_id) is True
    assert _verify_guest_session_token(token, "different_session") is False

    expired = _generate_guest_session_token(session_id, timestamp - 10)
    assert _verify_guest_session_token(expired, session_id, max_age_seconds=1) is False

    with app.test_request_context(
        f"/sessions/{session_id}?chat_token={token}",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        assert _get_chat_access_token_from_request() == token
        assert read_chat_file_secure(session_id, require_auth=True) == payload

    with app.test_request_context(
        "/sessions/guest_session_token_case",
        headers={"Authorization": "Bearer invalid-token"},
    ):
        assert _get_chat_access_token_from_request() == "invalid-token"
        assert read_chat_file_secure(session_id, require_auth=True) == {}


def test_share_url_resolution_prefers_backend_url_then_allowed_request_host(app, monkeypatch):
    monkeypatch.setattr(chat_history, "BACKEND_URL", "https://api.example.com/")
    assert build_share_url("public123") == "https://api.example.com/c/public123"

    monkeypatch.setattr(chat_history, "BACKEND_URL", "")
    monkeypatch.setattr(chat_history, "ALLOWED_HOSTS", ["localhost"])

    with app.test_request_context("/", base_url="http://localhost/"):
        assert build_share_url("public123") == "http://localhost/c/public123"

    monkeypatch.setattr(chat_history, "ALLOWED_HOSTS", ["example.com"])
    with app.test_request_context("/", base_url="http://localhost/"):
        assert build_share_url("public123") == "/c/public123"


def test_normalize_message_and_title_helpers():
    normalized = normalize_message("plain text")
    assert normalized["role"] == "user"
    assert normalized["parts"][0]["text"] == "plain text"

    explicit = normalize_message({"id": "m1", "role": "assistant", "text": "reply"})
    assert explicit["id"] == "m1"
    assert explicit["parts"] == [{"text": "reply"}]

    title = chat_history._generate_title_from_history(
        [{"role": "user", "parts": [{"text": "   Title with   extra    spaces   "}]}]
    )
    assert title.startswith("Title with extra spaces")

    fallback = chat_history._generate_title_from_history([{"role": "assistant", "parts": []}])
    assert isinstance(fallback, str)
    assert fallback

    signature_text = chat_history._message_signature({"role": "user", "parts": [{"text": "hello"}]})
    signature_url = chat_history._message_signature(
        {"role": "user", "parts": [{"url_path": "/uploads/file.txt"}]}
    )
    assert signature_text.startswith("user::")
    assert signature_url.startswith("user::")


def test_load_append_and_resolve_chat_history(app, create_confirmed_user, monkeypatch, tmp_path):
    monkeypatch.setattr(chat_history, "CHATS_FOLDER", tmp_path)
    monkeypatch.setattr(chat_history, "ALLOW_GUEST_CHATS_SAVE", True)

    user_id, _, _ = create_confirmed_user()
    session_id = "session_history_case_123"
    messages = [
        {
            "id": "m1",
            "role": "user",
            "parts": [{"text": "Hello from the first message"}],
            "timestamp": 1,
        }
    ]

    with app.app_context():
        append_messages_to_history(session_id, messages, "echo", user_id=user_id)
        append_messages_to_history(session_id, messages, "echo", user_id=user_id)

        file_data = chat_history.read_chat_file(session_id)
        assert file_data["title"].startswith("Hello from the first message")
        assert len(file_data["history"]) == 1

        loaded_from_db = load_chat_history(session_id, user_id=user_id)
        assert len(loaded_from_db) == 1
        assert loaded_from_db[0]["id"] == "m1"

        share = ChatShare(
            user_id=user_id,
            session_id=session_id,
            public_id="public_session_history_case",
            is_public=True,
        )
        db.session.add(share)
        db.session.commit()

        resolved_session_id, share_entry = resolve_session_identifier("public_session_history_case")
        assert resolved_session_id == session_id
        assert share_entry.public_id == "public_session_history_case"

        chat = UserChatHistory.query.filter_by(user_id=user_id, session_id=session_id).first()
        assert chat is not None
        assert chat.get_messages()[0]["id"] == "m1"


def test_load_chat_history_returns_empty_for_invalid_or_missing_session(monkeypatch, tmp_path):
    monkeypatch.setattr(chat_history, "CHATS_FOLDER", tmp_path)

    assert load_chat_history("../invalid") == []
    assert load_chat_history("missing_session_id") == []
