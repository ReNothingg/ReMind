import base64
import json
import re
import zipfile
from types import SimpleNamespace

from flask import Blueprint, Flask

from ai_engine.gemini import _python_activity_token
from ai_engine.personalization import render_python_tool_prompt
from routes.api_errors import ApiError
from routes.features import python as python_routes
from services import model_tools, python_runner


def test_python_runner_requires_authenticated_user(monkeypatch):
    monkeypatch.setattr(python_runner, "PYTHON_RUNNER_ENABLED", True)

    assert python_runner.python_runner_available(42) is True
    assert python_runner.python_runner_available(None) is False
    assert python_runner.execute_python("print(1)", user_id=None).output == {
        "ok": False,
        "error": "python_runner_unavailable",
    }
    assert python_runner.execute_python("", user_id=42).output == {
        "ok": False,
        "error": "invalid_code",
    }


def test_canvas_python_endpoint_requires_authentication(monkeypatch):
    app = Flask(__name__)
    blueprint = Blueprint("python_test_auth", __name__)
    python_routes.register_python_routes(blueprint)
    app.register_blueprint(blueprint)
    def reject_authentication():
        raise ApiError("Authentication required", status=401, code="auth_required")

    monkeypatch.setattr(python_routes, "require_authenticated_user_id", reject_authentication)

    response = app.test_client().post("/api/python/execute", json={"code": "print(1)"})

    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "auth_required"


def test_canvas_python_endpoint_delegates_to_isolated_runner(monkeypatch):
    app = Flask(__name__)
    blueprint = Blueprint("python_test_execute", __name__)
    python_routes.register_python_routes(blueprint)
    app.register_blueprint(blueprint)
    monkeypatch.setattr(python_routes, "require_authenticated_user_id", lambda: 42)
    monkeypatch.setattr(python_routes, "python_runner_available", lambda _user_id: True)
    def execute(code, *, user_id, allow_artifacts):
        return SimpleNamespace(
            output={"ok": True, "stdout": "3\\n", "stderr": "", "duration_ms": 12}
        )

    monkeypatch.setattr(python_routes, "execute_python", execute)

    response = app.test_client().post("/api/python/execute", json={"code": "print(1 + 2)"})

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "stdout": "3\\n",
        "stderr": "",
        "duration_ms": 12,
    }


def test_canvas_python_endpoint_rejects_oversized_code(monkeypatch):
    app = Flask(__name__)
    blueprint = Blueprint("python_test_size", __name__)
    python_routes.register_python_routes(blueprint)
    app.register_blueprint(blueprint)
    monkeypatch.setattr(python_routes, "require_authenticated_user_id", lambda: 42)
    monkeypatch.setattr(python_routes, "python_runner_available", lambda _user_id: True)
    def execute(*args, **kwargs):
        raise AssertionError("runner must not be called")

    monkeypatch.setattr(python_routes, "execute_python", execute)

    response = app.test_client().post(
        "/api/python/execute",
        json={"code": "x" * (python_runner.MAX_CODE_CHARS + 1)},
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_code"


def test_python_tool_declaration_is_authenticated_and_describes_inputs(monkeypatch, tmp_path):
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    source = upload_root / "stored.csv"
    source.write_text("value\n1\n", encoding="utf-8")
    files = [{"path": str(source), "original_name": "sales.csv"}]

    monkeypatch.setattr(python_runner, "PYTHON_RUNNER_ENABLED", True)
    monkeypatch.setattr(python_runner, "UPLOAD_FOLDER", upload_root)
    monkeypatch.setattr(model_tools, "_github_installations", lambda _user_id: [])

    authenticated = model_tools.model_tool_declarations(42, input_files=files)
    anonymous = model_tools.model_tool_declarations(None, input_files=files)
    python_declaration = next(item for item in authenticated if item["name"] == "python_execute")

    assert "sales.csv" in python_declaration["description"]
    assert python_declaration["parameters"]["required"] == ["code", "purpose"]
    assert not any(item["name"] == "python_execute" for item in anonymous)


def test_python_prompt_documents_exact_runtime_and_security_contract():
    prompt = render_python_tool_prompt()

    assert "Pillow 12.3.0" in prompt
    assert "pypdf 6.15.0" in prompt
    assert 'os.environ["REMIND_INPUT_DIR"]' in prompt
    assert 'os.environ["REMIND_OUTPUT_DIR"]' in prompt
    assert "Internet and local-network access are unavailable" in prompt
    assert "Do not deserialize pickle/joblib" in prompt
    assert "call `python_execute` in that response" in prompt
    assert "do not substitute `visualize`" in prompt
    assert "Keep planning, progress narration, and tool sequencing" in prompt
    assert "After every Python result" in prompt
    assert "must contain only the useful result" in prompt


def test_python_activity_contains_exact_bounded_code_and_terminal_metadata():
    code = 'print("<safe>")\n'
    token = _python_activity_token(
        "run-1",
        "python_completed",
        code=code,
        purpose="Check the generated chart before reporting it.",
        duration_ms=125,
        artifact_count=1,
    )
    encoded = re.search(r'data-b64="([^"]+)"', token).group(1)
    payload = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))

    assert payload == {
        "type": "python_execution",
        "id": "run-1",
        "status": "python_completed",
        "code": code,
        "purpose": "Check the generated chart before reporting it.",
        "duration_ms": 125,
        "artifact_count": 1,
    }


def test_available_inputs_reject_paths_outside_upload_root_and_symlinks(monkeypatch, tmp_path):
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    allowed = upload_root / "stored.csv"
    allowed.write_text("value\n1\n", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    symlink = upload_root / "linked.csv"
    symlink.symlink_to(allowed)

    monkeypatch.setattr(python_runner, "UPLOAD_FOLDER", upload_root)
    files = [
        {"path": str(allowed), "original_name": "sales.csv"},
        {"path": str(outside), "original_name": "secret.txt"},
        {"path": str(symlink), "original_name": "linked.csv"},
    ]

    assert python_runner.available_input_files(files) == ["sales.csv"]


def test_artifact_validation_rejects_invalid_json_and_unsafe_xlsx(tmp_path):
    invalid_json = tmp_path / "result.json"
    invalid_json.write_text("{not-json}", encoding="utf-8")
    unsafe_xlsx = tmp_path / "unsafe.xlsx"
    with zipfile.ZipFile(unsafe_xlsx, "w") as workbook:
        workbook.writestr("[Content_Types].xml", "<Types />")
        workbook.writestr("xl/workbook.xml", "<workbook />")
        workbook.writestr("../escape.txt", "blocked")

    assert python_runner._validate_artifact(invalid_json, ".json") is None
    assert python_runner._validate_artifact(unsafe_xlsx, ".xlsx") is None


def test_valid_json_artifact_is_canonicalized(tmp_path):
    artifact = tmp_path / "result.json"
    artifact.write_text(json.dumps({"ok": True}), encoding="utf-8")

    assert python_runner._validate_artifact(artifact, ".json") == "application/json"


def test_incomplete_model_code_is_rejected_before_execution(monkeypatch):
    issues = python_runner._code_quality_issues(
        "# ... (Fill Excel sheets) ...\n"
        "validation = {'audit_passed': True}\n"
        "print(validation)\n"
    )

    assert "placeholder_comment:1" in issues
    assert "hardcoded_success_flag:audit_passed:2" in issues
    assert python_runner._code_quality_issues(
        "checks = [weight_sum_ok, covariance_ok]\n"
        "validation = {'audit_passed': all(checks)}\n"
    ) == []
    monkeypatch.setattr(python_runner, "PYTHON_RUNNER_ENABLED", True)
    rejected = python_runner.execute_python(
        "validation = {'audit_passed': True}\nprint(validation)\n",
        user_id=42,
    )
    assert rejected.output["error"] == "incomplete_code"
    assert rejected.output["quality_issues"] == [
        "hardcoded_success_flag:audit_passed:1"
    ]


def test_artifact_metadata_exposes_workbook_structure_and_pdf_pages(tmp_path):
    workbook = tmp_path / "audit.xlsx"
    with zipfile.ZipFile(workbook, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0"?><workbook xmlns="urn:test"><sheets>'
            '<sheet name="Summary"/><sheet name="Validation"/>'
            '</sheets></workbook>',
        )
    pdf = tmp_path / "audit.pdf"
    pdf.write_bytes(b"%PDF-1.4\n/Type /Page\n/Type /Pages\n/Type /Page\n%%EOF")

    assert python_runner._artifact_metadata(workbook, ".xlsx") == {
        "kind": "workbook",
        "sheet_count": 2,
        "sheet_names": ["Summary", "Validation"],
    }
    assert python_runner._artifact_metadata(pdf, ".pdf") == {
        "kind": "pdf",
        "page_count": 2,
    }
