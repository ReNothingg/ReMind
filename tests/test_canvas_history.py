from services.chat_history import replace_canvas_textdoc_in_messages
from flask import Blueprint, Flask
from types import SimpleNamespace

import routes.features.sessions as session_routes


def _textdoc(content: str, textdoc_id: str = "canvas-1") -> dict:
    return {
        "id": textdoc_id,
        "name": "index.html",
        "type": "code/html",
        "content": content,
        "comments": [],
        "updated_at": 1,
    }


def test_replace_canvas_textdoc_updates_only_the_newest_matching_message():
    messages = [
        {"role": "model", "canvas_textdoc": _textdoc("old")},
        {"role": "model", "canvas_textdoc": _textdoc("current")},
    ]

    updated, saved = replace_canvas_textdoc_in_messages(messages, _textdoc("edited"))

    assert saved is not None
    assert updated[0]["canvas_textdoc"]["content"] == "old"
    assert updated[1]["canvas_textdoc"]["content"] == "edited"


def test_replace_canvas_textdoc_updates_matching_variant_and_canvas_event():
    messages = [{
        "role": "model",
        "variants": [{"canvasTextdoc": _textdoc("variant")}],
        "canvas_updates": [{"action": "create", "textdoc": _textdoc("event")}],
    }]

    updated, saved = replace_canvas_textdoc_in_messages(messages, _textdoc("edited"))

    assert saved is not None
    assert updated[0]["variants"][0]["canvasTextdoc"]["content"] == "edited"
    assert updated[0]["canvas_updates"][0]["textdoc"]["content"] == "edited"


def test_replace_canvas_textdoc_rejects_unknown_document():
    messages = [{"role": "model", "canvas_textdoc": _textdoc("current")}]

    updated, saved = replace_canvas_textdoc_in_messages(
        messages,
        {
            "id": "unknown",
            "name": "other.html",
            "type": "code/html",
            "content": "edited",
        },
    )

    assert saved is None
    assert updated == messages


def _session_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "test-only"
    blueprint = Blueprint("session_test", __name__)
    session_routes.register_session_routes(blueprint)
    app.register_blueprint(blueprint)
    return app


def test_canvas_save_rejects_a_non_owner_of_a_shared_session(monkeypatch):
    app = _session_app()
    monkeypatch.setattr(
        session_routes,
        "resolve_session_identifier",
        lambda _value: ("private-session", SimpleNamespace(user_id=7)),
    )
    save = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not save"))
    monkeypatch.setattr(session_routes, "save_canvas_textdoc_to_history", save)

    with app.test_client() as client:
        with client.session_transaction() as flask_session:
            flask_session["user_id"] = 8
        response = client.put(
            "/sessions/public-id/canvas",
            json={"textdoc": _textdoc("edited")},
        )

    assert response.status_code == 404


def test_canvas_save_requires_the_guest_session_token(monkeypatch):
    app = _session_app()
    monkeypatch.setattr(session_routes, "ALLOW_GUEST_CHATS_SAVE", True)
    monkeypatch.setattr(
        session_routes,
        "resolve_session_identifier",
        lambda _value: ("guest-session", None),
    )
    monkeypatch.setattr(session_routes, "chat_file_exists", lambda _value: True)
    monkeypatch.setattr(session_routes, "has_valid_guest_session_token", lambda _value: False)

    with app.test_client() as client:
        response = client.put(
            "/sessions/guest-session/canvas",
            json={"textdoc": _textdoc("edited")},
        )

    assert response.status_code == 401


def test_canvas_save_rejects_oversized_content_before_persistence(monkeypatch):
    app = _session_app()
    save = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not save"))
    monkeypatch.setattr(session_routes, "save_canvas_textdoc_to_history", save)

    oversized = _textdoc("x" * (session_routes.MAX_TEXTDOC_CONTENT_LENGTH + 1))
    with app.test_client() as client:
        response = client.put("/sessions/any/canvas", json={"textdoc": oversized})

    assert response.status_code == 400
