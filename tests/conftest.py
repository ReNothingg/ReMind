import os
import uuid

import pytest
from werkzeug.security import generate_password_hash

os.environ['FLASK_ENV'] = 'development'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['SECRET_KEY'] = 'pytest-secret-key'
os.environ['VALIDATE_USER_AGENT'] = 'False'
os.environ['TURNSTILE_SITE_KEY'] = ''
os.environ['TURNSTILE_SECRET_KEY'] = ''
os.environ['GOOGLE_CLIENT_ID'] = ''
os.environ['GOOGLE_CLIENT_SECRET'] = ''
os.environ['ALLOW_GUEST_CHATS_SAVE'] = 'True'

from app_factory import create_app
from utils.auth import User, UserSettings, db
from utils.input_validation import InputValidator


@pytest.fixture(autouse=True)
def disable_email_dns_validation(monkeypatch):
    monkeypatch.setattr(
        InputValidator,
        'validate_email',
        staticmethod(lambda value: str(value).strip().lower()),
    )


@pytest.fixture()
def app():
    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.drop_all()
        db.create_all()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def create_confirmed_user(app):
    def _create(email: str = None, password: str = 'Password1!', username: str = None):
        real_email = email or f"user_{uuid.uuid4().hex[:8]}@example.com"
        real_username = username or f"user_{uuid.uuid4().hex[:8]}"

        with app.app_context():
            user = User(
                username=real_username,
                email=real_email,
                password=generate_password_hash(password),
                is_confirmed=True,
            )
            db.session.add(user)
            db.session.commit()

            db.session.add(UserSettings(user_id=user.id))
            db.session.commit()

            return user.id, real_email, password

    return _create


@pytest.fixture()
def login(client):
    def _login(email: str, password: str):
        return client.post(
            '/api/auth/login',
            json={'email': email, 'password': password},
            headers={'User-Agent': 'Mozilla/5.0 (pytest)'}
        )

    return _login


@pytest.fixture()
def csrf_token(client):
    response = client.get('/health')
    return response.headers.get('X-CSRF-Token')
