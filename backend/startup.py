from __future__ import annotations

from backend.auth.identities import backfill_legacy_identities
from backend.auth.oauth import oauth
from backend.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from backend.db.bootstrap import configure_sqlite, initialize_schema, remove_legacy_default_minds
from backend.db.models import db


def initialize_app_services(app):
    db.init_app(app)
    oauth.init_app(app)
    configure_sqlite(app)

    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
        app.logger.info(f"Registering Google OAuth with client_id: {GOOGLE_CLIENT_ID[:20]}...")
        oauth.register(
            name="google",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            access_token_url="https://oauth2.googleapis.com/token",
            api_base_url="https://openidconnect.googleapis.com/v1/",
            client_kwargs={"scope": "openid email profile"},
            authorize_params={"access_type": "offline", "prompt": "consent"},
        )
        app.logger.info("Google OAuth registered successfully")
    with app.app_context():
        initialize_schema(app)
        backfill_legacy_identities(app)
        remove_legacy_default_minds(app)
        app.logger.info("Database tables created successfully")
