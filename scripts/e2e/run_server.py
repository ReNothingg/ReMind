#!/usr/bin/env python3
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / 'database' / 'e2e_users.db'

os.environ['FLASK_ENV'] = 'development'
os.environ['VALIDATE_USER_AGENT'] = 'False'
os.environ['TURNSTILE_SITE_KEY'] = ''
os.environ['TURNSTILE_SECRET_KEY'] = ''
os.environ['GOOGLE_CLIENT_ID'] = ''
os.environ['GOOGLE_CLIENT_SECRET'] = ''
os.environ['ALLOW_GUEST_CHATS_SAVE'] = 'True'
os.environ['DATABASE_URL'] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ['SECRET_KEY'] = 'e2e-secret-key'

from app_factory import create_app
from utils.auth import User, UserSettings, db
from werkzeug.security import generate_password_hash


def seed_e2e_user(app):
    with app.app_context():
        db.create_all()
        email = 'e2e@example.com'
        user = User.query.filter_by(email=email).first()
        if user is None:
            user = User(
                username='e2e_user',
                email=email,
                password=generate_password_hash('Password1!'),
                is_confirmed=True,
            )
            db.session.add(user)
            db.session.commit()

        settings = UserSettings.query.filter_by(user_id=user.id).first()
        if settings is None:
            db.session.add(UserSettings(user_id=user.id))
            db.session.commit()


if __name__ == '__main__':
    app = create_app()
    seed_e2e_user(app)
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
