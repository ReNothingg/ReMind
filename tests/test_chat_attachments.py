from ai_engine.gemini import _prepare_history
from services.files import restore_stored_file_for_model
import services.files as file_services


def _stored_file(name: str = "0123456789abcdef0123456789abcdef.txt") -> dict:
    return {
        "url_path": f"/uploads/{name}",
        "mime_type": "text/plain",
        "original_name": "notes.txt",
    }


def test_stored_attachment_is_safely_restored_for_regeneration(monkeypatch, tmp_path):
    monkeypatch.setattr(file_services, "UPLOAD_FOLDER", tmp_path)
    path = tmp_path / "0123456789abcdef0123456789abcdef.txt"
    path.write_text("attachment context", encoding="utf-8")

    restored = restore_stored_file_for_model(_stored_file())

    assert restored is not None
    assert restored["url_path"] == _stored_file()["url_path"]
    assert "attachment context" in restored["model_part"]["text"]


def test_stored_attachment_rejects_traversal_and_budget_bypass(monkeypatch, tmp_path):
    monkeypatch.setattr(file_services, "UPLOAD_FOLDER", tmp_path)
    path = tmp_path / "0123456789abcdef0123456789abcdef.txt"
    path.write_text("too large for this budget", encoding="utf-8")

    assert restore_stored_file_for_model(
        {"url_path": "/uploads/../users.db", "original_name": "users.db"}
    ) is None
    assert restore_stored_file_for_model(_stored_file(), max_bytes=2) is None


def test_only_canonical_history_can_rehydrate_stored_attachments(monkeypatch, tmp_path):
    monkeypatch.setattr(file_services, "UPLOAD_FOLDER", tmp_path)
    path = tmp_path / "0123456789abcdef0123456789abcdef.txt"
    path.write_text("private attachment context", encoding="utf-8")
    history = [
        {
            "role": "user",
            "parts": [{"text": "Review this"}, {"file": _stored_file()}],
        },
        {"role": "model", "parts": [{"text": "Sure"}]},
    ]

    untrusted = _prepare_history(history, allow_stored_attachments=False)
    canonical = _prepare_history(history, allow_stored_attachments=True)

    assert "private attachment context" not in str(untrusted)
    assert "private attachment context" in str(canonical)
