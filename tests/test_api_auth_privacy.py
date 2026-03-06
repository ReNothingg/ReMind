import json
from datetime import datetime, timedelta

import pytest

import utils.auth as auth_module
from config import SESSION_COOKIE_NAME
from utils.auth import ChatShare, User, UserChatHistory, db
from utils.session_security import resolve_cookie_domain


def test_api_auth_login_and_check(client, create_confirmed_user, login):
    user_id, email, password = create_confirmed_user()

    login_response = login(email, password)
    assert login_response.status_code == 200

    payload = login_response.get_json()
    assert payload['message'] == 'Успешный вход'
    assert payload['user']['id'] == user_id

    check_response = client.get('/api/auth/check')
    assert check_response.status_code == 200
    check_payload = check_response.get_json()
    assert check_payload['authenticated'] is True
    assert check_payload['user']['id'] == user_id


def test_api_login_wrong_password_for_argon2_hash_returns_401(client, app):
    try:
        from argon2 import PasswordHasher
    except ImportError:
        pytest.skip('argon2 is not installed')

    with app.app_context():
        user = User(
            username='argon-user',
            email='argon@example.com',
            password=PasswordHasher().hash('Password1!'),
            is_confirmed=True,
        )
        db.session.add(user)
        db.session.commit()

    response = client.post(
        '/api/auth/login',
        json={'email': 'argon@example.com', 'password': 'WrongPassword1!'},
        headers={'User-Agent': 'Mozilla/5.0 (pytest)'}
    )

    assert response.status_code == 401
    payload = response.get_json()
    assert 'email' in payload['error']


def test_resolve_cookie_domain_uses_host_only_cookies_for_local_requests():
    assert resolve_cookie_domain('.synvexai.com', '127.0.0.1:5000') is None
    assert resolve_cookie_domain('.synvexai.com', 'chat.synvexai.com') == '.synvexai.com'


def test_login_google_uses_host_only_cookies_on_local_host(client, monkeypatch):
    class FakeGoogleClient:
        def create_authorization_url(self, redirect_uri):
            self.redirect_uri = redirect_uri
            return {
                'url': 'https://accounts.google.com/o/oauth2/v2/auth?state=test-state',
                'state': 'test-state',
            }

        def save_authorize_data(self, **kwargs):
            self.saved = kwargs

    monkeypatch.setattr(auth_module.oauth, 'google', FakeGoogleClient(), raising=False)

    response = client.get(
        '/login/google?redirect_to=/health',
        base_url='http://127.0.0.1:5000',
        headers={'User-Agent': 'Mozilla/5.0 (pytest)'}
    )

    assert response.status_code == 302
    assert response.headers['Location'].startswith('https://accounts.google.com/')

    cookies = response.headers.getlist('Set-Cookie')
    session_cookie = next(cookie for cookie in cookies if cookie.startswith(f'{SESSION_COOKIE_NAME}='))
    fallback_cookie = next(cookie for cookie in cookies if cookie.startswith('oauth_state_fallback='))
    assert 'Domain=' not in session_cookie
    assert 'Domain=' not in fallback_cookie


def test_normalize_redirect_target_keeps_redirects_relative():
    allowed_hosts = ['chat.synvexai.com']

    assert auth_module._normalize_redirect_target('/health?tab=1', allowed_hosts) == '/health?tab=1'
    assert (
        auth_module._normalize_redirect_target(
            'https://chat.synvexai.com/health?tab=1',
            allowed_hosts,
        )
        == '/health?tab=1'
    )
    assert auth_module._normalize_redirect_target('https://evil.example/phish', allowed_hosts) == ''


def test_login_google_callback_error_redirect_drops_provider_query_params(client, monkeypatch):
    class FailingGoogleClient:
        def authorize_access_token(self):
            raise RuntimeError('forced oauth failure')

    monkeypatch.setattr(auth_module.oauth, 'google', FailingGoogleClient(), raising=False)

    response = client.get(
        '/login/google/callback?error=access_denied&error_description=https%3A%2F%2Fevil.example',
        headers={'User-Agent': 'Mozilla/5.0 (pytest)'}
    )

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')
    assert 'error=' not in response.headers['Location']


def test_chat_echo_as_guest_returns_reply_and_request_id(client):
    response = client.post('/chat', json={'message': 'hello from pytest', 'model': 'echo'})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['ok'] is True
    assert payload['reply'] == 'hello from pytest'
    assert response.headers.get('X-Request-Id')


def test_list_sessions_paginated_with_public_share(client, app, create_confirmed_user, login):
    user_id, email, password = create_confirmed_user()

    with app.app_context():
        older = UserChatHistory(
            user_id=user_id,
            session_id='session_older',
            title='Old title',
            messages_data=json.dumps([
                {'role': 'user', 'parts': [{'text': 'old message'}]}
            ]),
            created_at=datetime.utcnow() - timedelta(days=1),
            updated_at=datetime.utcnow() - timedelta(days=1),
        )
        newer = UserChatHistory(
            user_id=user_id,
            session_id='session_newer',
            title='New title',
            messages_data=json.dumps([
                {'role': 'user', 'parts': [{'text': 'new message'}]}
            ]),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.session.add_all([older, newer])
        db.session.add(
            ChatShare(
                user_id=user_id,
                session_id='session_newer',
                public_id='public_newer',
                is_public=True,
            )
        )
        db.session.commit()

    login_response = login(email, password)
    assert login_response.status_code == 200

    page_1 = client.get('/sessions?page=1&page_size=1')
    assert page_1.status_code == 200
    payload_1 = page_1.get_json()

    assert payload_1['ok'] is True
    assert payload_1['page'] == 1
    assert payload_1['page_size'] == 1
    assert payload_1['total'] == 2
    assert payload_1['has_more'] is True
    assert len(payload_1['sessions']) == 1
    assert payload_1['sessions'][0]['session_id'] == 'session_newer'
    assert payload_1['sessions'][0]['is_public'] is True
    assert payload_1['sessions'][0]['public_id'] == 'public_newer'

    page_2 = client.get('/sessions?page=2&page_size=1')
    payload_2 = page_2.get_json()
    assert payload_2['page'] == 2
    assert payload_2['has_more'] is False
    assert payload_2['sessions'][0]['session_id'] == 'session_older'


def test_privacy_export_and_delete_with_csrf(client, app, create_confirmed_user, login):
    user_id, email, password = create_confirmed_user()

    with app.app_context():
        db.session.add(
            UserChatHistory(
                user_id=user_id,
                session_id='privacy_session',
                title='Privacy Session',
                messages_data='[]',
            )
        )
        db.session.add(
            ChatShare(
                user_id=user_id,
                session_id='privacy_session',
                public_id='privacy_public',
                is_public=True,
            )
        )
        db.session.commit()

    unauth_export = client.get('/api/privacy/export')
    assert unauth_export.status_code == 401

    login_response = login(email, password)
    assert login_response.status_code == 200

    export_response = client.get('/api/privacy/export')
    assert export_response.status_code == 200
    exported = export_response.get_json()['data']
    assert exported['user_id'] == user_id
    assert len(exported['chats']) == 1
    assert len(exported['shares']) == 1

    delete_without_csrf = client.post('/api/privacy/delete', json={'delete_account': False})
    assert delete_without_csrf.status_code == 403

    csrf_value = client.get('/health').headers.get('X-CSRF-Token')
    assert csrf_value

    delete_response = client.post(
        '/api/privacy/delete',
        json={'delete_account': False},
        headers={'X-CSRF-Token': csrf_value}
    )
    assert delete_response.status_code == 200

    deleted_payload = delete_response.get_json()['deleted']
    assert deleted_payload['user_id'] == user_id
    assert deleted_payload['items_deleted']['chats'] == 1
    assert deleted_payload['items_deleted']['chat_shares'] == 1

    with app.app_context():
        user_exists = User.query.get(user_id)
        chats_count = UserChatHistory.query.filter_by(user_id=user_id).count()
        shares_count = ChatShare.query.filter_by(user_id=user_id).count()
        assert user_exists is not None
        assert chats_count == 0
        assert shares_count == 0


def test_health_full_includes_component_checks(client):
    response = client.get('/health?full=true')
    assert response.status_code in (200, 503)

    payload = response.get_json()
    assert 'status' in payload
    assert 'uptime_seconds' in payload
    assert 'latency_ms' in payload
    assert 'checks' in payload
    assert 'database' in payload['checks']
    assert 'storage' in payload['checks']


def test_health_defaults_to_json_for_api_clients(client):
    response = client.get('/health')
    assert response.status_code in (200, 503)
    assert response.is_json is True


def test_health_returns_html_for_browser_accept(client):
    response = client.get('/health', headers={'Accept': 'text/html'})
    assert response.status_code in (200, 503)
    assert 'text/html' in response.headers.get('Content-Type', '')

    body = response.get_data(as_text=True)
    assert 'Состояние сервиса ReMind' in body
    assert 'Открыть JSON' in body
    assert '/health/index.css' in body


def test_health_stylesheet_is_available(client):
    response = client.get('/health/index.css')
    assert response.status_code == 200
    assert 'text/css' in response.headers.get('Content-Type', '')
    body = response.get_data(as_text=True)
    assert '.health-page' in body


def test_images_route_serves_static_assets_under_images_prefix(client):
    response = client.get('/images/prompts/prompts.json')

    assert response.status_code == 200
    assert 'application/json' in response.headers.get('Content-Type', '')
    payload = response.get_json()
    assert 'prompts' in payload


def test_missing_generated_image_returns_404(client):
    response = client.get('/images/does-not-exist.png')

    assert response.status_code == 404
    payload = response.get_json()
    assert payload['ok'] is False
    assert payload['error']['code'] == 'not_found'
