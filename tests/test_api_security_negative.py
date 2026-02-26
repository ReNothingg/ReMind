import io
import json

from routes.features.chat import chat_limiter
from utils.auth import ChatShare, UserChatHistory, db
from utils.rate_limiting import rate_limit_store


def test_chat_rate_limit_returns_429_and_headers(client):
    original_max = chat_limiter.max_requests
    original_window = chat_limiter.time_window
    original_redis_mode = chat_limiter.use_redis

    chat_limiter.max_requests = 1
    chat_limiter.time_window = 120
    chat_limiter.use_redis = False
    rate_limit_store.clear()

    try:
        first = client.post("/chat", json={"message": "first", "model": "echo"})
        assert first.status_code == 200

        second = client.post("/chat", json={"message": "second", "model": "echo"})
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


def test_upload_validation_rejects_invalid_extension(client):
    response = client.post(
        "/chat",
        data={
            "model": "echo",
            "user_id": "guest_upload_validation",
            "file0": (io.BytesIO(b"MZ\\x00\\x01"), "payload.exe"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_input"
