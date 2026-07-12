import pytest
from flask import Blueprint, Flask

from routes.features.user_state import DRAFT_MAX_CHARS, register_user_state_routes
from routes.features.chat import _find_previous_delivery
from services.chat_history import normalize_message
from utils.auth import User, db


def _draft_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "test-only"
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    blueprint = Blueprint("draft_test", __name__)
    register_user_state_routes(blueprint)
    app.register_blueprint(blueprint)
    with app.app_context():
        db.create_all()
        db.session.add(User(id=1, username="user", email="user@example.com"))
        db.session.commit()
    return app


def test_draft_sync_uses_revision_to_prevent_silent_overwrite():
    app = _draft_app()
    with app.test_client() as client:
        with client.session_transaction() as flask_session:
            flask_session["user_id"] = 1

        saved = client.put(
            "/api/user/draft",
            json={"content": "first", "device_id": "device-a", "base_revision": 0},
        )
        conflict = client.put(
            "/api/user/draft",
            json={"content": "stale", "device_id": "device-b", "base_revision": 0},
        )

    assert saved.status_code == 200
    assert saved.get_json()["draft"]["revision"] == 1
    assert conflict.status_code == 409
    assert conflict.get_json()["draft"]["content"] == "first"


def test_draft_sync_rejects_oversized_content():
    app = _draft_app()
    with app.test_client() as client:
        with client.session_transaction() as flask_session:
            flask_session["user_id"] = 1
        response = client.put(
            "/api/user/draft",
            json={"content": "x" * (DRAFT_MAX_CHARS + 1), "device_id": "device-a"},
        )

    assert response.status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        ["not", "an", "object"],
        {"content": "draft", "device_id": "device-a", "session_id": "bad/session"},
        {"content": "draft", "device_id": "device-a", "base_revision": True},
    ],
)
def test_draft_sync_rejects_malformed_state(payload):
    app = _draft_app()
    with app.test_client() as client:
        with client.session_transaction() as flask_session:
            flask_session["user_id"] = 1
        response = client.put("/api/user/draft", json=payload)

    assert response.status_code == 400


def test_delivery_metadata_survives_history_normalization():
    message = normalize_message(
        {
            "role": "model",
            "parts": [{"text": "partial"}],
            "request_id": "request_123",
            "delivery_status": "interrupted",
        }
    )

    assert message["request_id"] == "request_123"
    assert message["delivery_status"] == "interrupted"


def test_previous_delivery_is_reused_by_request_id():
    delivery = _find_previous_delivery(
        [
            {"role": "user", "request_id": "request_123", "parts": [{"text": "hello"}]},
            {
                "role": "model",
                "request_id": "request_123",
                "delivery_status": "complete",
                "parts": [{"text": "world"}],
            },
        ],
        "request_123",
    )

    assert delivery is not None
    assert delivery["reply"] == "world"
    assert delivery["recovered"] is True
