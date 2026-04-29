import routes.features.chat as chat_routes
from utils.auth import Mind, MindPin, UserChatHistory
from utils.rate_limiting import rate_limit_store


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
        "name": "Research Mind",
        "description": "Helps prepare concise research summaries.",
        "instructions": "Summarize sources carefully and separate facts from assumptions.",
        "starters": ["Summarize this topic", "Build a research outline"],
        "category": "education",
        "visibility": "private",
    }
    payload.update(overrides)
    return payload


def test_mind_create_list_pin_and_delete_lifecycle(client, app, create_confirmed_user, login):
    user_id, email, password = create_confirmed_user()
    assert login(email, password).status_code == 200
    headers = _csrf_headers(client)

    create_response = client.post("/api/minds", json=_mind_payload(), headers=headers)
    assert create_response.status_code == 201
    created = create_response.get_json()["mind"]
    assert created["name"] == "Research Mind"
    assert created["is_owner"] is True
    assert created["can_edit"] is True
    assert created["instructions"]

    mine_response = client.get("/api/minds?mine=1", headers={"User-Agent": "Mozilla/5.0 (pytest)"})
    assert mine_response.status_code == 200
    assert [mind["public_id"] for mind in mine_response.get_json()["minds"]] == [created["public_id"]]

    public_response = client.get(f"/api/minds/{created['public_id']}")
    assert public_response.status_code == 404

    pin_response = client.post(f"/api/minds/{created['public_id']}/pin", headers=headers)
    assert pin_response.status_code == 200
    assert pin_response.get_json()["mind"]["is_pinned"] is True

    pinned_response = client.get("/api/minds/pinned", headers={"User-Agent": "Mozilla/5.0 (pytest)"})
    assert pinned_response.status_code == 200
    assert pinned_response.get_json()["minds"][0]["public_id"] == created["public_id"]

    delete_response = client.delete(f"/api/minds/{created['public_id']}", headers=headers)
    assert delete_response.status_code == 204

    with app.app_context():
        assert Mind.query.filter_by(user_id=user_id).count() == 0
        assert MindPin.query.filter_by(user_id=user_id).count() == 0


def test_mind_store_search_hides_instructions_for_non_owner(client, create_confirmed_user, login):
    _, email, password = create_confirmed_user()
    assert login(email, password).status_code == 200
    headers = _csrf_headers(client)

    create_response = client.post(
        "/api/minds",
        json=_mind_payload(
            name="Verified Search Helper",
            visibility="store",
            category="development",
        ),
        headers=headers,
    )
    assert create_response.status_code == 201
    public_id = create_response.get_json()["mind"]["public_id"]

    assert client.post("/api/auth/logout", headers=headers).status_code == 200

    store_response = client.get("/api/minds?category=development&q=search")
    assert store_response.status_code == 200
    minds = store_response.get_json()["minds"]
    assert [mind["public_id"] for mind in minds] == [public_id]
    assert minds[0]["instructions"] == ""
    assert minds[0]["is_owner"] is False


def test_mind_idor_blocks_other_user_management(client, create_confirmed_user, login):
    _, owner_email, owner_password = create_confirmed_user(username="owner_user")
    _, other_email, other_password = create_confirmed_user(username="other_user")

    assert login(owner_email, owner_password).status_code == 200
    owner_headers = _csrf_headers(client)
    create_response = client.post("/api/minds", json=_mind_payload(), headers=owner_headers)
    assert create_response.status_code == 201
    public_id = create_response.get_json()["mind"]["public_id"]
    assert client.post("/api/auth/logout", headers=owner_headers).status_code == 200

    assert login(other_email, other_password).status_code == 200
    other_headers = _csrf_headers(client)

    update_response = client.put(
        f"/api/minds/{public_id}",
        json=_mind_payload(name="Stolen Mind"),
        headers=other_headers,
    )
    assert update_response.status_code == 404

    pin_response = client.post(f"/api/minds/{public_id}/pin", headers=other_headers)
    assert pin_response.status_code == 404

    delete_response = client.delete(f"/api/minds/{public_id}", headers=other_headers)
    assert delete_response.status_code == 404


def test_mind_validation_rejects_html_instructions(client, create_confirmed_user, login):
    _, email, password = create_confirmed_user()
    assert login(email, password).status_code == 200
    headers = _csrf_headers(client)

    response = client.post(
        "/api/minds",
        json=_mind_payload(instructions="Use this <script>alert(1)</script> payload safely."),
        headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "validation_error"


def test_chat_resolves_mind_context_server_side(client, create_confirmed_user, login, monkeypatch):
    rate_limit_store.clear()
    _, email, password = create_confirmed_user()
    assert login(email, password).status_code == 200
    headers = _csrf_headers(client)

    create_response = client.post(
        "/api/minds",
        json=_mind_payload(instructions="Always answer as a research mentor."),
        headers=headers,
    )
    public_id = create_response.get_json()["mind"]["public_id"]

    def mind_echo(_user_id, payload):
        active_mind = payload.get("active_mind") or {}
        return {"reply": active_mind.get("instructions", "missing")}

    monkeypatch.setattr(chat_routes, "get_model_function", lambda _name: mind_echo)

    session_id = "mind_chat_session_1234567890"

    try:
        response = client.post(
            "/chat",
            json={
                "message": "hello",
                "model": "echo",
                "session_id": session_id,
                "mind_id": public_id,
            },
            headers=headers,
        )
    finally:
        rate_limit_store.clear()

    assert response.status_code == 200
    assert response.get_json()["reply"] == "Always answer as a research mentor."

    history_response = client.get(
        f"/sessions/{session_id}/history",
        headers={"User-Agent": "Mozilla/5.0 (pytest)"},
    )
    assert history_response.status_code == 200
    assert history_response.get_json()["mind"]["public_id"] == public_id

    second_response = client.post(
        "/chat",
        json={
            "message": "continue",
            "model": "echo",
            "session_id": session_id,
        },
        headers=headers,
    )
    assert second_response.status_code == 200
    assert second_response.get_json()["reply"] == "Always answer as a research mentor."

    clear_response = client.put(
        f"/sessions/{session_id}/mind",
        json={"mind_id": None},
        headers=headers,
    )
    assert clear_response.status_code == 200
    assert clear_response.get_json()["mind"] is None

    with client.application.app_context():
        chat = UserChatHistory.query.filter_by(session_id=session_id).first()
        assert chat is not None
        assert chat.mind_id is None
