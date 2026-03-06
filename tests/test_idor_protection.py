import json

from flask import session

from utils.auth import ChatShare, UserChatHistory, db
from utils.idor_protection import (
    add_ownership_filter,
    check_resource_ownership,
    require_auth,
    verify_resource_access,
)


def test_require_auth_blocks_unauthenticated_requests(app):
    @require_auth
    def protected():
        return "ok"

    with app.test_request_context("/resource"):
        response, status = protected()

    assert status == 401
    assert response.get_json()["error"]["code"] == "auth_required"


def test_require_auth_allows_authenticated_requests(app):
    @require_auth
    def protected():
        return "ok"

    with app.test_request_context("/resource"):
        session["user_id"] = 7
        result = protected()

    assert result == "ok"


def test_check_resource_ownership_covers_auth_session_and_missing_id(app):
    @check_resource_ownership("chat")
    def protected(**_kwargs):
        return "ok"

    with app.test_request_context("/chat"):
        response, status = protected()
    assert status == 401
    assert response.get_json()["error"]["code"] == "auth_required"

    with app.test_request_context("/chat"):
        session["user_id"] = "not-an-int"
        response, status = protected()
    assert status == 401
    assert response.get_json()["error"]["code"] == "invalid_session"

    with app.test_request_context("/chat"):
        session["user_id"] = 3
        response, status = protected()
    assert status == 400
    assert response.get_json()["error"]["code"] == "missing_resource_id"


def test_check_resource_ownership_allows_owned_chat_and_chat_share(app, create_confirmed_user):
    user_id, _, _ = create_confirmed_user()

    with app.app_context():
        db.session.add(
            UserChatHistory(
                user_id=user_id,
                session_id="owned_session_id",
                title="Owned chat",
                messages_data=json.dumps([{"role": "user", "parts": [{"text": "hello"}]}]),
            )
        )
        db.session.add(
            ChatShare(
                user_id=user_id,
                session_id="shared_session_id",
                public_id="public_shared_session",
                is_public=False,
            )
        )
        db.session.commit()

    @check_resource_ownership("chat", resource_id_arg="session_id")
    def chat_view(**_kwargs):
        return "chat-ok"

    @check_resource_ownership("chat_share")
    def share_view(**_kwargs):
        return "share-ok"

    with app.test_request_context("/chat"):
        session["user_id"] = user_id
        assert chat_view(session_id="owned_session_id") == "chat-ok"

    with app.test_request_context("/share?resource_id=shared_session_id"):
        session["user_id"] = user_id
        assert share_view() == "share-ok"


def test_check_resource_ownership_supports_public_chat_and_denies_missing_owner(
    app, create_confirmed_user
):
    owner_id, _, _ = create_confirmed_user()
    other_user_id, _, _ = create_confirmed_user()

    with app.app_context():
        db.session.add(
            ChatShare(
                user_id=owner_id,
                session_id="public_session_id",
                public_id="public_session",
                is_public=True,
            )
        )
        db.session.commit()

    @check_resource_ownership("public_chat")
    def public_view(**_kwargs):
        return "public-ok"

    @check_resource_ownership("chat")
    def private_view(**_kwargs):
        return "private-ok"

    with app.test_request_context(
        "/public",
        method="POST",
        data=json.dumps({"resource_id": "public_session_id"}),
        content_type="application/json",
    ):
        session["user_id"] = other_user_id
        assert public_view() == "public-ok"

    with app.test_request_context("/private", method="POST", data={"resource_id": "missing"}):
        session["user_id"] = other_user_id
        response, status = private_view()

    assert status == 403
    assert response.get_json()["error"]["code"] == "access_denied"


def test_verify_resource_access_checks_chat_share_and_public_chat(app, create_confirmed_user):
    user_id, _, _ = create_confirmed_user()
    other_user_id, _, _ = create_confirmed_user()

    with app.app_context():
        db.session.add(
            UserChatHistory(
                user_id=user_id,
                session_id="verify_chat_session",
                title="Verify chat",
                messages_data="[]",
            )
        )
        db.session.add(
            ChatShare(
                user_id=user_id,
                session_id="verify_chat_session",
                public_id="verify_public",
                is_public=True,
            )
        )
        db.session.commit()

        assert verify_resource_access(user_id, "chat", "verify_chat_session") is True
        assert verify_resource_access(user_id, "chat_share", "verify_chat_session") is True
        assert verify_resource_access(other_user_id, "public_chat", "verify_chat_session") is True
        assert verify_resource_access(other_user_id, "chat", "verify_chat_session") is False
        assert verify_resource_access(None, "chat", "verify_chat_session") is False
        assert verify_resource_access(user_id, "unknown", "verify_chat_session") is False


def test_add_ownership_filter_uses_model_column():
    class DummyField:
        def __eq__(self, other):
            return ("eq", other)

    class DummyModel:
        user_id = DummyField()

    class DummyQuery:
        model = DummyModel

        def __init__(self):
            self.filtered = None

        def filter(self, expression):
            self.filtered = expression
            return expression

    query = DummyQuery()
    assert add_ownership_filter(query, 42) == ("eq", 42)
    assert query.filtered == ("eq", 42)
