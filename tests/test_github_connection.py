from __future__ import annotations

from types import SimpleNamespace

from flask import Flask

import routes.features.github as github_routes


class FakeQuery:
    def __init__(self, items: list[object]) -> None:
        self.items = items

    def filter_by(self, **_kwargs):
        return self

    def order_by(self, *_args):
        return self

    def all(self) -> list[object]:
        return self.items


class FakeSortField:
    def desc(self):
        return self


class FakeInstallation:
    def __init__(self, installation_id: int) -> None:
        self.id = installation_id
        self.installation_id = installation_id

    def to_dict(self) -> dict[str, int]:
        return {"installation_id": self.installation_id}


def test_connection_payload_never_contacts_github(monkeypatch) -> None:
    installations = [FakeInstallation(51)]
    monkeypatch.setattr(
        github_routes,
        "GitHubInstallation",
        SimpleNamespace(
            id=FakeSortField(),
            query=FakeQuery(installations),
            updated_at=FakeSortField(),
        ),
    )
    monkeypatch.setattr(github_routes, "github_app_missing_fields", lambda: [])
    monkeypatch.setattr(github_routes, "url_for", lambda endpoint, **_values: f"/{endpoint}")
    monkeypatch.setattr(
        github_routes,
        "_github_external_url",
        lambda endpoint, **_values: f"https://example.test/{endpoint}",
    )

    class ExternalCallIsForbidden:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("connection endpoint must not call GitHub")

    monkeypatch.setattr(github_routes, "GitHubAgentService", ExternalCallIsForbidden)

    payload = github_routes._github_connection_payload(7)

    assert payload["configured"] is True
    assert payload["selected_installation_id"] == 51
    assert payload["installations"] == [{"installation_id": 51}]
    assert payload["repositories"] == []
    assert payload["connection_error"] is None


def test_oauth_redirect_returns_to_github_workspace() -> None:
    app = Flask(__name__)

    with app.test_request_context("/"):
        response = github_routes._github_frontend_redirect(github="connected")

    assert response.status_code == 303
    assert response.location.endswith("/github?github=connected")
