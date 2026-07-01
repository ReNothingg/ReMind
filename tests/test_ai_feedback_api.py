import json

from utils.auth import AIResponseFeedback, UserChatHistory, UserSettings, db


def _csrf_headers(client):
    csrf_value = client.get("/health", headers={"User-Agent": "Mozilla/5.0 (pytest)"}).headers.get(
        "X-CSRF-Token"
    )
    assert csrf_value
    return {
        "User-Agent": "Mozilla/5.0 (pytest)",
        "X-CSRF-Token": csrf_value,
    }


def test_user_can_submit_ai_feedback_with_opt_in_training_payload(
    client,
    app,
    create_confirmed_user,
    login,
):
    user_id, email, password = create_confirmed_user()
    with app.app_context():
        settings = UserSettings.query.filter_by(user_id=user_id).first()
        settings.settings_data = json.dumps({"service_improvement_opt_in": True})
        db.session.add(
            UserChatHistory(
                user_id=user_id,
                session_id="feedback_session",
                messages_data=json.dumps(
                    [
                        {"role": "user", "parts": [{"text": "private prompt"}]},
                        {"role": "model", "parts": [{"text": "private answer"}]},
                    ]
                ),
            )
        )
        db.session.commit()

    assert login(email, password).status_code == 200
    response = client.post(
        "/api/feedback/ai-response",
        json={
            "session_id": "feedback_session",
            "message_client_id": "ai-1",
            "rating": "dislike",
            "reason_codes": ["incorrect", "unsafe", "incorrect", "ignored"],
            "comment": "The answer mixed facts.",
            "response_text": "private answer",
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    assert response.get_json()["feedback"]["rating"] == "dislike"

    with app.app_context():
        feedback = AIResponseFeedback.query.filter_by(user_id=user_id).one()
        assert feedback.rating == "dislike"
        assert feedback.get_reason_codes() == ["incorrect", "unsafe"]
        assert feedback.comment == "The answer mixed facts."
        assert feedback.prompt_text == "private prompt"
        assert feedback.response_text == "private answer"
        assert feedback.service_improvement_opt_in is True


def test_ai_feedback_requires_owned_session_and_does_not_store_text_without_opt_in(
    client,
    app,
    create_confirmed_user,
    login,
):
    owner_id, _owner_email, _owner_password = create_confirmed_user(username="owner")
    user_id, email, password = create_confirmed_user(username="plain")
    with app.app_context():
        db.session.add(
            UserChatHistory(
                user_id=owner_id,
                session_id="owned_by_someone_else",
                messages_data="[]",
            )
        )
        db.session.add(
            UserChatHistory(
                user_id=user_id,
                session_id="own_session",
                messages_data=json.dumps(
                    [{"role": "model", "parts": [{"text": "stored only as hash"}]}]
                ),
            )
        )
        db.session.commit()

    assert login(email, password).status_code == 200
    headers = _csrf_headers(client)

    denied = client.post(
        "/api/feedback/ai-response",
        json={
            "session_id": "owned_by_someone_else",
            "rating": "like",
            "response_text": "nope",
        },
        headers=headers,
    )
    assert denied.status_code == 404

    accepted = client.post(
        "/api/feedback/ai-response",
        json={
            "session_id": "own_session",
            "rating": "like",
            "response_text": "stored only as hash",
        },
        headers=headers,
    )
    assert accepted.status_code == 200

    with app.app_context():
        feedback = AIResponseFeedback.query.filter_by(user_id=user_id).one()
        assert feedback.rating == "like"
        assert feedback.response_text is None
        assert feedback.prompt_text is None
        assert feedback.comment is None
        assert feedback.service_improvement_opt_in is False
