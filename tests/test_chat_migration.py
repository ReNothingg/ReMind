import json

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError

import migrations.versions.dedupe_chat_sessions as migration
from migrations.versions.dedupe_chat_sessions import _merged_messages
from services.chat_history import _select_variant_in_graph, materialize_conversation_history
from utils.auth import ensure_chat_session_uniqueness


def test_duplicate_session_migration_keeps_unique_turns_and_alternatives():
    rows = [
        {
            "messages_data": json.dumps(
                [
                    {"id": "u1", "role": "user", "parts": [{"text": "Question"}]},
                    {"id": "a1", "role": "model", "parts": [{"text": "First"}]},
                ]
            )
        },
        {
            "messages_data": json.dumps(
                [
                    {"id": "u-copy", "role": "user", "parts": [{"text": "Question"}]},
                    {"id": "a2", "role": "model", "parts": [{"text": "Alternative"}]},
                ]
            )
        },
    ]

    merged = json.loads(_merged_messages(rows))

    assert {message["parts"][0]["text"] for message in merged} == {
        "Question",
        "First",
        "Alternative",
    }
    assert [message["parts"][0]["text"] for message in materialize_conversation_history(merged)] == [
        "Question",
        "First",
    ]


def test_duplicate_session_migration_preserves_edited_prompt_subtrees():
    rows = [
        {
            "messages_data": json.dumps(
                [
                    {"id": "u-edited", "role": "user", "parts": [{"text": "Edited"}]},
                    {"id": "a-edited", "role": "model", "parts": [{"text": "Edited answer"}]},
                ]
            )
        },
        {
            "messages_data": json.dumps(
                [
                    {"id": "u-original", "role": "user", "parts": [{"text": "Original"}]},
                    {"id": "a-original", "role": "model", "parts": [{"text": "Original answer"}]},
                    {"id": "u-follow", "role": "user", "parts": [{"text": "Follow-up"}]},
                    {"id": "a-follow", "role": "model", "parts": [{"text": "Continuation"}]},
                ]
            )
        },
    ]

    merged = json.loads(_merged_messages(rows))

    assert [message["parts"][0]["text"] for message in materialize_conversation_history(merged)] == [
        "Edited",
        "Edited answer",
    ]
    original_graph = _select_variant_in_graph(merged, "u-original")
    assert [
        message["parts"][0]["text"]
        for message in materialize_conversation_history(original_graph)
    ] == ["Original", "Original answer", "Follow-up", "Continuation"]


def test_migration_deduplicates_real_sqlite_rows_and_adds_unique_constraint(
    monkeypatch,
):
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE user_chat_history ("
                "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, session_id VARCHAR(100) NOT NULL, "
                "title VARCHAR(200), messages_data TEXT, mind_id INTEGER, "
                "created_at DATETIME, updated_at DATETIME)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO user_chat_history "
                "(id, user_id, session_id, title, messages_data, updated_at) VALUES "
                "(1, 7, 'duplicate', 'Older', :older, '2026-01-01'), "
                "(2, 7, 'duplicate', 'Newest', :newest, '2026-01-02')"
            ),
            {
                "older": json.dumps(
                    [
                        {"id": "u1", "role": "user", "parts": [{"text": "Question"}]},
                        {"id": "a1", "role": "model", "parts": [{"text": "Older"}]},
                    ]
                ),
                "newest": json.dumps(
                    [
                        {"id": "u2", "role": "user", "parts": [{"text": "Question"}]},
                        {"id": "a2", "role": "model", "parts": [{"text": "Newest"}]},
                    ]
                ),
            },
        )
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)
        migration.upgrade()

        rows = connection.execute(
            sa.text("SELECT title, messages_data FROM user_chat_history")
        ).mappings().all()
        assert len(rows) == 1
        assert rows[0]["title"] == "Newest"
        assert [
            message["parts"][0]["text"]
            for message in materialize_conversation_history(
                json.loads(rows[0]["messages_data"])
            )
        ] == ["Question", "Newest"]

        with pytest.raises(IntegrityError):
            connection.execute(
                sa.text(
                    "INSERT INTO user_chat_history "
                    "(user_id, session_id, title, messages_data) "
                    "VALUES (7, 'duplicate', 'Again', '[]')"
                )
            )


def test_runtime_startup_repairs_existing_database_without_migration_runner():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE user_chat_history ("
                "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, session_id VARCHAR(100) NOT NULL, "
                "title VARCHAR(200), messages_data TEXT, mind_id INTEGER, "
                "created_at DATETIME, updated_at DATETIME)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO user_chat_history "
                "(id, user_id, session_id, title, messages_data, updated_at) VALUES "
                "(1, 9, 'same', 'Old', '[]', '2026-01-01'), "
                "(2, 9, 'same', 'New', '[]', '2026-01-02')"
            )
        )

    ensure_chat_session_uniqueness(engine)

    with engine.connect() as connection:
        count = connection.execute(
            sa.text("SELECT COUNT(*) FROM user_chat_history")
        ).scalar_one()
    assert count == 1
    assert any(
        index.get("unique")
        and set(index.get("column_names") or []) == {"user_id", "session_id"}
        for index in sa.inspect(engine).get_indexes("user_chat_history")
    )
