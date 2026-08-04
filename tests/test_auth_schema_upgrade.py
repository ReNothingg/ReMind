from __future__ import annotations

from flask import Flask
from sqlalchemy import create_engine, inspect, text

from utils.auth import AuthIdentity, db, setup_auth


def test_legacy_user_columns_are_added_before_identity_backfill(tmp_path):
    database_path = tmp_path / "legacy-users.db"
    database_url = f"sqlite:///{database_path}"
    legacy_engine = create_engine(database_url)
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                'CREATE TABLE "user" ('
                "id INTEGER PRIMARY KEY, "
                "username VARCHAR(50) NOT NULL, "
                "email VARCHAR(100) NOT NULL UNIQUE, "
                "password VARCHAR(200), "
                "is_confirmed BOOLEAN, "
                "confirmation_token VARCHAR(100), "
                "confirmation_token_expires DATETIME, "
                "reset_token VARCHAR(100), "
                "reset_token_expires DATETIME, "
                "created_at DATETIME, "
                "oauth_provider VARCHAR(20), "
                "oauth_id VARCHAR(100)"
                ")"
            )
        )
        connection.execute(
            text(
                'INSERT INTO "user" '
                "(id, username, email, is_confirmed, oauth_provider, oauth_id) "
                "VALUES (1, 'legacy', 'legacy@example.com', TRUE, 'telegram', '123456789')"
            )
        )
    legacy_engine.dispose()

    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SECRET_KEY="schema-upgrade-test-secret",
    )

    setup_auth(app)

    with app.app_context():
        user_columns = {column["name"] for column in inspect(db.engine).get_columns("user")}
        assert {
            "name",
            "is_admin",
            "is_banned",
            "is_blocked",
            "moderation_reason",
            "ban_reason",
            "block_reason",
            "banned_until",
            "blocked_until",
        }.issubset(user_columns)
        identity = AuthIdentity.query.one()
        assert identity.user_id == 1
        assert identity.provider == "telegram"
        assert identity.provider_user_id == "123456789"
