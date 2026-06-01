import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

import routes.features.chat as chat_routes
import services.chat_history as chat_history
import utils.auth as auth_module
from config import SESSION_COOKIE_NAME
from utils.auth import ChatShare, User, UserChatHistory, db
from utils.rate_limiting import rate_limit_store
from utils.session_security import resolve_cookie_domain


def test_api_auth_login_and_check(client, create_confirmed_user, login):
    user_id, email, password = create_confirmed_user(name="Ada Lovelace")

    login_response = login(email, password)
    assert login_response.status_code == 200

    payload = login_response.get_json()
    assert payload["message"] == "Успешный вход"
    assert payload["user"]["id"] == user_id

    check_response = client.get("/api/auth/check")
    assert check_response.status_code == 200
    check_payload = check_response.get_json()
    assert check_payload["authenticated"] is True
    assert check_payload["user"]["id"] == user_id
    assert check_payload["user"]["name"] == "Ada Lovelace"


def test_api_auth_config_reports_when_turnstile_is_required(client, monkeypatch):
    import config

    monkeypatch.setattr(config, "TURNSTILE_SITE_KEY", "site-key")
    monkeypatch.setattr(config, "LOCALHOST_MODE", False)

    response = client.get("/api/auth/config")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["turnstile_site_key"] == "site-key"
    assert payload["turnstile_required"] is True
    assert payload["google_mobile_login_url"] == "/login/google?client=ios"
    assert payload["mobile_oauth_redirect_uri"] == "remind://auth/google"
    assert payload["mobile_oauth_callback_scheme"] == "remind"

    monkeypatch.setattr(config, "LOCALHOST_MODE", True)

    localhost_response = client.get("/api/auth/config")

    assert localhost_response.status_code == 200
    assert localhost_response.get_json()["turnstile_required"] is False


def test_html_security_headers_allow_turnstile_iframe(client):
    response = client.get("/")

    assert response.status_code == 200
    csp = response.headers["Content-Security-Policy"]
    assert "frame-src 'self' https://challenges.cloudflare.com" in csp
    assert "Cross-Origin-Embedder-Policy" not in response.headers


def test_api_update_profile_returns_validation_errors_and_updates_name(
    client, app, create_confirmed_user, login
):
    user_id, email, password = create_confirmed_user(username="valid_user", name="Old Name")

    login_response = login(email, password)
    assert login_response.status_code == 200
    csrf_value = client.get("/health").headers.get("X-CSRF-Token")
    assert csrf_value

    invalid_response = client.put(
        "/api/auth/profile",
        json={"username": "bad name"},
        headers={"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_value},
    )
    assert invalid_response.status_code == 400
    invalid_payload = invalid_response.get_json()
    assert invalid_payload["field"] == "username"
    assert "Username can only contain" in invalid_payload["error"]

    update_response = client.put(
        "/api/auth/profile",
        json={"username": "updated_user", "name": "Ada Lovelace"},
        headers={"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_value},
    )
    assert update_response.status_code == 200
    updated_payload = update_response.get_json()
    assert updated_payload["user"]["username"] == "updated_user"
    assert updated_payload["user"]["name"] == "Ada Lovelace"

    with app.app_context():
        refreshed_user = db.session.get(User, user_id)
        assert refreshed_user.username == "updated_user"
        assert refreshed_user.name == "Ada Lovelace"


def test_api_login_wrong_password_for_argon2_hash_returns_401(client, app):
    try:
        from argon2 import PasswordHasher
    except ImportError:
        pytest.skip("argon2 is not installed")

    with app.app_context():
        user = User(
            username="argon-user",
            email="argon@example.com",
            password=PasswordHasher().hash("Password1!"),
            is_confirmed=True,
        )
        db.session.add(user)
        db.session.commit()

    response = client.post(
        "/api/auth/login",
        json={"email": "argon@example.com", "password": "WrongPassword1!"},
        headers={"User-Agent": "Mozilla/5.0 (pytest)"},
    )

    assert response.status_code == 401
    payload = response.get_json()
    assert "email" in payload["error"]


def test_resolve_cookie_domain_uses_host_only_cookies_for_local_requests():
    assert resolve_cookie_domain(".synvexai.com", "127.0.0.1:5000") is None
    assert resolve_cookie_domain(".synvexai.com", "chat.synvexai.com") == ".synvexai.com"


def test_login_uses_non_secure_session_cookie_on_local_http(client, app, create_confirmed_user):
    app.config["SESSION_COOKIE_SECURE"] = True
    _, email, password = create_confirmed_user()

    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        base_url="http://127.0.0.1:5000",
        headers={"User-Agent": "Mozilla/5.0 (pytest)"},
    )

    assert response.status_code == 200
    cookies = response.headers.getlist("Set-Cookie")
    session_cookie = next(
        cookie for cookie in cookies if cookie.startswith(f"{SESSION_COOKIE_NAME}=")
    )
    csrf_cookie = next(cookie for cookie in cookies if cookie.startswith("csrf_token="))
    assert "Secure" not in session_cookie
    assert "Secure" not in csrf_cookie


def test_login_google_uses_host_only_cookies_on_local_host(client, monkeypatch):
    class FakeGoogleClient:
        def create_authorization_url(self, redirect_uri):
            self.redirect_uri = redirect_uri
            return {
                "url": "https://accounts.google.com/o/oauth2/v2/auth?state=test-state",
                "state": "test-state",
            }

        def save_authorize_data(self, **kwargs):
            self.saved = kwargs

    monkeypatch.setattr(auth_module.oauth, "google", FakeGoogleClient(), raising=False)

    response = client.get(
        "/login/google?redirect_to=/health",
        base_url="http://127.0.0.1:5000",
        headers={"User-Agent": "Mozilla/5.0 (pytest)"},
    )

    assert response.status_code == 302
    assert response.headers["Location"].startswith("https://accounts.google.com/")

    cookies = response.headers.getlist("Set-Cookie")
    session_cookie = next(
        cookie for cookie in cookies if cookie.startswith(f"{SESSION_COOKIE_NAME}=")
    )
    fallback_cookie = next(
        cookie for cookie in cookies if cookie.startswith("oauth_state_fallback=")
    )
    assert "Domain=" not in session_cookie
    assert "Domain=" not in fallback_cookie


def test_mobile_google_oauth_callback_completes_api_session(app, client, monkeypatch):
    class FakeUserInfoResponse:
        def json(self):
            return {
                "sub": "google-user-1",
                "email": "ios-google@example.com",
                "name": "iOS Google User",
            }

    class FakeGoogleClient:
        def create_authorization_url(self, redirect_uri):
            self.redirect_uri = redirect_uri
            return {
                "url": "https://accounts.google.com/o/oauth2/v2/auth?state=test-state",
                "state": "test-state",
            }

        def save_authorize_data(self, **kwargs):
            self.saved = kwargs

        def authorize_access_token(self):
            return {"access_token": "test-access-token"}

        def get(self, url, token=None):
            self.userinfo_url = url
            self.userinfo_token = token
            return FakeUserInfoResponse()

    monkeypatch.setattr(auth_module.oauth, "google", FakeGoogleClient(), raising=False)

    start_response = client.get(
        "/login/google?client=ios",
        base_url="http://127.0.0.1:5000",
        headers={"User-Agent": "Mozilla/5.0 (pytest)"},
    )
    assert start_response.status_code == 302
    assert start_response.headers["Location"].startswith("https://accounts.google.com/")

    callback_response = client.get(
        "/login/google/callback?state=test-state&code=test-code",
        base_url="http://127.0.0.1:5000",
        headers={"User-Agent": "Mozilla/5.0 (pytest)"},
    )
    assert callback_response.status_code == 302

    callback_url = callback_response.headers["Location"]
    parsed_callback = urlparse(callback_url)
    assert parsed_callback.scheme == "remind"
    assert parsed_callback.netloc == "auth"
    assert parsed_callback.path == "/google"
    mobile_token = parse_qs(parsed_callback.query)["token"][0]

    mobile_headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1 ReMindIOS/1.0"
        )
    }
    with app.test_client() as mobile_client:
        complete_response = mobile_client.post(
            "/api/auth/mobile/google/complete",
            json={"token": mobile_token},
            headers=mobile_headers,
        )
        assert complete_response.status_code == 200
        payload = complete_response.get_json()
        assert payload["user"]["email"] == "ios-google@example.com"
        assert payload["user"]["oauth_provider"] == "google"

        check_response = mobile_client.get("/api/auth/check", headers=mobile_headers)
        assert check_response.status_code == 200
        assert check_response.get_json()["authenticated"] is True


def test_normalize_redirect_target_keeps_redirects_relative():
    allowed_hosts = ["chat.synvexai.com"]

    assert auth_module._normalize_redirect_target("/health?tab=1", allowed_hosts) == "/health?tab=1"
    assert (
        auth_module._normalize_redirect_target(
            "https://chat.synvexai.com/health?tab=1",
            allowed_hosts,
        )
        == "/health?tab=1"
    )
    assert auth_module._normalize_redirect_target("https://evil.example/phish", allowed_hosts) == ""


def test_login_google_callback_error_redirect_drops_provider_query_params(client, monkeypatch):
    class FailingGoogleClient:
        def authorize_access_token(self):
            raise RuntimeError("forced oauth failure")

    monkeypatch.setattr(auth_module.oauth, "google", FailingGoogleClient(), raising=False)

    response = client.get(
        "/login/google/callback?error=access_denied&error_description=https%3A%2F%2Fevil.example",
        headers={"User-Agent": "Mozilla/5.0 (pytest)"},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
    assert "error=" not in response.headers["Location"]


def test_legacy_register_and_profile_routes_land_on_spa(client, create_confirmed_user, login):
    register_response = client.get("/register")
    assert register_response.status_code == 302
    assert register_response.headers["Location"].endswith("/?auth=register")

    user_id, email, password = create_confirmed_user()
    assert login(email, password).status_code == 200

    profile_response = client.get("/profile")
    assert profile_response.status_code == 302
    assert profile_response.headers["Location"].endswith("/#settings/account")

    good_response = client.get("/good")
    assert good_response.status_code == 303
    assert good_response.headers["Location"].endswith("/")
    assert user_id


def test_password_reset_pages_render_without_removed_template_errors(
    client, app, create_confirmed_user
):
    forgot_response = client.get("/forgot_password")
    assert forgot_response.status_code == 200
    assert "Сброс пароля" in forgot_response.get_data(as_text=True)

    user_id, _, _ = create_confirmed_user()
    with app.app_context():
        user = db.session.get(User, user_id)
        user.reset_token = "reset-token"
        user.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()

    reset_response = client.get("/reset_password/reset-token")
    assert reset_response.status_code == 200
    assert "Новый пароль" in reset_response.get_data(as_text=True)


def test_chat_release_model_as_guest_returns_reply_and_request_id(client, monkeypatch):
    rate_limit_store.clear()
    monkeypatch.setattr(
        chat_routes,
        "get_model_function",
        lambda _name: lambda _user_id, payload: {"reply": payload.get("message", "")},
    )

    response = client.post("/chat", json={"message": "hello from pytest", "model": "gemini"})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["reply"] == "hello from pytest"
    assert response.headers.get("X-Request-Id")
    rate_limit_store.clear()


def test_chat_authenticated_uses_requested_session_id(client, app, create_confirmed_user, login):
    rate_limit_store.clear()
    try:
        user_id, email, password = create_confirmed_user()
        login_response = login(email, password)
        assert login_response.status_code == 200

        csrf_value = client.get(
            "/health", headers={"User-Agent": "Mozilla/5.0 (pytest)"}
        ).headers.get("X-CSRF-Token")
        assert csrf_value

        request_headers = {
            "User-Agent": "Mozilla/5.0 (pytest)",
            "X-CSRF-Token": csrf_value,
        }
        session_a = "user_session_alpha_1234567890"
        session_b = "user_session_beta_1234567890"

        first_response = client.post(
            "/chat",
            json={"message": "first message", "model": "echo", "user_id": session_a},
            headers=request_headers,
        )
        second_response = client.post(
            "/chat",
            json={"message": "second message", "model": "echo", "user_id": session_b},
            headers=request_headers,
        )

        assert first_response.status_code == 200
        assert second_response.status_code == 200

        with app.app_context():
            first_chat = UserChatHistory.query.filter_by(
                user_id=user_id, session_id=session_a
            ).first()
            second_chat = UserChatHistory.query.filter_by(
                user_id=user_id, session_id=session_b
            ).first()

            assert first_chat is not None
            assert second_chat is not None
            assert first_chat.session_id == session_a
            assert second_chat.session_id == session_b

            first_messages = first_chat.get_messages()
            second_messages = second_chat.get_messages()

            assert first_messages[0]["parts"][0]["text"] == "first message"
            assert second_messages[0]["parts"][0]["text"] == "second message"
            assert first_messages != second_messages
    finally:
        rate_limit_store.clear()


def test_chat_demo_image_stream_returns_image_and_persists_history(
    client, app, create_confirmed_user, login, monkeypatch, tmp_path
):
    generated_dir = tmp_path / "generated_images"
    chats_dir = tmp_path / "chats"
    generated_dir.mkdir()
    chats_dir.mkdir()

    monkeypatch.setattr(chat_history, "CHATS_FOLDER", chats_dir)
    app.config["CREATE_IMAGE_FOLDER"] = str(generated_dir)
    rate_limit_store.clear()
    user_id, email, password = create_confirmed_user()
    assert login(email, password).status_code == 200
    csrf_value = client.get(
        "/health", headers={"User-Agent": "Mozilla/5.0 (pytest)"}
    ).headers.get("X-CSRF-Token")
    assert csrf_value

    response = client.post(
        "/chat",
        json={
            "message": "Draw a bright demo skyline at sunset",
            "model": "demo_image",
            "user_id": "demo_image_session",
        },
        headers={"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_value},
    )

    assert response.status_code == 200
    assert response.headers.get("Content-Type", "").startswith("text/event-stream")

    body = response.get_data(as_text=True)
    assert '"status": "generating_image"' in body
    assert '"/images/' in body

    with app.app_context():
        stored_chat = UserChatHistory.query.filter_by(
            user_id=user_id,
            session_id="demo_image_session",
        ).first()
        assert stored_chat is not None
        history = stored_chat.get_messages()
    assert len(history) == 2

    assistant_message = history[-1]
    image_parts = [part["image"] for part in assistant_message["parts"] if "image" in part]
    assert image_parts
    assert any(
        part.get("text") == "Тестовое изображение готово." for part in assistant_message["parts"]
    )

    image_name = Path(image_parts[0]["url_path"]).name
    assert (generated_dir / image_name).is_file()
    rate_limit_store.clear()


def test_list_sessions_paginated_with_public_share(client, app, create_confirmed_user, login):
    user_id, email, password = create_confirmed_user()

    with app.app_context():
        older = UserChatHistory(
            user_id=user_id,
            session_id="session_older",
            title="Old title",
            messages_data=json.dumps([{"role": "user", "parts": [{"text": "old message"}]}]),
            created_at=datetime.utcnow() - timedelta(days=1),
            updated_at=datetime.utcnow() - timedelta(days=1),
        )
        newer = UserChatHistory(
            user_id=user_id,
            session_id="session_newer",
            title="New title",
            messages_data=json.dumps([{"role": "user", "parts": [{"text": "new message"}]}]),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.session.add_all([older, newer])
        db.session.add(
            ChatShare(
                user_id=user_id,
                session_id="session_newer",
                public_id="public_newer",
                is_public=True,
            )
        )
        db.session.commit()

    login_response = login(email, password)
    assert login_response.status_code == 200

    page_1 = client.get("/sessions?page=1&page_size=1")
    assert page_1.status_code == 200
    payload_1 = page_1.get_json()

    assert payload_1["ok"] is True
    assert payload_1["page"] == 1
    assert payload_1["page_size"] == 1
    assert payload_1["total"] == 2
    assert payload_1["has_more"] is True
    assert len(payload_1["sessions"]) == 1
    assert payload_1["sessions"][0]["session_id"] == "session_newer"
    assert payload_1["sessions"][0]["is_public"] is True
    assert payload_1["sessions"][0]["public_id"] == "public_newer"

    page_2 = client.get("/sessions?page=2&page_size=1")
    payload_2 = page_2.get_json()
    assert payload_2["page"] == 2
    assert payload_2["has_more"] is False
    assert payload_2["sessions"][0]["session_id"] == "session_older"


def test_privacy_export_and_delete_with_csrf(client, app, create_confirmed_user, login):
    user_id, email, password = create_confirmed_user()

    with app.app_context():
        db.session.add(
            UserChatHistory(
                user_id=user_id,
                session_id="privacy_session",
                title="Privacy Session",
                messages_data="[]",
            )
        )
        db.session.add(
            ChatShare(
                user_id=user_id,
                session_id="privacy_session",
                public_id="privacy_public",
                is_public=True,
            )
        )
        db.session.commit()

    unauth_export = client.get("/api/privacy/export")
    assert unauth_export.status_code == 401

    login_response = login(email, password)
    assert login_response.status_code == 200

    export_response = client.get("/api/privacy/export")
    assert export_response.status_code == 200
    exported = export_response.get_json()["data"]
    assert exported["user_id"] == user_id
    assert len(exported["chats"]) == 1
    assert len(exported["shares"]) == 1

    delete_without_csrf = client.post("/api/privacy/delete", json={"delete_account": False})
    assert delete_without_csrf.status_code == 403

    csrf_value = client.get("/health").headers.get("X-CSRF-Token")
    assert csrf_value

    delete_response = client.post(
        "/api/privacy/delete", json={"delete_account": False}, headers={"X-CSRF-Token": csrf_value}
    )
    assert delete_response.status_code == 200

    deleted_payload = delete_response.get_json()["deleted"]
    assert deleted_payload["user_id"] == user_id
    assert deleted_payload["items_deleted"]["chats"] == 1
    assert deleted_payload["items_deleted"]["chat_shares"] == 1

    with app.app_context():
        user_exists = db.session.get(User, user_id)
        chats_count = UserChatHistory.query.filter_by(user_id=user_id).count()
        shares_count = ChatShare.query.filter_by(user_id=user_id).count()
        assert user_exists is not None
        assert chats_count == 0
        assert shares_count == 0


def test_privacy_delete_account_removes_user_and_clears_session(
    client, app, create_confirmed_user, login
):
    user_id, email, password = create_confirmed_user(name="Delete Me")

    login_response = login(email, password)
    assert login_response.status_code == 200

    csrf_value = client.get("/health").headers.get("X-CSRF-Token")
    assert csrf_value

    delete_response = client.post(
        "/api/privacy/delete",
        json={"delete_account": True},
        headers={"X-CSRF-Token": csrf_value},
    )
    assert delete_response.status_code == 200
    deleted_payload = delete_response.get_json()["deleted"]
    assert deleted_payload["account_deleted"] is True

    with app.app_context():
        assert db.session.get(User, user_id) is None

    check_response = client.get("/api/auth/check")
    payload = check_response.get_json()
    assert payload["authenticated"] is False


def test_health_full_includes_component_checks(client):
    response = client.get("/health?full=true")
    assert response.status_code in (200, 503)

    payload = response.get_json()
    assert "status" in payload
    assert "uptime_seconds" in payload
    assert "latency_ms" in payload
    assert "checks" in payload
    assert "database" in payload["checks"]
    assert "storage" in payload["checks"]


def test_health_defaults_to_json_for_api_clients(client):
    response = client.get("/health")
    assert response.status_code in (200, 503)
    assert response.is_json is True


def test_health_returns_html_for_browser_accept(client):
    response = client.get("/health", headers={"Accept": "text/html"})
    assert response.status_code in (200, 503)
    assert "text/html" in response.headers.get("Content-Type", "")

    body = response.get_data(as_text=True)
    assert "Состояние сервиса ReMind" in body
    assert "Открыть JSON" in body
    assert "/health/index.css" in body


def test_health_stylesheet_is_available(client):
    response = client.get("/health/index.css")
    assert response.status_code == 200
    assert "text/css" in response.headers.get("Content-Type", "")
    body = response.get_data(as_text=True)
    assert ".health-page" in body


def test_images_route_serves_static_assets_under_images_prefix(client):
    response = client.get("/images/prompts/prompts.json")

    assert response.status_code == 200
    assert "application/json" in response.headers.get("Content-Type", "")
    payload = response.get_json()
    assert "prompts" in payload


def test_missing_generated_image_returns_404(client):
    response = client.get("/images/does-not-exist.png")

    assert response.status_code == 404
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "not_found"
