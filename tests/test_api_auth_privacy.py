import json
from datetime import datetime, timedelta

from utils.auth import ChatShare, User, UserChatHistory, db


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
