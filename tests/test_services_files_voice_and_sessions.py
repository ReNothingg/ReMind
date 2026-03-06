import io
import json
import time

from werkzeug.datastructures import FileStorage

import services.files as file_service
import services.voice as voice_service
from services.chat_history import _generate_guest_session_token, write_chat_file
from utils.auth import ChatShare, UserChatHistory, db


def test_handle_file_upload_accepts_valid_text_files(monkeypatch, tmp_path):
    monkeypatch.setattr(file_service, "UPLOAD_FOLDER", tmp_path)
    monkeypatch.setattr(file_service, "validate_file_content", lambda _path: (True, None))
    monkeypatch.setattr(file_service, "validate_mime_type", lambda _path: (True, "text/plain"))
    monkeypatch.setattr(file_service, "is_safe_to_serve", lambda _path: True)
    monkeypatch.setattr(file_service, "PIL_AVAILABLE", False)

    upload = FileStorage(
        stream=io.BytesIO(b"hello world"),
        filename="notes.txt",
        content_type="text/plain",
    )

    saved = file_service.handle_file_upload(upload, user_id="user-1")

    assert saved is not None
    assert saved["mime_type"] == "text/plain"
    assert saved["original_name"] == "notes.txt"
    assert saved["url_path"].startswith("/uploads/")
    assert "hello world" in saved["model_part"]["text"]


def test_handle_file_upload_rejects_invalid_input_and_cleans_up(monkeypatch, tmp_path):
    monkeypatch.setattr(file_service, "UPLOAD_FOLDER", tmp_path)

    bad_user_upload = FileStorage(
        stream=io.BytesIO(b"hello"),
        filename="notes.txt",
        content_type="text/plain",
    )
    monkeypatch.setattr(
        file_service.InputValidator,
        "validate_text",
        staticmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad user"))),
    )
    assert file_service.handle_file_upload(bad_user_upload, user_id="bad") is None

    monkeypatch.setattr(
        file_service.InputValidator,
        "validate_text",
        staticmethod(lambda value, **_kwargs: value),
    )
    blocked_extension = FileStorage(
        stream=io.BytesIO(b"hello"),
        filename="payload.exe",
        content_type="application/octet-stream",
    )
    assert file_service.handle_file_upload(blocked_extension, user_id="user-1") is None

    content_fail = FileStorage(
        stream=io.BytesIO(b"hello"),
        filename="notes.txt",
        content_type="text/plain",
    )
    monkeypatch.setattr(file_service, "validate_file_content", lambda _path: (False, "bad"))
    assert file_service.handle_file_upload(content_fail, user_id="user-1") is None
    assert list(tmp_path.iterdir()) == []

    mime_fail = FileStorage(
        stream=io.BytesIO(b"hello"),
        filename="notes.txt",
        content_type="text/plain",
    )
    monkeypatch.setattr(file_service, "validate_file_content", lambda _path: (True, None))
    monkeypatch.setattr(file_service, "validate_mime_type", lambda _path: (False, None))
    assert file_service.handle_file_upload(mime_fail, user_id="user-1") is None
    assert list(tmp_path.iterdir()) == []

    unsafe_file = FileStorage(
        stream=io.BytesIO(b"hello"),
        filename="notes.txt",
        content_type="text/plain",
    )
    monkeypatch.setattr(file_service, "validate_mime_type", lambda _path: (True, "text/plain"))
    monkeypatch.setattr(file_service, "is_safe_to_serve", lambda _path: False)
    monkeypatch.setattr(file_service, "PIL_AVAILABLE", False)
    assert file_service.handle_file_upload(unsafe_file, user_id="user-1") is None
    assert list(tmp_path.iterdir()) == []


def test_synthesize_text_segments_covers_empty_success_detection_and_error(monkeypatch):
    assert voice_service.synthesize_text_segments("   ") == []

    monkeypatch.setattr(voice_service, "detect", lambda _text: "en")
    monkeypatch.setattr(voice_service.gtts_langs, "tts_langs", lambda: {"en": "English"})

    class FakeTTS:
        def __init__(self, text, lang, slow):
            self.text = text
            self.lang = lang
            self.slow = slow

        def write_to_fp(self, fp):
            fp.write(b"audio-bytes")

    monkeypatch.setattr(voice_service, "gTTS", FakeTTS)
    success = voice_service.synthesize_text_segments("This is a longer sentence")
    assert success[0]["lang"] == "en"
    assert success[0]["audio_base64"]
    assert success[0]["error"] is None

    class BrokenTTS:
        def __init__(self, *args, **kwargs):
            pass

        def write_to_fp(self, _fp):
            raise RuntimeError("tts failed")

    monkeypatch.setattr(
        voice_service,
        "detect",
        lambda _text: (_ for _ in ()).throw(voice_service.LangDetectException(0, "fail")),
    )
    monkeypatch.setattr(voice_service, "gTTS", BrokenTTS)
    errored = voice_service.synthesize_text_segments("another sentence for fallback")
    assert errored[0]["lang"] == voice_service.DEFAULT_LANGUAGE
    assert errored[0]["audio_base64"] is None
    assert "tts failed" in errored[0]["error"]


def test_session_routes_cover_create_history_guest_listing_share_and_delete(
    client, app, create_confirmed_user, login, monkeypatch, tmp_path
):
    guest_create = client.post("/sessions")
    assert guest_create.status_code == 200
    assert guest_create.get_json()["session_id"].startswith("guest_")

    user_id, email, password = create_confirmed_user()

    with app.app_context():
        db.session.add(
            UserChatHistory(
                user_id=user_id,
                session_id="history_session_case",
                title="History Session",
                messages_data=json.dumps([{"role": "user", "parts": [{"text": "hello history"}]}]),
            )
        )
        db.session.add(
            UserChatHistory(
                user_id=user_id,
                session_id="public_history_case",
                title="Public Session",
                messages_data=json.dumps([{"role": "user", "parts": [{"text": "shared hello"}]}]),
            )
        )
        db.session.add(
            ChatShare(
                user_id=user_id,
                session_id="public_history_case",
                public_id="public_history_id",
                is_public=True,
            )
        )
        db.session.commit()

    login_response = login(email, password)
    assert login_response.status_code == 200

    csrf_value = client.get("/health").headers.get("X-CSRF-Token")
    assert csrf_value

    invalid_create = client.post(
        "/sessions",
        json={"session_id": "short"},
        headers={"X-CSRF-Token": csrf_value},
    )
    assert invalid_create.status_code == 400
    assert invalid_create.get_json()["error"]["code"] == "invalid_session_id"

    created = client.post(
        "/sessions",
        json={"session_id": "session_created_for_tests", "title": "Created Session"},
        headers={"X-CSRF-Token": csrf_value},
    )
    assert created.status_code == 200
    assert created.get_json()["session_id"] == "session_created_for_tests"

    private_history = client.get("/sessions/history_session_case/history")
    assert private_history.status_code == 200
    assert private_history.get_json()["is_owner"] is True

    public_history = client.get("/sessions/public_history_id/history")
    assert public_history.status_code == 200
    assert public_history.get_json()["is_public"] is True
    assert public_history.get_json()["read_only"] is False

    guest_client = app.test_client()

    public_history_as_guest = guest_client.get("/sessions/public_history_id/history")
    assert public_history_as_guest.status_code == 200
    assert public_history_as_guest.get_json()["is_public"] is True
    assert public_history_as_guest.get_json()["read_only"] is True
    assert public_history_as_guest.get_json()["public_id"] == "public_history_id"

    import routes.features.sessions as sessions_routes
    import services.chat_history as chat_history

    monkeypatch.setattr(sessions_routes, "ALLOW_GUEST_CHATS_SAVE", True)
    monkeypatch.setattr(chat_history, "CHATS_FOLDER", tmp_path)
    monkeypatch.setattr(chat_history, "SECRET_KEY", "pytest-secret")
    guest_session_id = "guest_session_route_case"
    write_chat_file(
        guest_session_id,
        {
            "history": [{"role": "user", "parts": [{"text": "guest history"}]}],
            "title": "Guest Session",
            "last_updated": 10,
        },
    )
    token = _generate_guest_session_token(guest_session_id, int(time.time()))
    guest_list = guest_client.get(
        f"/sessions?ids={guest_session_id}",
        headers={"X-Guest-Tokens": json.dumps({guest_session_id: token})},
    )
    assert guest_list.status_code == 200
    assert guest_list.get_json()["sessions"][0]["session_id"] == guest_session_id

    csrf_value = client.get("/health").headers.get("X-CSRF-Token")
    share_response = client.post(
        "/sessions/history_session_case/share",
        json={"is_public": True},
        headers={"X-CSRF-Token": csrf_value},
    )
    assert share_response.status_code == 200
    share_payload = share_response.get_json()
    assert share_payload["is_public"] is True
    assert share_payload["public_id"].startswith("p_")

    toggle_share = client.post(
        "/sessions/history_session_case/share",
        json={"is_public": False},
        headers={"X-CSRF-Token": csrf_value},
    )
    assert toggle_share.status_code == 200
    assert toggle_share.get_json()["is_public"] is False

    missing_delete = client.delete(
        "/sessions/missing_session",
        headers={"X-CSRF-Token": csrf_value},
    )
    assert missing_delete.status_code == 404

    deleted = client.delete(
        "/sessions/history_session_case",
        headers={"X-CSRF-Token": csrf_value},
    )
    assert deleted.status_code == 204

    with app.app_context():
        deleted_chat = UserChatHistory.query.filter_by(
            user_id=user_id, session_id="history_session_case"
        ).first()
        assert deleted_chat is None
