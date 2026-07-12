from __future__ import annotations

import json

import pytest

from services import model_tools


def test_model_tool_declarations_include_web_and_connected_github(monkeypatch):
    monkeypatch.setattr(model_tools, "WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr(model_tools, "_github_installations", lambda _user_id: [object()])

    names = {
        item["name"]
        for item in model_tools.model_tool_declarations(7, enable_web=True)
    }

    assert names == {
        "web_search",
        "github_list_repositories",
        "github_get_repository_map",
        "github_read_file",
    }


def test_web_search_tool_returns_model_context_and_public_sources(monkeypatch):
    monkeypatch.setattr(
        model_tools,
        "run_web_search",
        lambda query: {
            "query": query,
            "context": "[1] Example source\nUseful fact",
            "sources": [
                {
                    "id": 1,
                    "title": "Example",
                    "url": "https://example.com/article",
                    "snippet": "Useful fact",
                }
            ],
        },
    )

    result = model_tools.execute_model_tool(
        "web_search", {"query": "latest example"}, user_id=7
    )

    assert result.output["ok"] is True
    assert result.output["query"] == "latest example"
    assert result.sources[0]["url"] == "https://example.com/article"
    assert [event["status"] for event in result.events] == [
        "web_search_started",
        "web_search_fetching",
        "web_search_done",
    ]


@pytest.mark.parametrize(
    "path",
    [".env", "private/id_rsa", "certificates/server.pem", "config/api_key.txt"],
)
def test_github_read_tool_blocks_sensitive_paths(path):
    with pytest.raises(ValueError, match="sensitive_path_blocked"):
        model_tools._safe_github_read_path(path)


def test_serialized_tool_output_marks_external_content_untrusted():
    payload = json.loads(model_tools.serialize_tool_output({"ok": True, "content": "hello"}))

    assert payload["ok"] is True
    assert "untrusted external content" in payload["security"]


def test_serialized_tool_output_remains_valid_and_bounded_when_truncated():
    serialized = model_tools.serialize_tool_output({"content": '"\\' * 100_000})
    payload = json.loads(serialized)

    assert payload["truncated"] is True
    assert len(serialized) <= model_tools.MAX_TOOL_OUTPUT_CHARS


def test_web_tool_is_not_exposed_when_search_is_disabled(monkeypatch):
    monkeypatch.setattr(model_tools, "_github_installations", lambda _user_id: [])

    assert model_tools.model_tool_declarations(7, enable_web=False) == []


def test_repository_lookup_is_scoped_to_current_users_installations(monkeypatch):
    installation = type("Installation", (), {"installation_id": 42})()
    monkeypatch.setattr(
        model_tools, "_github_installations", lambda user_id: [installation] if user_id == 7 else []
    )

    class FakeService:
        def __init__(self, installation_id):
            assert installation_id == 42

        def list_repositories(self):
            return [{"full_name": "owner/private", "default_branch": "main"}]

    monkeypatch.setattr(model_tools, "GitHubAgentService", FakeService)

    service, repository = model_tools._repository_service(7, "owner/private")
    assert isinstance(service, FakeService)
    assert repository["full_name"] == "owner/private"
    with pytest.raises(ValueError, match="repository_not_connected"):
        model_tools._repository_service(8, "owner/private")
