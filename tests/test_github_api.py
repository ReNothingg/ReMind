import json

from utils.auth import GitHubInstallation, UserChatHistory, db
from services.github_app import GitHubAgentExecutionError


class FakeGitHubAgentService:
    def __init__(self, installation_id):
        self.installation_id = int(installation_id)

    def list_repositories(self):
        return [
            {
                "full_name": "ReNothingg/ReMind",
                "html_url": "https://github.com/ReNothingg/ReMind",
                "default_branch": "main",
                "private": False,
                "permissions": {"pull": True, "push": True, "admin": False},
            },
            {
                "full_name": "ReNothingg/devex-pr-agent",
                "html_url": "https://github.com/ReNothingg/devex-pr-agent",
                "default_branch": "main",
                "private": False,
                "permissions": {"pull": True, "push": True, "admin": False},
            }
        ]

    def plan(self, repo_full_name, base_branch, task):
        return {
            "summary": "Test plan",
            "steps": [{"title": "Edit file", "details": "Update a target file"}],
            "files": [{"path": "src/App.tsx", "reason": "App route", "action": "edit"}],
            "risks": [],
            "branch_suffix": "test-task",
            "commit_message": "Implement test task",
            "pr_title": "Test task",
            "pr_body": task,
            "repo_map": {
                "stats": {"files": 1, "directories": 1, "nodes": 2, "max_depth": 2},
                "truncated": False,
                "source": "git",
            },
        }

    def run(self, repo_full_name, base_branch, task, plan):
        return {
            "branch_name": "remind/test-task",
            "commit_sha": "abc123",
            "diff": (
                "diff --git a/src/App.tsx b/src/App.tsx\n"
                "# modified: src/App.tsx\n"
                "@@ -1,1 +1,1 @@\n"
                "-export default function App() { return <main>Old</main>; }\n"
                "+export default function App() { return <main>New</main>; }\n"
            ),
            "edits": {
                "summary": "Updated file",
                "activity": [{"code": "pullRequestOpened", "status": "done"}],
                "tests": ["Not run"],
                "edits": [
                    {
                        "path": "src/App.tsx",
                        "action": "update",
                        "content": "export default function App() { return null; }",
                    }
                ],
            },
            "pull_request": {
                "number": 7,
                "url": "https://github.com/ReNothingg/ReMind/pull/7",
                "title": "Test task",
            },
        }


class FailingGitHubAgentService(FakeGitHubAgentService):
    def run(self, repo_full_name, base_branch, task, plan):
        raise GitHubAgentExecutionError(
            "AI editor did not return JSON edits.",
            [{"code": "geminiInvalidJson", "status": "error"}],
        )


class NoChangeGitHubAgentService(FakeGitHubAgentService):
    def run(self, repo_full_name, base_branch, task, plan):
        return {
            "no_changes": True,
            "diff": "",
            "edits": {
                "summary": "No safe bug fix found.",
                "findings": ["The agent found no deterministic edit."],
                "no_changes_reason": "No safe bug fix found.",
                "activity": [{"code": "noChanges", "status": "warning"}],
                "tests": [],
                "edits": [],
            },
        }


class NoopOnlyGitHubAgentService(FakeGitHubAgentService):
    def run(self, repo_full_name, base_branch, task, plan):
        return {
            "no_changes": True,
            "diff": "",
            "edits": {
                "summary": "The AI editor only proposed edits that leave files unchanged.",
                "findings": [],
                "no_changes_reason": "The AI editor only proposed edits that leave files unchanged.",
                "activity": [{"code": "noChanges", "status": "warning"}],
                "tests": [],
                "edits": [],
            },
        }


def _login_confirmed_user(client, create_confirmed_user, login):
    _user_id, email, password = create_confirmed_user()
    response = login(email, password)
    assert response.status_code == 200
    return _user_id


def _add_installation(app, user_id, installation_id=123):
    with app.app_context():
        installation = GitHubInstallation(
            user_id=user_id,
            installation_id=installation_id,
            account_login="ReNothingg",
            repository_selection="selected",
        )
        installation.set_permissions({"contents": "write", "pull_requests": "write"})
        db.session.add(installation)
        db.session.commit()


def _patch_github_chat(monkeypatch, service_class=FakeGitHubAgentService):
    import services.github_chat as github_chat

    monkeypatch.setattr(github_chat, "github_app_missing_fields", lambda: [])
    monkeypatch.setattr(github_chat, "github_app_configured", lambda: True)
    monkeypatch.setattr(github_chat, "GitHubAgentService", service_class)
    monkeypatch.setattr(github_chat, "call_gemini_json", lambda _prompt: None)
    return github_chat


def test_github_oauth_callback_uses_public_base_url(app, monkeypatch):
    import routes.features.github as github_routes

    monkeypatch.setattr(github_routes, "GITHUB_PUBLIC_BASE_URL", "http://localhost:5173")

    with app.test_request_context("/", headers={"Host": "127.0.0.1:5000"}):
        assert (
            github_routes._github_external_url("api.github_oauth_callback")
            == "http://localhost:5173/auth/github/callback"
        )


def test_github_status_lists_user_installation_repositories(
    app, client, create_confirmed_user, login, monkeypatch
):
    import routes.features.github as github_routes

    monkeypatch.setattr(github_routes, "github_app_missing_fields", lambda: [])
    monkeypatch.setattr(github_routes, "github_app_configured", lambda: True)
    monkeypatch.setattr(github_routes, "GitHubAgentService", FakeGitHubAgentService)

    user_id = _login_confirmed_user(client, create_confirmed_user, login)
    _add_installation(app, user_id)

    response = client.get("/api/github/status")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["selected_installation_id"] == 123
    assert payload["repositories"][0]["full_name"] == "ReNothingg/ReMind"


def test_github_agent_plan_and_run_create_task(app, client, create_confirmed_user, login, monkeypatch):
    import routes.features.github as github_routes

    monkeypatch.setattr(github_routes, "GitHubAgentService", FakeGitHubAgentService)

    user_id = _login_confirmed_user(client, create_confirmed_user, login)
    _add_installation(app, user_id)
    csrf_token = client.get("/health").headers.get("X-CSRF-Token")

    plan_response = client.post(
        "/api/github/agent/plan",
        json={
            "installation_id": 123,
            "repo_full_name": "ReNothingg/ReMind",
            "base_branch": "main",
            "task": "Add a settings page",
        },
        headers={"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_token},
    )

    assert plan_response.status_code == 200
    planned_task = plan_response.get_json()["task"]
    assert planned_task["status"] == "planned"
    assert planned_task["plan"]["files"][0]["path"] == "src/App.tsx"

    run_response = client.post(
        "/api/github/agent/run",
        json={"task_id": planned_task["id"]},
        headers={"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_token},
    )

    assert run_response.status_code == 200
    completed_task = run_response.get_json()["task"]
    assert completed_task["status"] == "pull_request_opened"
    assert completed_task["branch_name"] == "remind/test-task"
    assert completed_task["pull_request_url"].endswith("/pull/7")
    assert completed_task["edits"]["activity"][0]["code"] == "pullRequestOpened"


def test_github_agent_run_error_keeps_activity(app, client, create_confirmed_user, login, monkeypatch):
    import routes.features.github as github_routes

    monkeypatch.setattr(github_routes, "GitHubAgentService", FailingGitHubAgentService)

    user_id = _login_confirmed_user(client, create_confirmed_user, login)
    _add_installation(app, user_id)
    csrf_token = client.get("/health").headers.get("X-CSRF-Token")

    plan_response = client.post(
        "/api/github/agent/plan",
        json={
            "installation_id": 123,
            "repo_full_name": "ReNothingg/ReMind",
            "base_branch": "main",
            "task": "Find bugs",
        },
        headers={"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_token},
    )
    planned_task = plan_response.get_json()["task"]

    run_response = client.post(
        "/api/github/agent/run",
        json={"task_id": planned_task["id"]},
        headers={"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_token},
    )

    assert run_response.status_code == 500

    task_response = client.get(
        f"/api/github/tasks/{planned_task['id']}",
        headers={"User-Agent": "Mozilla/5.0 (pytest)"},
    )
    failed_task = task_response.get_json()["task"]
    assert failed_task["status"] == "error"
    assert failed_task["error"] == "AI editor did not return JSON edits."
    assert failed_task["edits"]["activity"][0]["code"] == "geminiInvalidJson"


def test_github_agent_run_without_edits_completes_without_pr(
    app, client, create_confirmed_user, login, monkeypatch
):
    import routes.features.github as github_routes

    monkeypatch.setattr(github_routes, "GitHubAgentService", NoChangeGitHubAgentService)

    user_id = _login_confirmed_user(client, create_confirmed_user, login)
    _add_installation(app, user_id)
    csrf_token = client.get("/health").headers.get("X-CSRF-Token")

    plan_response = client.post(
        "/api/github/agent/plan",
        json={
            "installation_id": 123,
            "repo_full_name": "ReNothingg/ReMind",
            "base_branch": "main",
            "task": "Find bugs",
        },
        headers={"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_token},
    )
    planned_task = plan_response.get_json()["task"]

    run_response = client.post(
        "/api/github/agent/run",
        json={"task_id": planned_task["id"]},
        headers={"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_token},
    )

    assert run_response.status_code == 200
    completed_task = run_response.get_json()["task"]
    assert completed_task["status"] == "completed_no_changes"
    assert completed_task["pull_request_url"] is None
    assert completed_task["edits"]["findings"] == ["The agent found no deterministic edit."]


def test_github_agent_run_falls_back_to_pull_request_files_for_diff(monkeypatch):
    import services.github_app as github_app
    from services.github_app import GitHubAgentService

    class CompareWithoutPatchClient:
        def compare(self, owner, repo, base, head):
            return {"files": [{"filename": "src/app.py", "status": "modified"}]}

        def create_pull_request(self, owner, repo, title, head, base, body):
            return {
                "number": 2,
                "html_url": "https://github.com/ReNothingg/ReSave/pull/2",
                "title": title,
            }

        def list_pull_request_files(self, owner, repo, number):
            return [
                {
                    "filename": "src/app.py",
                    "status": "modified",
                    "patch": "@@ -1 +1 @@\n-old\n+new",
                }
            ]

    service = object.__new__(GitHubAgentService)
    service.installation_id = 123
    service.client = CompareWithoutPatchClient()
    monkeypatch.setattr(
        service,
        "load_repo_map",
        lambda repo_full_name, base_branch: {
            "base_branch": base_branch,
            "stats": {"files": 1, "directories": 0, "nodes": 1},
            "truncated": False,
            "flat": [{"path": "src/app.py", "type": "file"}],
        },
    )
    monkeypatch.setattr(service, "_commit_edits", lambda **_kwargs: ("remind/bug-hunt", "1a6bb2f"))
    monkeypatch.setattr(
        github_app,
        "read_file_contexts",
        lambda *_args, **_kwargs: [{"path": "src/app.py", "content": "old\n", "exists": True}],
    )
    monkeypatch.setattr(
        github_app,
        "call_gemini_json_with_trace",
        lambda _prompt: (
            {
                "summary": "Fixed app bug",
                "edits": [
                    {
                        "path": "src/app.py",
                        "action": "update",
                        "content": "new\n",
                        "reason": "Fix deterministic issue",
                    }
                ],
                "tests": [],
            },
            {"code": "geminiJsonParsed", "status": "done"},
        ),
    )

    result = service.run(
        repo_full_name="ReNothingg/ReSave",
        base_branch="main",
        task="Найди и исправь баги",
        plan={
            "files": [{"path": "src/app.py"}],
            "branch_suffix": "bug-hunt",
            "commit_message": "fix: bug hunt",
            "pr_title": "Bug hunt",
            "pr_body": "Body",
        },
    )

    assert result["pull_request"]["url"].endswith("/pull/2")
    assert result["diff"].startswith("diff --git a/src/app.py b/src/app.py")
    assert "-old" in result["diff"]
    assert "+new" in result["diff"]
    assert any(
        item.get("code") == "diffLoadedFromPullRequest"
        for item in result["edits"]["activity"]
    )


def test_github_agent_retries_invalid_editor_json(monkeypatch):
    import services.github_app as github_app
    from services.github_app import GitHubAgentService

    class SimpleClient:
        def compare(self, owner, repo, base, head):
            return {
                "files": [
                    {
                        "filename": "README.md",
                        "status": "modified",
                        "patch": "@@ -1 +1 @@\n-old readme\n+new readme",
                    }
                ]
            }

        def create_pull_request(self, owner, repo, title, head, base, body):
            return {"number": 3, "html_url": "https://github.com/ReNothingg/ReSave/pull/3", "title": title}

        def list_pull_request_files(self, owner, repo, number):
            return []

    service = object.__new__(GitHubAgentService)
    service.installation_id = 123
    service.client = SimpleClient()
    monkeypatch.setattr(
        service,
        "load_repo_map",
        lambda repo_full_name, base_branch: {
            "base_branch": base_branch,
            "stats": {"files": 1, "directories": 0, "nodes": 1},
            "truncated": False,
            "flat": [{"path": "README.md", "type": "file"}],
        },
    )
    monkeypatch.setattr(service, "_commit_edits", lambda **_kwargs: ("remind/readme", "abc123"))
    monkeypatch.setattr(
        github_app,
        "read_file_contexts",
        lambda *_args, **_kwargs: [{"path": "README.md", "content": "old readme\n", "exists": True}],
    )
    calls = []

    def fake_editor(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return None, {
                "code": "geminiInvalidJson",
                "status": "error",
                "details": {"response_preview": "not json", "response_chars": 8},
            }
        return (
            {
                "summary": "Улучшен README.",
                "edits": [
                    {
                        "path": "README.md",
                        "action": "update",
                        "content": "new readme\n",
                        "reason": "Уточнить README.",
                    }
                ],
                "tests": [],
            },
            {"code": "geminiJsonParsed", "status": "done"},
        )

    monkeypatch.setattr(github_app, "call_gemini_json_with_trace", fake_editor)

    result = service.run(
        repo_full_name="ReNothingg/ReSave",
        base_branch="main",
        task="Улучши README",
        plan={
            "files": [{"path": "README.md"}],
            "branch_suffix": "readme",
            "commit_message": "docs: improve readme",
            "pr_title": "Improve README",
            "pr_body": "Body",
        },
    )

    assert len(calls) == 2
    assert "previous editor response was rejected" in calls[1]
    assert result["pull_request"]["url"].endswith("/pull/3")
    assert result["diff"].startswith("diff --git a/README.md b/README.md")
    assert any(item.get("code") == "editorJsonRepairStarted" for item in result["edits"]["activity"])


def test_github_agent_invalid_editor_json_after_retry_completes_without_pr(monkeypatch):
    import services.github_app as github_app
    from services.github_app import GitHubAgentService

    service = object.__new__(GitHubAgentService)
    service.installation_id = 123
    service.client = object()
    monkeypatch.setattr(
        service,
        "load_repo_map",
        lambda repo_full_name, base_branch: {
            "base_branch": base_branch,
            "stats": {"files": 1, "directories": 0, "nodes": 1},
            "truncated": False,
            "flat": [{"path": "README.md", "type": "file"}],
        },
    )
    monkeypatch.setattr(
        github_app,
        "read_file_contexts",
        lambda *_args, **_kwargs: [{"path": "README.md", "content": "old readme\n", "exists": True}],
    )
    monkeypatch.setattr(
        github_app,
        "call_gemini_json_with_trace",
        lambda _prompt: (
            None,
            {
                "code": "geminiInvalidJson",
                "status": "error",
                "details": {"response_preview": "still not json", "response_chars": 14},
            },
        ),
    )
    monkeypatch.setattr(
        github_app,
        "call_gemini_text_with_trace",
        lambda _prompt: (None, {"code": "geminiTextEmpty", "status": "error"}),
    )

    result = service.run(
        repo_full_name="ReNothingg/ReSave",
        base_branch="main",
        task="Исправь баг в src/app.py",
        plan={
            "files": [{"path": "src/app.py"}],
            "branch_suffix": "bugfix",
            "commit_message": "fix: app bug",
            "pr_title": "Fix app bug",
            "pr_body": "Body",
        },
    )

    assert result["no_changes"] is True
    assert result["diff"] == ""
    assert result["edits"]["edits"] == []
    assert result["edits"]["no_changes_reason"] == "AI editor did not return valid JSON edits after retry."
    assert any(item.get("code") == "editorJsonRepairStarted" for item in result["edits"]["activity"])


def test_github_agent_uses_text_editor_fallback_for_readme_after_invalid_json(monkeypatch):
    import services.github_app as github_app
    from services.github_app import GitHubAgentService

    class SimpleClient:
        def compare(self, owner, repo, base, head):
            return {
                "files": [
                    {
                        "filename": "README.md",
                        "status": "modified",
                        "patch": "@@ -1,2 +1,7 @@\n # Project\n+\n+## Local development\n+\n+Run `pip install -r requirements.txt`.\n",
                    }
                ]
            }

        def create_pull_request(self, owner, repo, title, head, base, body):
            return {"number": 4, "html_url": "https://github.com/ReNothingg/devex-pr-agent/pull/4", "title": title}

        def list_pull_request_files(self, owner, repo, number):
            return []

    service = object.__new__(GitHubAgentService)
    service.installation_id = 123
    service.client = SimpleClient()
    monkeypatch.setattr(
        service,
        "load_repo_map",
        lambda repo_full_name, base_branch: {
            "base_branch": base_branch,
            "stats": {"files": 1, "directories": 0, "nodes": 1},
            "truncated": False,
            "flat": [{"path": "README.md", "type": "file"}],
        },
    )
    monkeypatch.setattr(service, "_commit_edits", lambda **_kwargs: ("remind/readme", "abc123"))
    monkeypatch.setattr(
        github_app,
        "read_file_contexts",
        lambda *_args, **_kwargs: [{"path": "README.md", "content": "# Project\n", "exists": True}],
    )
    monkeypatch.setattr(
        github_app,
        "call_gemini_json_with_trace",
        lambda _prompt: (
            None,
            {
                "code": "geminiInvalidJson",
                "status": "error",
                "details": {"response_preview": "not json", "response_chars": 8},
            },
        ),
    )
    text_prompts = []

    def fake_text_editor(prompt):
        text_prompts.append(prompt)
        return (
            "BEGIN_REMIND_FILE:README.md\n"
            "# Project\n\n"
            "## Local development\n\n"
            "Run `python3 -m venv .venv`, install dependencies with "
            "`pip install -r requirements.txt`, then start the app with `python main.py`.\n"
            "END_REMIND_FILE",
            {"code": "geminiTextGenerated", "status": "done"},
        )

    monkeypatch.setattr(github_app, "call_gemini_text_with_trace", fake_text_editor)

    result = service.run(
        repo_full_name="ReNothingg/devex-pr-agent",
        base_branch="main",
        task="улучши README: добавь короткий раздел Local development с командами установки и запуска",
        plan={
            "files": [{"path": "README.md"}],
            "branch_suffix": "readme-local-development",
            "commit_message": "docs: add local development section",
            "pr_title": "Add local development docs",
            "pr_body": "Body",
        },
    )

    assert len(text_prompts) == 1
    assert result["pull_request"]["url"].endswith("/pull/4")
    assert result["edits"]["edits"][0]["path"] == "README.md"
    assert "Local development" in result["edits"]["edits"][0]["content"]
    assert any(item.get("code") == "editorJsonRepairStarted" for item in result["edits"]["activity"])
    assert any(item.get("code") == "textEditorFallbackSucceeded" for item in result["edits"]["activity"])


def test_github_chat_request_without_repo_asks_for_repository(
    app, client, create_confirmed_user, login, monkeypatch
):
    _patch_github_chat(monkeypatch)

    user_id = _login_confirmed_user(client, create_confirmed_user, login)
    _add_installation(app, user_id)
    csrf_token = client.get("/health").headers.get("X-CSRF-Token")

    response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-missing-repo",
            "model": "gemini",
            "message": "GitHub: найди баги в коде",
        },
        headers={"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["github_tool"]["status"] == "repo_required"
    assert "owner/repo" in payload["reply"]
    assert "ReNothingg/ReMind" in payload["reply"]


def test_github_chat_plans_and_runs_after_confirmation(
    app, client, create_confirmed_user, login, monkeypatch
):
    _patch_github_chat(monkeypatch)

    user_id = _login_confirmed_user(client, create_confirmed_user, login)
    _add_installation(app, user_id)
    csrf_token = client.get("/health").headers.get("X-CSRF-Token")

    plan_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-plan-run",
            "model": "gemini",
            "message": "В GitHub ReNothingg/ReMind добавь страницу настроек",
        },
        headers={"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_token},
    )

    assert plan_response.status_code == 200
    planned_payload = plan_response.get_json()
    planned_task = planned_payload["github_tool"]["task"]
    assert planned_payload["github_tool"]["status"] == "planned"
    assert planned_task["status"] == "planned"
    assert planned_task["repo_full_name"] == "ReNothingg/ReMind"
    assert "Подтвердить GitHub PR" in planned_payload["reply"]
    assert "ID задачи:" in planned_payload["reply"]
    assert "Task ID:" not in planned_payload["reply"]
    assert "Шаги:" in planned_payload["reply"]

    run_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-plan-run",
            "model": "gemini",
            "message": f"Подтвердить GitHub PR {planned_task['id']}",
        },
        headers={"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_token},
    )

    assert run_response.status_code == 200
    completed_payload = run_response.get_json()
    completed_task = completed_payload["github_tool"]["task"]
    assert completed_payload["github_tool"]["status"] == "pull_request_opened"
    assert completed_task["branch_name"] == "remind/test-task"
    assert completed_task["pull_request_url"].endswith("/pull/7")
    assert "Готово: создан Pull Request" in completed_payload["reply"]
    assert "Ветка:" in completed_payload["reply"]
    assert "```diff" not in completed_payload["reply"]
    assert completed_payload["github_tool"]["task"]["diff"].startswith("diff --git")

    with app.app_context():
        chat = UserChatHistory.query.filter_by(
            user_id=user_id,
            session_id="chat-github-plan-run",
        ).first()
        saved_messages = chat.get_messages()
        assert saved_messages[-1]["github_tool"]["task"]["repo_full_name"] == "ReNothingg/ReMind"
        assert saved_messages[-1]["github_tool"]["task"]["diff"].startswith("diff --git")


def test_github_chat_summarizes_actual_recent_pr_changes_without_hallucinating(
    app, client, create_confirmed_user, login, monkeypatch
):
    _patch_github_chat(monkeypatch)

    user_id = _login_confirmed_user(client, create_confirmed_user, login)
    _add_installation(app, user_id)
    csrf_token = client.get("/health").headers.get("X-CSRF-Token")
    headers = {"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_token}

    plan_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-change-summary",
            "model": "gemini",
            "message": "В GitHub ReNothingg/ReMind добавь страницу настроек",
        },
        headers=headers,
    )
    planned_task = plan_response.get_json()["github_tool"]["task"]

    run_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-change-summary",
            "model": "gemini",
            "message": f"Подтвердить GitHub PR {planned_task['id']}",
        },
        headers=headers,
    )
    assert run_response.status_code == 200

    summary_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-change-summary",
            "model": "gemini",
            "message": "И какие изменения по коду ты сделал? Расскажи",
        },
        headers=headers,
    )

    assert summary_response.status_code == 200
    payload = summary_response.get_json()
    reply = payload["reply"]
    assert payload["github_tool"]["status"] == "summary"
    assert "По фактическому GitHub PR" in reply
    assert "`src/App.tsx`" in reply
    assert "1 добавлено, 1 удалено" in reply
    assert "добавлено: `export default function App() { return <main>New</main>; }`" in reply
    assert "удалено: `export default function App() { return <main>Old</main>; }`" in reply
    assert "backend/app.py" not in reply
    assert "MAX_HISTORY_LENGTH" not in reply

    followup_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-change-summary",
            "model": "gemini",
            "message": "не хочешь еще 2 файла поменять какие нибудь",
        },
        headers=headers,
    )

    assert followup_response.status_code == 200
    followup_payload = followup_response.get_json()
    assert followup_payload["github_tool"]["status"] == "planned"
    assert followup_payload["github_tool"]["task"]["repo_full_name"] == "ReNothingg/ReMind"
    assert "По фактическому GitHub PR" not in followup_payload["reply"]


def test_github_chat_uses_ai_router_for_contextual_followup_task(
    app, client, create_confirmed_user, login, monkeypatch
):
    github_chat = _patch_github_chat(monkeypatch)

    user_id = _login_confirmed_user(client, create_confirmed_user, login)
    _add_installation(app, user_id)
    csrf_token = client.get("/health").headers.get("X-CSRF-Token")
    headers = {"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_token}

    first_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-ai-router",
            "model": "gemini",
            "message": "В GitHub ReNothingg/devex-pr-agent найди баги",
        },
        headers=headers,
    )
    assert first_response.status_code == 200

    def fake_router(prompt):
        payload = json.loads(prompt)
        assert payload["recent_repo"] == "ReNothingg/devex-pr-agent"
        assert "туда ещё пару файлов тронуть" in payload["latest_user_message"]
        return {
            "intent": "task",
            "confidence": 0.91,
            "repo_full_name": "ReNothingg/devex-pr-agent",
            "use_recent_repo": True,
            "use_recent_task": False,
            "task_text": "Измени еще пару файлов аккуратно",
        }

    monkeypatch.setattr(github_chat, "call_gemini_json", fake_router)
    followup_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-ai-router",
            "model": "gemini",
            "message": "а можно туда ещё пару файлов тронуть нормально?",
        },
        headers=headers,
    )

    assert followup_response.status_code == 200
    payload = followup_response.get_json()
    assert payload["github_tool"]["status"] == "planned"
    assert payload["github_tool"]["task"]["repo_full_name"] == "ReNothingg/devex-pr-agent"
    assert payload["github_tool"]["task"]["task"] == "Измени еще пару файлов аккуратно"


def test_github_chat_explains_recent_noop_result_without_hallucinating(
    app, client, create_confirmed_user, login, monkeypatch
):
    _patch_github_chat(monkeypatch, NoopOnlyGitHubAgentService)

    user_id = _login_confirmed_user(client, create_confirmed_user, login)
    _add_installation(app, user_id)
    csrf_token = client.get("/health").headers.get("X-CSRF-Token")
    headers = {"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_token}

    plan_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-noop-explain",
            "model": "gemini",
            "message": "В GitHub ReNothingg/devex-pr-agent найди баги",
        },
        headers=headers,
    )
    assert plan_response.status_code == 200
    planned_task = plan_response.get_json()["github_tool"]["task"]

    run_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-noop-explain",
            "model": "gemini",
            "message": f"Подтвердить GitHub PR {planned_task['id']}",
        },
        headers=headers,
    )
    assert run_response.status_code == 200
    run_payload = run_response.get_json()
    assert run_payload["github_tool"]["status"] == "completed_no_changes"
    assert "PR не создан" in run_payload["reply"]
    assert "AI-редактор предложил только правки" in run_payload["reply"]
    assert "The AI editor only proposed" not in run_payload["reply"]

    explain_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-noop-explain",
            "model": "gemini",
            "message": "Че?",
        },
        headers=headers,
    )

    assert explain_response.status_code == 200
    payload = explain_response.get_json()
    reply = payload["reply"]
    assert payload["github_tool"]["status"] == "summary"
    assert "По фактической GitHub-задаче" in reply
    assert "PR не создан" in reply
    assert "фактический diff пустой" in reply
    assert "AI-редактор предложил только правки" in reply
    assert "The AI editor only proposed" not in reply
    assert "backend/app.py" not in reply
    assert "MAX_HISTORY_LENGTH" not in reply


def test_github_chat_uses_recent_repo_context_for_followup_task(
    app, client, create_confirmed_user, login, monkeypatch
):
    _patch_github_chat(monkeypatch)

    user_id = _login_confirmed_user(client, create_confirmed_user, login)
    _add_installation(app, user_id)
    csrf_token = client.get("/health").headers.get("X-CSRF-Token")
    headers = {"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_token}

    first_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-repo-followup",
            "model": "gemini",
            "message": "В GitHub ReNothingg/devex-pr-agent найди баги",
        },
        headers=headers,
    )
    assert first_response.status_code == 200
    assert first_response.get_json()["github_tool"]["task"]["repo_full_name"] == "ReNothingg/devex-pr-agent"

    followup_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-repo-followup",
            "model": "gemini",
            "message": "Сделай там оформление requirements.txt красивее",
        },
        headers=headers,
    )

    assert followup_response.status_code == 200
    payload = followup_response.get_json()
    assert payload["github_tool"]["status"] == "planned"
    assert payload["github_tool"]["task"]["repo_full_name"] == "ReNothingg/devex-pr-agent"
    assert "Укажите репозиторий" not in payload["reply"]


def test_github_chat_intercepts_correction_followups_in_recent_repo_context(
    app, client, create_confirmed_user, login, monkeypatch
):
    _patch_github_chat(monkeypatch)

    user_id = _login_confirmed_user(client, create_confirmed_user, login)
    _add_installation(app, user_id)
    csrf_token = client.get("/health").headers.get("X-CSRF-Token")
    headers = {"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_token}

    first_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-correction-followup",
            "model": "gemini",
            "message": "В GitHub ReNothingg/devex-pr-agent найди баги",
        },
        headers=headers,
    )
    assert first_response.status_code == 200

    correction_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-correction-followup",
            "model": "gemini",
            "message": "Но ты не внес изменения в код...",
        },
        headers=headers,
    )
    assert correction_response.status_code == 200
    correction_payload = correction_response.get_json()
    assert correction_payload["github_tool"]["status"] == "planned"
    assert correction_payload["github_tool"]["task"]["repo_full_name"] == "ReNothingg/devex-pr-agent"
    assert "Подтвердить GitHub PR" in correction_payload["reply"]

    short_followup_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-correction-followup",
            "model": "gemini",
            "message": "Ну сделай",
        },
        headers=headers,
    )
    assert short_followup_response.status_code == 200
    short_payload = short_followup_response.get_json()
    assert short_payload["github_tool"]["status"] == "planned"
    assert short_payload["github_tool"]["task"]["repo_full_name"] == "ReNothingg/devex-pr-agent"


def test_github_chat_uses_recent_pr_branch_for_this_comments_followup(
    app, client, create_confirmed_user, login, monkeypatch
):
    _patch_github_chat(monkeypatch)

    user_id = _login_confirmed_user(client, create_confirmed_user, login)
    _add_installation(app, user_id)
    csrf_token = client.get("/health").headers.get("X-CSRF-Token")
    headers = {"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_token}

    plan_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-recent-pr-branch",
            "model": "gemini",
            "message": "В GitHub ReNothingg/devex-pr-agent сделай оформление requirements.txt красивее",
        },
        headers=headers,
    )
    planned_task = plan_response.get_json()["github_tool"]["task"]
    run_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-recent-pr-branch",
            "model": "gemini",
            "message": f"Подтвердить GitHub PR {planned_task['id']}",
        },
        headers=headers,
    )
    assert run_response.status_code == 200
    assert run_response.get_json()["github_tool"]["task"]["branch_name"] == "remind/test-task"

    followup_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-recent-pr-branch",
            "model": "gemini",
            "message": "А можешь вот все эти комментарии удалить?",
        },
        headers=headers,
    )

    assert followup_response.status_code == 200
    payload = followup_response.get_json()
    assert payload["github_tool"]["status"] == "planned"
    assert payload["github_tool"]["task"]["repo_full_name"] == "ReNothingg/devex-pr-agent"
    assert payload["github_tool"]["task"]["base_branch"] == "remind/test-task"


def test_github_chat_access_question_uses_connected_tool(
    app, client, create_confirmed_user, login, monkeypatch
):
    _patch_github_chat(monkeypatch)

    user_id = _login_confirmed_user(client, create_confirmed_user, login)
    _add_installation(app, user_id)
    csrf_token = client.get("/health").headers.get("X-CSRF-Token")

    response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-info-access",
            "model": "gemini",
            "message": "У тебя есть доступ к гитхабе?",
        },
        headers={"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 200
    payload = response.get_json()
    reply = payload["reply"]
    assert payload["github_tool"]["status"] == "info"
    assert payload["github_tool"]["repository_count"] == 2
    assert "GitHub подключен" in reply
    assert "ReNothingg/ReMind" in reply
    assert "не буду придумывать" in reply


def test_github_chat_profile_followup_uses_recent_context(
    app, client, create_confirmed_user, login, monkeypatch
):
    _patch_github_chat(monkeypatch)

    user_id = _login_confirmed_user(client, create_confirmed_user, login)
    _add_installation(app, user_id)
    csrf_token = client.get("/health").headers.get("X-CSRF-Token")
    headers = {"User-Agent": "Mozilla/5.0 (pytest)", "X-CSRF-Token": csrf_token}

    first_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-info-profile",
            "model": "gemini",
            "message": "ReNothingg это мой профиль гита",
        },
        headers=headers,
    )
    assert first_response.status_code == 200

    followup_response = client.post(
        "/chat",
        data={
            "session_id": "chat-github-info-profile",
            "model": "gemini",
            "message": "Посмотри и скажи",
        },
        headers=headers,
    )

    assert followup_response.status_code == 200
    payload = followup_response.get_json()
    reply = payload["reply"]
    assert payload["github_tool"]["status"] == "info"
    assert payload["github_tool"]["profile_login"] == "ReNothingg"
    assert "По профилю `ReNothingg`" in reply
    assert "не буду придумывать" in reply


def test_github_agent_prompts_preserve_russian_user_language():
    from services.github_app import build_edit_prompt, build_plan_prompt

    repo_map = {
        "flat": [{"path": "src/App.tsx", "type": "file"}],
        "stats": {"files": 1, "directories": 1, "nodes": 2},
    }
    file_contexts = [{"path": "src/App.tsx", "content": "export default function App() {}", "size": 32}]

    plan_prompt = json.loads(
        build_plan_prompt(
            "Найди баги в коде",
            "ReNothingg/ReMind",
            "main",
            repo_map,
            file_contexts,
        )
    )
    edit_prompt = json.loads(
        build_edit_prompt(
            "Найди баги в коде",
            "ReNothingg/ReMind",
            "main",
            {"files": [{"path": "src/App.tsx"}]},
            repo_map,
            file_contexts,
        )
    )

    assert plan_prompt["response_language"] == "Russian"
    assert edit_prompt["response_language"] == "Russian"
    assert "Write every user-facing JSON string value in Russian" in plan_prompt["instruction"]
    assert "Write every user-facing JSON string value in Russian" in edit_prompt["instruction"]
    assert "preserve the existing dependency set" in plan_prompt["instruction"]
    assert "preserve the existing dependency set" in edit_prompt["instruction"]
    assert "какие-нибудь правки" in plan_prompt["instruction"]
    assert "какие-нибудь правки" in edit_prompt["instruction"]
    assert "Do not alter CSS colors" in edit_prompt["instruction"]
    assert plan_prompt["editing_policy"]["allow_ai_selected_safe_improvements"] is False
    assert edit_prompt["editing_policy"]["allow_ai_selected_safe_improvements"] is False

    exploratory_prompt = json.loads(
        build_edit_prompt(
            "Ну хоть какие-то 2 файла поменяй",
            "ReNothingg/ReMind",
            "main",
            {"files": [{"path": "src/App.tsx"}, {"path": "src/utils.ts"}]},
            repo_map,
            file_contexts,
        )
    )
    assert exploratory_prompt["editing_policy"]["allow_ai_selected_safe_improvements"] is True
    assert exploratory_prompt["editing_policy"]["requested_changed_files"] == 2
    assert "AI-selected" in exploratory_prompt["instruction"]


def test_github_agent_selects_default_context_for_generic_tasks():
    from services.github_app import select_candidate_paths

    paths = select_candidate_paths(
        [
            {"path": "assets/logo.png", "type": "file"},
            {"path": "backend/static/styles.css", "type": "file"},
            {"path": "backend/app.py", "type": "file"},
            {"path": "README.md", "type": "file"},
            {"path": "requirements.txt", "type": "file"},
        ],
        "Ну хоть какие-то 2 файла поменяй",
        3,
    )

    assert paths == ["README.md", "requirements.txt", "backend/app.py"]


def test_github_agent_filters_noop_file_edits():
    from services.github_app import _filter_noop_edits

    edit_payload = {
        "edits": [
            {
                "path": "requirements.txt",
                "action": "update",
                "content": "Flask==3.0.3\n",
                "reason": "unchanged",
            },
            {
                "path": "backend/app.py",
                "action": "update",
                "content": "print('changed')\n",
                "reason": "real edit",
            },
        ]
    }
    skipped = _filter_noop_edits(
        edit_payload,
        [
            {"path": "requirements.txt", "content": "Flask==3.0.3\n", "exists": True},
            {"path": "backend/app.py", "content": "print('old')\n", "exists": True},
        ],
    )

    assert skipped == [{"path": "requirements.txt", "action": "update", "reason": "content_unchanged"}]
    assert [item["path"] for item in edit_payload["edits"]] == ["backend/app.py"]
    assert edit_payload["skipped_edits"][0]["path"] == "requirements.txt"


def test_github_agent_sanitizes_no_change_findings_that_claim_edits():
    from services.github_app import _sanitize_no_change_findings

    edit_payload = {
        "findings": [
            "Не обнаружено детерминированных дефектов.",
            "В файле backend/static/app.js удалены все комментарии.",
            "backend/app.py updated for readability.",
        ]
    }

    _sanitize_no_change_findings(edit_payload)

    assert edit_payload["findings"] == ["Не обнаружено детерминированных дефектов."]


def test_github_agent_filters_cosmetic_css_token_only_edits_for_vague_bugfix():
    from services.github_app import _filter_unsafe_edits

    original = (
        ":root {\n"
        "  --line-strong: #a8a8a0;\n"
        "  --muted: #686866;\n"
        "}\n"
    )
    changed = (
        ":root {\n"
        "  --line-strong: #a8a0;\n"
        "  --muted: #6866;\n"
        "}\n"
    )
    edit_payload = {
        "edits": [
            {
                "path": "backend/static/styles.css",
                "action": "update",
                "content": changed,
                "reason": "minor bugfix",
            }
        ]
    }

    skipped = _filter_unsafe_edits(
        edit_payload,
        [{"path": "backend/static/styles.css", "content": original, "exists": True}],
        "Найди баги и сделай какие-нибудь багфиксы",
        {},
    )

    assert skipped == [
        {
            "path": "backend/static/styles.css",
            "action": "update",
            "reason": "cosmetic_css_token_only",
        }
    ]
    assert edit_payload["edits"] == []


def test_github_agent_allows_css_token_edits_when_user_asks_for_colors():
    from services.github_app import _filter_unsafe_edits

    original = ":root {\n  --accent: #111111;\n}\n"
    changed = ":root {\n  --accent: #0f766e;\n}\n"
    edit_payload = {
        "edits": [
            {
                "path": "backend/static/styles.css",
                "action": "update",
                "content": changed,
                "reason": "update requested theme color",
            }
        ]
    }

    skipped = _filter_unsafe_edits(
        edit_payload,
        [{"path": "backend/static/styles.css", "content": original, "exists": True}],
        "Измени цвет темы в CSS",
        {},
    )

    assert skipped == []
    assert edit_payload["edits"][0]["path"] == "backend/static/styles.css"
