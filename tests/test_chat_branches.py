import io
import time

import pytest
from flask import Blueprint, Flask

import routes.features.chat as chat_routes
import routes.features.sessions as session_routes
import services.chat_history as chat_history
import services.files as file_services
from routes.features.sessions import register_session_routes
from services.chat_history import (
    _apply_chat_operation,
    _select_variant_in_graph,
    ensure_conversation_graph,
    materialize_conversation_history,
)
from utils.auth import ChatShare, User, UserChatHistory, db
from utils.csrf_protection import add_csrf_token_to_response, setup_csrf_protection


def _message(message_id: str, role: str, text: str, request_id: str | None = None) -> dict:
    message = {
        "id": message_id,
        "role": role,
        "parts": [{"text": text}],
        "timestamp": 1,
    }
    if request_id:
        message["request_id"] = request_id
    return message


def _texts(history: list[dict]) -> list[str]:
    return [message["parts"][0]["text"] for message in history]


def test_legacy_consecutive_assistant_messages_become_persisted_variants():
    legacy = [
        _message("u1", "user", "Question"),
        _message("a1", "model", "First answer"),
        _message("a2", "model", "Regenerated answer"),
    ]

    history = materialize_conversation_history(legacy)

    assert _texts(history) == ["Question", "Regenerated answer"]
    assert [variant["id"] for variant in history[1]["variants"]] == ["a1", "a2"]
    assert history[1]["current_variant_index"] == 1


def test_regeneration_creates_sibling_and_switching_restores_its_subtree():
    graph: list[dict] = []
    graph = _apply_chat_operation(
        graph,
        operation="send",
        target_message_id=None,
        parent_message_id=None,
        user_message=_message("u1", "user", "Question", "r1"),
        model_message=_message("a1", "model", "First", "r1"),
    )
    graph = _apply_chat_operation(
        graph,
        operation="send",
        target_message_id=None,
        parent_message_id="a1",
        user_message=_message("u2", "user", "Follow-up", "r2"),
        model_message=_message("a2", "model", "Follow-up answer", "r2"),
    )
    graph = _apply_chat_operation(
        graph,
        operation="regenerate",
        target_message_id="a1",
        parent_message_id="u1",
        user_message=None,
        model_message=_message("a1b", "model", "Alternative", "r3"),
    )

    assert _texts(materialize_conversation_history(graph)) == ["Question", "Alternative"]

    graph = _select_variant_in_graph(graph, "a2")
    assert _texts(materialize_conversation_history(graph)) == [
        "Question",
        "First",
        "Follow-up",
        "Follow-up answer",
    ]


def test_edit_creates_user_branch_without_destroying_original_conversation():
    graph = ensure_conversation_graph(
        [
            _message("u1", "user", "Original"),
            _message("a1", "model", "Original answer"),
            _message("u2", "user", "Continue"),
            _message("a2", "model", "Continuation"),
        ]
    )
    graph = _apply_chat_operation(
        graph,
        operation="edit",
        target_message_id="u1",
        parent_message_id=None,
        user_message=_message("u1b", "user", "Edited", "edit-request"),
        model_message=_message("a1b", "model", "Edited answer", "edit-request"),
    )

    assert _texts(materialize_conversation_history(graph)) == ["Edited", "Edited answer"]

    graph = _select_variant_in_graph(graph, "u1")
    assert _texts(materialize_conversation_history(graph)) == [
        "Original",
        "Original answer",
        "Continue",
        "Continuation",
    ]


def test_request_id_makes_chat_operation_idempotent():
    graph = _apply_chat_operation(
        [],
        operation="send",
        target_message_id=None,
        parent_message_id=None,
        user_message=_message("u1", "user", "Question", "same-request"),
        model_message=_message("a1", "model", "Answer", "same-request"),
    )
    replayed = _apply_chat_operation(
        graph,
        operation="send",
        target_message_id=None,
        parent_message_id=None,
        user_message=_message("u1-copy", "user", "Question", "same-request"),
        model_message=_message("a1-copy", "model", "Answer", "same-request"),
    )

    assert len(replayed) == 2


def test_client_cannot_reuse_an_existing_message_id_for_a_new_operation():
    graph = _apply_chat_operation(
        [],
        operation="send",
        target_message_id=None,
        parent_message_id=None,
        user_message=_message("u1", "user", "Question", "first-request"),
        model_message=_message("a1", "model", "Answer", "first-request"),
    )

    with pytest.raises(ValueError, match="message_id_conflict"):
        _apply_chat_operation(
            graph,
            operation="regenerate",
            target_message_id="a1",
            parent_message_id="u1",
            user_message=None,
            model_message=_message("a1", "model", "Tampered", "second-request"),
        )


def test_variant_limit_is_enforced_inside_atomic_graph_update(monkeypatch):
    monkeypatch.setattr(chat_history, "CHAT_MAX_VARIANTS_PER_TURN", 2)
    graph = _apply_chat_operation(
        [],
        operation="send",
        target_message_id=None,
        parent_message_id=None,
        user_message=_message("u1", "user", "Question", "request-one"),
        model_message=_message("a1", "model", "First", "request-one"),
    )
    graph = _apply_chat_operation(
        graph,
        operation="regenerate",
        target_message_id="a1",
        parent_message_id="u1",
        user_message=None,
        model_message=_message("a2", "model", "Second", "request-two"),
    )

    with pytest.raises(ValueError, match="chat_variant_limit_reached"):
        _apply_chat_operation(
            graph,
            operation="regenerate",
            target_message_id="a2",
            parent_message_id="u1",
            user_message=None,
            model_message=_message("a3", "model", "Third", "request-three"),
        )


def _session_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "test-only"
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    blueprint = Blueprint("chat_branch_routes", __name__)
    register_session_routes(blueprint)
    app.register_blueprint(blueprint)
    with app.app_context():
        db.create_all()
        db.session.add(User(id=42, username="branch-user", email="branch@example.com"))
        chat = UserChatHistory(user_id=42, session_id="session-1", title="Branch test")
        chat.set_messages(
            [
                _message("u1", "user", "Question"),
                _message("a1", "model", "First"),
                _message("a2", "model", "Second"),
            ]
        )
        db.session.add(chat)
        db.session.commit()
    return app


def test_session_history_repairs_legacy_duplicates_and_persists_selection():
    app = _session_app()
    with app.test_client() as client:
        with client.session_transaction() as flask_session:
            flask_session["user_id"] = 42

        initial = client.get("/sessions/session-1/history")
        switched = client.put(
            "/sessions/session-1/branch",
            json={"message_id": "a1"},
        )
        reloaded = client.get("/sessions/session-1/history")

    assert initial.status_code == 200
    assert _texts(initial.get_json()["history"]) == ["Question", "Second"]
    assert len(initial.get_json()["history"][1]["variants"]) == 2
    assert switched.status_code == 200
    assert _texts(switched.get_json()["history"]) == ["Question", "First"]
    assert _texts(reloaded.get_json()["history"]) == ["Question", "First"]


def test_branch_selection_enforces_object_ownership():
    app = _session_app()
    with app.app_context():
        db.session.add(User(id=43, username="other-user", email="other@example.com"))
        db.session.commit()

    with app.test_client() as client:
        with client.session_transaction() as flask_session:
            flask_session["user_id"] = 43
        response = client.put(
            "/sessions/session-1/branch",
            json={"message_id": "a1"},
        )

    assert response.status_code == 404
    with app.app_context():
        chat = UserChatHistory.query.filter_by(user_id=42, session_id="session-1").one()
        assert _texts(materialize_conversation_history(chat.get_messages())) == [
            "Question",
            "Second",
        ]


def test_authenticated_branch_selection_requires_csrf_token():
    app = _session_app()
    setup_csrf_protection(app)
    app.after_request(add_csrf_token_to_response)

    with app.test_client() as client:
        with client.session_transaction() as flask_session:
            flask_session["user_id"] = 42
        bootstrap = client.get("/sessions/session-1/history")
        csrf_token = bootstrap.headers["X-CSRF-Token"]
        rejected = client.put(
            "/sessions/session-1/branch",
            json={"message_id": "a1"},
        )
        accepted = client.put(
            "/sessions/session-1/branch",
            json={"message_id": "a1"},
            headers={"X-CSRF-Token": csrf_token},
        )

    assert rejected.status_code == 403
    assert rejected.get_json()["error"]["code"] == "csrf_validation_failed"
    assert accepted.status_code == 200


def test_public_chat_does_not_expose_hidden_prompt_or_response_variants():
    app = _session_app()
    with app.app_context():
        db.session.add(
            ChatShare(
                user_id=42,
                session_id="session-1",
                public_id="public-branch",
                is_public=True,
            )
        )
        db.session.commit()

    with app.test_client() as client:
        response = client.get("/sessions/public-branch/history")

    assert response.status_code == 200
    history = response.get_json()["history"]
    assert _texts(history) == ["Question", "Second"]
    assert all("variants" not in message for message in history)
    assert "First" not in response.get_data(as_text=True)


def test_guest_can_delete_its_own_token_protected_chat(monkeypatch, tmp_path):
    app = _session_app()
    monkeypatch.setattr(chat_history, "CHATS_FOLDER", tmp_path)
    monkeypatch.setattr(chat_history, "ALLOW_GUEST_CHATS_SAVE", True)
    monkeypatch.setattr(session_routes, "ALLOW_GUEST_CHATS_SAVE", True)
    chat_history.write_chat_file(
        "guest-session",
        {"session_id": "guest-session", "history": [], "title": "Guest"},
    )
    token = chat_history._generate_guest_session_token("guest-session", int(time.time()))

    with app.test_client() as client:
        response = client.delete(
            "/sessions/guest-session",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 204
    assert not (tmp_path / "guest-session.json").exists()


def test_guest_cannot_mutate_a_chat_with_the_wrong_token(monkeypatch, tmp_path):
    app = _session_app()
    monkeypatch.setattr(chat_history, "CHATS_FOLDER", tmp_path)
    monkeypatch.setattr(chat_history, "ALLOW_GUEST_CHATS_SAVE", True)
    monkeypatch.setattr(session_routes, "ALLOW_GUEST_CHATS_SAVE", True)
    chat_history.write_chat_file(
        "guest-session",
        {
            "session_id": "guest-session",
            "history": [
                _message("guest-u1", "user", "Private question"),
                _message("guest-a1", "model", "Private answer"),
            ],
            "title": "Guest",
        },
    )
    wrong_token = chat_history._generate_guest_session_token(
        "different-session", int(time.time())
    )

    with app.test_client() as client:
        branch_response = client.put(
            "/sessions/guest-session/branch",
            json={"message_id": "guest-a1"},
            headers={"Authorization": f"Bearer {wrong_token}"},
        )
        delete_response = client.delete(
            "/sessions/guest-session",
            headers={"Authorization": f"Bearer {wrong_token}"},
        )

    assert branch_response.status_code == 401
    assert delete_response.status_code == 401
    assert (tmp_path / "guest-session.json").exists()


def test_chat_endpoint_regeneration_persists_one_turn_with_two_variants(
    monkeypatch, tmp_path
):
    app = Flask(__name__)
    app.secret_key = "test-only"
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    blueprint = Blueprint("chat_operation_routes", __name__)
    chat_routes.register_chat_routes(blueprint)
    app.register_blueprint(blueprint)
    with app.app_context():
        db.create_all()
        db.session.add(User(id=77, username="chat-user", email="chat@example.com"))
        db.session.commit()

    model_calls: list[str] = []
    model_files: list[list[dict]] = []

    def fake_model(_user_id, data):
        model_calls.append(str(data.get("operation") or ""))
        model_files.append(list(data.get("files") or []))
        yield "Reply to " + str(data.get("message") or "")

    monkeypatch.setattr(chat_routes, "model_exists", lambda _model: True)
    monkeypatch.setattr(chat_routes, "can_user_access_model", lambda _model, _user: True)
    monkeypatch.setattr(chat_routes, "get_model_function", lambda _model: fake_model)
    monkeypatch.setattr(file_services, "UPLOAD_FOLDER", tmp_path)

    # The stream owns an application context while it is consumed. Keeping the
    # test client's preserve-context manager open would make Flask pop that
    # nested context out of order, which is unrelated to the HTTP behaviour.
    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = 77
    first = client.post(
        "/chat",
        data={
            "message": "Question",
            "session_id": "session-chat",
            "operation": "send",
            "user_message_id": "u1",
            "assistant_message_id": "a1",
            "request_id": "request_one",
            "attachment": (io.BytesIO(b"attachment context"), "notes.txt"),
        },
        content_type="multipart/form-data",
    )
    first.get_data()
    regenerated = client.post(
        "/chat",
        json={
            "message": "client text is ignored for canonical regeneration",
            "session_id": "session-chat",
            "operation": "regenerate",
            "target_message_id": "a1",
            "assistant_message_id": "a2",
            "request_id": "request_two",
        },
    )
    regenerated.get_data()
    conflict = client.post(
        "/chat",
        json={
            "message": "Question",
            "session_id": "session-chat",
            "operation": "regenerate",
            "target_message_id": "a2",
            "assistant_message_id": "a1",
            "request_id": "request_conflict",
        },
    )
    monkeypatch.setattr(chat_routes, "CHAT_MAX_VARIANTS_PER_TURN", 2)
    limited = client.post(
        "/chat",
        json={
            "message": "Question",
            "session_id": "session-chat",
            "operation": "regenerate",
            "target_message_id": "a2",
            "assistant_message_id": "a3",
            "request_id": "request_limited",
        },
    )

    assert first.status_code == 200
    assert regenerated.status_code == 200
    assert conflict.status_code == 409
    assert conflict.get_json()["error"]["code"] == "message_id_conflict"
    assert limited.status_code == 409
    assert limited.get_json()["error"]["code"] == "chat_variant_limit_reached"
    assert model_calls == ["send", "regenerate"]
    assert "attachment context" in model_files[1][0]["model_part"]["text"]
    with app.app_context():
        chat = UserChatHistory.query.filter_by(user_id=77, session_id="session-chat").one()
        graph = chat.get_messages()
        history = materialize_conversation_history(graph)
    assert len(graph) == 3
    assert _texts(history) == ["Question", "Reply to Question"]
    assert [variant["id"] for variant in history[1]["variants"]] == ["a1", "a2"]

    with app.app_context():
        db.session.add(User(id=78, username="other-chat-user", email="other-chat@example.com"))
        db.session.add(
            ChatShare(
                user_id=77,
                session_id="session-chat",
                public_id="shared-chat-id",
                is_public=True,
            )
        )
        db.session.commit()
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = 78
    public_write = client.post(
        "/chat",
        json={
            "message": "tamper",
            "session_id": "shared-chat-id",
            "operation": "send",
            "user_message_id": "other-u1",
            "assistant_message_id": "other-a1",
            "request_id": "public_write_request",
        },
    )
    with app.app_context():
        share = ChatShare.query.filter_by(public_id="shared-chat-id").one()
        share.is_public = False
        db.session.commit()
    private_write = client.post(
        "/chat",
        json={
            "message": "tamper",
            "session_id": "shared-chat-id",
            "operation": "send",
            "user_message_id": "other-u2",
            "assistant_message_id": "other-a2",
            "request_id": "private_write_request",
        },
    )

    assert public_write.status_code == 403
    assert public_write.get_json()["error"]["code"] == "chat_read_only"
    assert private_write.status_code == 404
    assert private_write.get_json()["error"]["code"] == "not_found"
    assert model_calls == ["send", "regenerate"]


def test_temporary_chat_attachments_are_not_left_on_disk(monkeypatch, tmp_path):
    app = Flask(__name__)
    app.secret_key = "test-only"
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    blueprint = Blueprint("temporary_chat_routes", __name__)
    chat_routes.register_chat_routes(blueprint)
    app.register_blueprint(blueprint)
    with app.app_context():
        db.create_all()
        db.session.add(User(id=88, username="temporary-user", email="temp@example.com"))
        db.session.commit()

    received_files: list[list[dict]] = []

    def fake_model(_user_id, data):
        received_files.append(list(data.get("files") or []))
        yield "Temporary answer"

    monkeypatch.setattr(chat_routes, "model_exists", lambda _model: True)
    monkeypatch.setattr(chat_routes, "can_user_access_model", lambda _model, _user: True)
    monkeypatch.setattr(chat_routes, "get_model_function", lambda _model: fake_model)
    monkeypatch.setattr(file_services, "UPLOAD_FOLDER", tmp_path)
    monkeypatch.setattr(chat_routes, "UPLOAD_FOLDER", tmp_path)

    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = 88
    response = client.post(
        "/chat",
        data={
            "message": "Review",
            "session_id": "temporary-session",
            "temporary_chat": "true",
            "operation": "send",
            "user_message_id": "temporary-u1",
            "assistant_message_id": "temporary-a1",
            "request_id": "temporary_request",
            "attachment": (io.BytesIO(b"temporary attachment"), "notes.txt"),
        },
        content_type="multipart/form-data",
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "temporary attachment" in received_files[0][0]["model_part"]["text"]
    assert '"uploaded_files": []' in body
    assert list(tmp_path.iterdir()) == []
    with app.app_context():
        assert UserChatHistory.query.filter_by(
            user_id=88, session_id="temporary-session"
        ).first() is None


def test_regeneration_rejects_new_uploads_before_writing_them(monkeypatch, tmp_path):
    app = Flask(__name__)
    app.secret_key = "test-only"
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    blueprint = Blueprint("regeneration_upload_routes", __name__)
    chat_routes.register_chat_routes(blueprint)
    app.register_blueprint(blueprint)
    with app.app_context():
        db.create_all()
        db.session.add(User(id=89, username="regen-user", email="regen@example.com"))
        db.session.commit()

    monkeypatch.setattr(file_services, "UPLOAD_FOLDER", tmp_path)
    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["user_id"] = 89
    response = client.post(
        "/chat",
        data={
            "message": "Question",
            "session_id": "regeneration-session",
            "operation": "regenerate",
            "target_message_id": "a1",
            "assistant_message_id": "a2",
            "request_id": "regeneration_request",
            "attachment": (io.BytesIO(b"must not be stored"), "notes.txt"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "regenerate_attachments_not_allowed"
    assert list(tmp_path.iterdir()) == []
