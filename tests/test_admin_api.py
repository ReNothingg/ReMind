import json
from datetime import datetime, timedelta

import pytest

from utils.auth import AIResponseFeedback, Mind, User, UserChatHistory, db
from utils.rate_limiting import rate_limit_store


@pytest.fixture(autouse=True)
def clear_rate_limits():
    rate_limit_store.clear()
    yield
    rate_limit_store.clear()


def _csrf_headers(client):
    csrf_value = client.get(
        "/health", headers={"User-Agent": "Mozilla/5.0 (pytest)"}
    ).headers.get("X-CSRF-Token")
    assert csrf_value
    return {
        "User-Agent": "Mozilla/5.0 (pytest)",
        "X-CSRF-Token": csrf_value,
    }


def _mind_payload(**overrides):
    payload = {
        "name": "Store Mind",
        "description": "A public mind for moderation tests.",
        "instructions": "Answer with concise moderation-safe help.",
        "starters": ["Start"],
        "category": "general",
        "visibility": "store",
    }
    payload.update(overrides)
    return payload


def test_root_admin_can_open_dashboard_without_chat_transcripts(
    client,
    app,
    create_confirmed_user,
    login,
):
    _admin_id, admin_email, admin_password = create_confirmed_user(username="root_admin")
    target_id, _target_email, _target_password = create_confirmed_user(username="target_user")

    with app.app_context():
        db.session.add(
            UserChatHistory(
                user_id=target_id,
                session_id="secret_session",
                title="Private title",
                messages_data=json.dumps(
                    [{"role": "user", "content": "very secret transcript"}],
                    ensure_ascii=False,
                ),
            )
        )
        db.session.commit()

    assert login(admin_email, admin_password).status_code == 200

    overview = client.get("/api/admin/overview", headers={"User-Agent": "Mozilla/5.0 (pytest)"})
    assert overview.status_code == 200
    assert overview.get_json()["admin"]["is_super_admin"] is True
    assert overview.get_json()["operations"]["health"]["score"] >= 0
    assert "queues" in overview.get_json()["operations"]
    assert "recent_audit" in overview.get_json()["operations"]

    users = client.get("/api/admin/users", headers={"User-Agent": "Mozilla/5.0 (pytest)"})
    assert users.status_code == 200
    serialized = json.dumps(users.get_json(), ensure_ascii=False)
    assert "very secret transcript" not in serialized
    listed_target = next(
        item for item in users.get_json()["users"] if item["id"] == target_id
    )
    assert listed_target["chat_count"] == 1


def test_admin_overview_exposes_only_ai_feedback_percentages(
    client,
    app,
    create_confirmed_user,
    login,
):
    _admin_id, admin_email, admin_password = create_confirmed_user(username="root_admin")
    target_id, _target_email, _target_password = create_confirmed_user(username="feedback_user")

    with app.app_context():
        db.session.add_all(
            [
                AIResponseFeedback(
                    user_id=target_id,
                    session_id="feedback_session",
                    response_hash="a" * 64,
                    rating="like",
                    response_text="secret liked answer",
                ),
                AIResponseFeedback(
                    user_id=target_id,
                    session_id="feedback_session",
                    response_hash="b" * 64,
                    rating="dislike",
                    comment="secret dislike comment",
                ),
            ]
        )
        db.session.commit()

    assert login(admin_email, admin_password).status_code == 200

    overview = client.get("/api/admin/overview", headers={"User-Agent": "Mozilla/5.0 (pytest)"})
    assert overview.status_code == 200
    ai_feedback = overview.get_json()["stats"]["ai_feedback"]
    assert ai_feedback == {
        "total": 2,
        "likes": 1,
        "dislikes": 1,
        "like_percent": 50.0,
        "dislike_percent": 50.0,
    }
    serialized = json.dumps(overview.get_json(), ensure_ascii=False)
    assert "secret liked answer" not in serialized
    assert "secret dislike comment" not in serialized


def test_non_admin_is_rejected_from_admin_api(client, create_confirmed_user, login):
    _admin_id, _admin_email, _admin_password = create_confirmed_user(username="root_admin")
    _user_id, user_email, user_password = create_confirmed_user(username="plain_user")

    assert login(user_email, user_password).status_code == 200

    response = client.get("/api/admin/overview", headers={"User-Agent": "Mozilla/5.0 (pytest)"})
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "admin_required"


def test_admin_can_ban_account_and_block_future_login(
    client,
    create_confirmed_user,
    login,
):
    _admin_id, admin_email, admin_password = create_confirmed_user(username="root_admin")
    target_id, target_email, target_password = create_confirmed_user(username="target_user")

    assert login(admin_email, admin_password).status_code == 200
    headers = _csrf_headers(client)

    response = client.patch(
        f"/api/admin/users/{target_id}",
        json={"is_banned": True, "moderation_reason": "abuse"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.get_json()["user"]["is_banned"] is True

    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    login_response = login(target_email, target_password)
    assert login_response.status_code == 403
    assert "abuse" in login_response.get_json()["error"]


def test_admin_can_set_temporary_block_reason_and_expired_blocks_do_not_apply(
    client,
    app,
    create_confirmed_user,
    login,
):
    _admin_id, admin_email, admin_password = create_confirmed_user(username="root_admin")
    target_id, target_email, target_password = create_confirmed_user(username="temporary_blocked")

    assert login(admin_email, admin_password).status_code == 200
    headers = _csrf_headers(client)
    blocked_until = (datetime.utcnow() + timedelta(hours=2)).isoformat() + "Z"

    response = client.patch(
        f"/api/admin/users/{target_id}",
        json={
            "is_blocked": True,
            "block_reason": "payment abuse",
            "blocked_until": blocked_until,
        },
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.get_json()["user"]
    assert payload["is_blocked"] is True
    assert payload["block_reason"] == "payment abuse"
    assert payload["blocked_until"] is not None

    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    login_response = login(target_email, target_password)
    assert login_response.status_code == 403
    assert "payment abuse" in login_response.get_json()["error"]
    assert "Срок:" in login_response.get_json()["error"]

    with app.app_context():
        target = db.session.get(User, target_id)
        target.blocked_until = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()

    login_response = login(target_email, target_password)
    assert login_response.status_code == 200


def test_admin_can_feature_and_ban_mind(client, create_confirmed_user, login):
    _admin_id, admin_email, admin_password = create_confirmed_user(username="root_admin")
    _owner_id, owner_email, owner_password = create_confirmed_user(username="mind_owner")

    assert login(owner_email, owner_password).status_code == 200
    owner_headers = _csrf_headers(client)
    create_response = client.post("/api/minds", json=_mind_payload(), headers=owner_headers)
    assert create_response.status_code == 201
    public_id = create_response.get_json()["mind"]["public_id"]
    assert client.post("/api/auth/logout", headers=owner_headers).status_code == 200

    assert login(admin_email, admin_password).status_code == 200
    admin_headers = _csrf_headers(client)
    feature_response = client.patch(
        f"/api/admin/minds/{public_id}",
        json={"is_featured": True},
        headers=admin_headers,
    )
    assert feature_response.status_code == 200
    assert feature_response.get_json()["mind"]["is_featured"] is True

    store_response = client.get("/api/minds", headers={"User-Agent": "Mozilla/5.0 (pytest)"})
    assert store_response.status_code == 200
    assert store_response.get_json()["minds"][0]["public_id"] == public_id
    assert store_response.get_json()["minds"][0]["is_featured"] is True

    ban_response = client.patch(
        f"/api/admin/minds/{public_id}",
        json={"is_banned": True, "moderation_reason": "unsafe"},
        headers=admin_headers,
    )
    assert ban_response.status_code == 200
    assert ban_response.get_json()["mind"]["is_banned"] is True
    assert ban_response.get_json()["mind"]["is_featured"] is False

    with client.application.app_context():
        mind = Mind.query.filter_by(public_id=public_id).first()
        assert mind is not None
        assert mind.is_banned is True

    hidden_response = client.get("/api/minds", headers={"User-Agent": "Mozilla/5.0 (pytest)"})
    assert hidden_response.status_code == 200
    assert hidden_response.get_json()["minds"] == []
