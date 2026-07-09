from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from flask import Blueprint, Flask

import routes.features.github as github_routes
from services.github_oauth_flow import GitHubOAuthFlowStore


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, key: str, value: str, *, ex: int) -> bool:
        self.values[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def getdel(self, key: str) -> str | None:
        return self.values.pop(key, None)

    def delete(self, key: str) -> int:
        return 1 if self.values.pop(key, None) is not None else 0


def make_store(redis_client: FakeRedis) -> GitHubOAuthFlowStore:
    return GitHubOAuthFlowStore(
        redis_client,
        encryption_key=Fernet.generate_key().decode("ascii"),
        secret_key="test-secret",
    )


def test_state_is_bound_to_user_and_consumed_once() -> None:
    store = make_store(FakeRedis())
    start = store.start(17, after="setup", pending_installation_id=42)

    state = store.consume_state(start.state, 17)

    assert state is not None
    assert state.flow_id == start.flow_id
    assert state.after == "setup"
    assert state.pending_installation_id == 42
    assert store.consume_state(start.state, 17) is None


def test_credential_is_encrypted_and_consumed_once() -> None:
    redis_client = FakeRedis()
    store = make_store(redis_client)
    start = store.start(17)
    access_token = "github-user-access-token"

    store.store_credential(start.flow_id, 17, access_token)

    assert all(access_token not in value for value in redis_client.values.values())
    assert store.has_credential(start.flow_id, 17)
    assert store.consume_credential(start.flow_id, 17) == access_token
    assert store.consume_credential(start.flow_id, 17) is None


def test_credential_cannot_be_read_by_a_different_user() -> None:
    store = make_store(FakeRedis())
    start = store.start(17)
    store.store_credential(start.flow_id, 17, "github-user-access-token")

    assert not store.has_credential(start.flow_id, 18)


def test_oauth_callback_keeps_token_out_of_the_browser_session(monkeypatch) -> None:
    redis_client = FakeRedis()
    store = make_store(redis_client)
    app = Flask(__name__)
    app.secret_key = "test-session-secret"
    blueprint = Blueprint("api", __name__)
    github_routes.register_github_routes(blueprint)
    app.register_blueprint(blueprint)

    monkeypatch.setattr(github_routes, "github_app_configured", lambda: True)
    monkeypatch.setattr(
        github_routes,
        "_github_external_url",
        lambda endpoint, **_values: f"https://example.test/{endpoint}",
    )
    monkeypatch.setattr(
        github_routes,
        "build_github_oauth_url",
        lambda _callback_url, state, **_values: f"https://github.test/oauth?state={state}",
    )
    monkeypatch.setattr(
        github_routes,
        "build_github_app_install_url",
        lambda: "https://github.test/install",
    )
    monkeypatch.setattr(
        github_routes,
        "exchange_github_oauth_code",
        lambda _code, _callback_url: "github-user-access-token",
    )
    monkeypatch.setattr(
        github_routes.GitHubOAuthFlowStore,
        "from_config",
        classmethod(lambda _cls: store),
    )

    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = 17

    login_response = client.get("/auth/github/login?after=install")
    state = parse_qs(urlparse(login_response.location).query)["state"][0]
    callback_response = client.get(f"/auth/github/callback?state={state}&code=oauth-code")

    assert callback_response.status_code == 302
    assert callback_response.location == "https://github.test/install"
    assert all("github-user-access-token" not in value for value in redis_client.values.values())
    with client.session_transaction() as session:
        assert "github_user_token" not in session
        assert session[github_routes.GITHUB_OAUTH_FLOW_SESSION_KEY]
