import io
import json
import time

import routes.features.chat as chat_routes
import services.chat_history as chat_history
from routes.features.chat import anonymous_synthesize_limiter, chat_limiter
from utils.auth import ChatShare, UserChatHistory, db
from utils.rate_limiting import rate_limit_store


def test_chat_rate_limit_returns_429_and_headers(client, monkeypatch):
    original_max = chat_limiter.max_requests
    original_window = chat_limiter.time_window
    original_redis_mode = chat_limiter.use_redis

    chat_limiter.max_requests = 1
    chat_limiter.time_window = 120
    chat_limiter.use_redis = False
    rate_limit_store.clear()
    monkeypatch.setattr(
        chat_routes,
        "get_model_function",
        lambda _name: lambda _user_id, payload: {"reply": payload.get("message", "")},
    )

    try:
        first = client.post("/chat", json={"message": "first", "model": "gemini"})
        assert first.status_code == 200

        second = client.post("/chat", json={"message": "second", "model": "gemini"})
        assert second.status_code == 429
        payload = second.get_json()
        assert payload["ok"] is False
        assert payload["error"]["code"] == "rate_limit_exceeded"

        assert second.headers.get("X-RateLimit-Limit") == "1"
        assert second.headers.get("X-RateLimit-Remaining") == "0"
        assert second.headers.get("X-RateLimit-Reset")
        assert second.headers.get("Retry-After")
    finally:
        chat_limiter.max_requests = original_max
        chat_limiter.time_window = original_window
        chat_limiter.use_redis = original_redis_mode
        rate_limit_store.clear()


def test_share_endpoint_rejects_missing_csrf(client, app, create_confirmed_user, login):
    user_id, email, password = create_confirmed_user()

    with app.app_context():
        db.session.add(
            UserChatHistory(
                user_id=user_id,
                session_id="csrf_share_session",
                title="CSRF Share Session",
                messages_data="[]",
            )
        )
        db.session.commit()

    login_response = login(email, password)
    assert login_response.status_code == 200

    share_response = client.post("/sessions/csrf_share_session/share", json={"is_public": True})
    assert share_response.status_code == 403
    payload = share_response.get_json()
    assert payload["ok"] is False
    assert payload["error"]["code"] in {"csrf_failed", "csrf_validation_failed"}


def test_public_share_is_read_only_for_guest_chat_write(client, app, create_confirmed_user):
    owner_id, _, _ = create_confirmed_user()

    with app.app_context():
        db.session.add(
            UserChatHistory(
                user_id=owner_id,
                session_id="owner_private_session",
                title="Owner Session",
                messages_data=json.dumps([{"role": "user", "parts": [{"text": "hello"}]}]),
            )
        )
        db.session.add(
            ChatShare(
                user_id=owner_id,
                session_id="owner_private_session",
                public_id="public_owner_session",
                is_public=True,
            )
        )
        db.session.commit()

    read_only_attempt = client.post(
        "/chat",
        json={
            "user_id": "public_owner_session",
            "model": "echo",
            "message": "guest should not write into shared session",
        },
    )
    assert read_only_attempt.status_code == 403
    payload = read_only_attempt.get_json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "chat_read_only"


def test_dev_models_are_restricted_to_admin_users(
    client, create_confirmed_user, login, monkeypatch
):
    rate_limit_store.clear()
    create_confirmed_user(username="root_admin")
    _, user_email, user_password = create_confirmed_user(username="plain_user")
    assert login(user_email, user_password).status_code == 200
    csrf_token = client.get("/health").headers.get("X-CSRF-Token")
    assert csrf_token
    monkeypatch.setattr(
        chat_routes,
        "get_model_function",
        lambda _name: lambda _user_id, payload: {"reply": payload.get("message", "")},
    )

    response = client.post(
        "/chat",
        json={"message": "probe", "model": "echo", "session_id": "plain_dev_access"},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 403
    payload = response.get_json()
    assert payload["error"]["code"] == "model_access_denied"
    assert payload["error"]["stage"] == "dev"
    rate_limit_store.clear()


def test_synthesize_rejects_oversized_text_before_tts(client, monkeypatch):
    monkeypatch.setattr(
        chat_routes,
        "synthesize_text_segments",
        lambda _text: (_ for _ in ()).throw(AssertionError("TTS should not be called")),
    )

    response = client.post(
        "/synthesize",
        json={"text": "x" * (chat_routes.TTS_MAX_CHARS + 1)},
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_text"


def test_anonymous_synthesize_has_stricter_quota(client, monkeypatch):
    original_max = anonymous_synthesize_limiter.max_requests
    original_window = anonymous_synthesize_limiter.time_window
    original_redis_mode = anonymous_synthesize_limiter.use_redis

    anonymous_synthesize_limiter.max_requests = 1
    anonymous_synthesize_limiter.time_window = 120
    anonymous_synthesize_limiter.use_redis = False
    rate_limit_store.clear()
    monkeypatch.setattr(
        chat_routes,
        "synthesize_text_segments",
        lambda _text: [{"audio_base64": "ZmFrZQ==", "lang": "en", "error": None}],
    )

    try:
        first = client.post("/synthesize", json={"text": "hello"})
        assert first.status_code == 200

        second = client.post("/synthesize", json={"text": "hello again"})
        assert second.status_code == 429
        assert second.get_json()["error"]["code"] == "anonymous_rate_limit_exceeded"
    finally:
        anonymous_synthesize_limiter.max_requests = original_max
        anonymous_synthesize_limiter.time_window = original_window
        anonymous_synthesize_limiter.use_redis = original_redis_mode
        rate_limit_store.clear()


def test_link_metadata_rejects_non_http_and_private_targets(client):
    for url in [
        "file:///etc/passwd",
        "ftp://example.com/",
        "javascript:alert(1)",
        "http://127.0.0.1:80/",
        "http://localhost/",
        "http://[::1]/",
        "http://10.0.0.1/",
        "http://169.254.169.254/",
    ]:
        response = client.post("/get-link-metadata", json={"url": url})
        assert response.status_code == 400
        assert response.get_json()["error"]["code"] == "invalid_url"


def test_link_metadata_accepts_public_http_url(client):
    response = client.post("/get-link-metadata", json={"url": "https://93.184.216.34/"})

    assert response.status_code == 200
    assert response.get_json()["url"] == "https://93.184.216.34/"


def test_guest_chat_cannot_load_or_overwrite_existing_file_history_without_token(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(chat_history, "CHATS_FOLDER", tmp_path)
    monkeypatch.setattr(chat_history, "ALLOW_GUEST_CHATS_SAVE", True)
    monkeypatch.setattr(chat_routes, "ALLOW_GUEST_CHATS_SAVE", True)
    monkeypatch.setattr(chat_history, "SECRET_KEY", "pytest-secret")

    session_id = "victim_file_session"
    chat_history.write_chat_file(
        session_id,
        {
            "history": [{"role": "user", "parts": [{"text": "private history"}]}],
            "title": "Private",
        },
    )

    def history_echo(_user_id, payload):
        history = payload.get("history") or []
        if not history:
            return {"reply": "no-history"}
        return {"reply": history[0]["parts"][0]["text"]}

    monkeypatch.setattr(chat_routes, "get_model_function", lambda _name: history_echo)
    rate_limit_store.clear()

    try:
        no_token_response = client.post(
            "/chat",
            json={"message": "probe", "model": "gemini", "session_id": session_id},
        )
        assert no_token_response.status_code == 200
        assert no_token_response.get_json()["reply"] == "no-history"
        assert "session_token" not in no_token_response.get_json()

        stored_after_probe = chat_history.read_chat_file(session_id)
        assert len(stored_after_probe["history"]) == 1
        assert stored_after_probe["history"][0]["parts"][0]["text"] == "private history"

        token = chat_history._generate_guest_session_token(session_id, int(time.time()))
        token_response = client.post(
            "/chat",
            json={"message": "probe", "model": "gemini", "session_id": session_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert token_response.status_code == 200
        assert token_response.get_json()["reply"] == "private history"
    finally:
        rate_limit_store.clear()


def test_upload_validation_rejects_invalid_extension_for_authenticated_user(
    client, create_confirmed_user, login
):
    _, email, password = create_confirmed_user()
    login_response = login(email, password)
    assert login_response.status_code == 200

    csrf_token = client.get("/health").headers.get("X-CSRF-Token")
    assert csrf_token

    response = client.post(
        "/chat",
        data={
            "model": "echo",
            "user_id": "guest_upload_validation",
            "file0": (io.BytesIO(b"MZ\\x00\\x01"), "payload.exe"),
        },
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_input"


def test_guest_file_upload_is_forbidden(client):
    response = client.post(
        "/chat",
        data={
            "model": "echo",
            "user_id": "guest_upload_blocked",
            "file0": (io.BytesIO(b"fake image bytes"), "photo.png"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 403
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "guest_file_upload_disabled"
