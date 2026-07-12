"""Deduplicate user chat sessions and enforce one row per user/session.

Revision ID: dedupe_chat_sessions
Revises: add_ai_response_feedback
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from alembic import op
import sqlalchemy as sa


revision = "dedupe_chat_sessions"
down_revision = "add_ai_response_feedback"
branch_labels = None
depends_on = None


def _message_signature(message: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            {"role": message.get("role"), "parts": message.get("parts")},
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _message_paths(messages: list[dict]) -> list[list[dict]]:
    if not any("parent_id" in message for message in messages):
        return [messages]

    by_parent: dict[str | None, list[dict]] = defaultdict(list)
    valid_ids = {str(message.get("id")) for message in messages if message.get("id")}
    for message in messages:
        parent_id = message.get("parent_id")
        if parent_id is not None and str(parent_id) not in valid_ids:
            parent_id = None
        by_parent[parent_id].append(message)
    for siblings in by_parent.values():
        siblings.sort(key=lambda message: bool(message.get("is_active")))

    paths: list[list[dict]] = []

    def visit(message: dict, path: list[dict], visited: set[str]) -> None:
        message_id = str(message.get("id") or "")
        if not message_id or message_id in visited:
            paths.append(path)
            return
        next_path = [*path, message]
        children = by_parent.get(message_id, [])
        if not children:
            paths.append(next_path)
            return
        for child in children:
            visit(child, next_path, {*visited, message_id})

    for root in by_parent.get(None, []):
        visit(root, [], set())
    return paths or [messages]


def _merged_messages(rows: list[dict]) -> str:
    parsed: list[list[dict]] = []
    # Rows arrive newest first. Replaying oldest-to-newest makes the newest
    # conversation path the selected branch while retaining every older path.
    for row in reversed(rows):
        try:
            messages = json.loads(row.get("messages_data") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            messages = []
        if isinstance(messages, list):
            parsed.append([message for message in messages if isinstance(message, dict)])

    merged: list[dict] = []
    node_by_key: dict[tuple[str | None, str, str], dict] = {}
    used_ids: set[str] = set()
    for messages in parsed:
        for path in _message_paths(messages):
            previous: dict | None = None
            for source in path:
                role = str(source.get("role") or "user")
                if previous is not None and role == previous.get("role"):
                    parent_id = previous.get("parent_id")
                else:
                    parent_id = previous.get("id") if previous else None
                signature = _message_signature(source)
                key = (parent_id, role, signature)
                node = node_by_key.get(key)
                if node is None:
                    candidate_id = str(source.get("id") or "")
                    if not candidate_id or candidate_id in used_ids:
                        candidate_id = f"legacy_{hashlib.sha256(f'{parent_id}:{role}:{signature}'.encode()).hexdigest()[:20]}"
                    node = {
                        key_name: value
                        for key_name, value in source.items()
                        if key_name not in {"variants", "current_variant_index", "parent_id", "is_active"}
                    }
                    node["id"] = candidate_id
                    node["parent_id"] = parent_id
                    node["is_active"] = True
                    merged.append(node)
                    node_by_key[key] = node
                    used_ids.add(candidate_id)
                for sibling in merged:
                    if sibling.get("parent_id") == parent_id:
                        sibling["is_active"] = sibling is node
                previous = node
    return json.dumps(merged, ensure_ascii=False)


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, user_id, session_id, title, messages_data, mind_id, created_at, updated_at "
            "FROM user_chat_history ORDER BY user_id, session_id, updated_at DESC, id DESC"
        )
    ).mappings().all()
    grouped: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["user_id"], row["session_id"])].append(dict(row))

    for duplicates in grouped.values():
        if len(duplicates) < 2:
            continue
        keeper = duplicates[0]
        best_title = next(
            (
                row.get("title")
                for row in duplicates
                if row.get("title") and row.get("title") != "Новый чат"
            ),
            keeper.get("title") or "Новый чат",
        )
        mind_id = next((row.get("mind_id") for row in duplicates if row.get("mind_id")), None)
        connection.execute(
            sa.text(
                "UPDATE user_chat_history SET title=:title, messages_data=:messages_data, "
                "mind_id=:mind_id WHERE id=:keeper_id"
            ),
            {
                "title": best_title,
                "messages_data": _merged_messages(duplicates),
                "mind_id": mind_id,
                "keeper_id": keeper["id"],
            },
        )
        duplicate_ids = [row["id"] for row in duplicates[1:]]
        connection.execute(
            sa.text("DELETE FROM user_chat_history WHERE id IN :ids").bindparams(
                sa.bindparam("ids", expanding=True)
            ),
            {"ids": duplicate_ids},
        )

    inspector = sa.inspect(connection)
    unique_columns = {"user_id", "session_id"}
    constraint_exists = any(
        set(constraint.get("column_names") or []) == unique_columns
        for constraint in inspector.get_unique_constraints("user_chat_history")
    )
    index_exists = any(
        bool(index.get("unique"))
        and set(index.get("column_names") or []) == unique_columns
        for index in inspector.get_indexes("user_chat_history")
    )
    if not constraint_exists and not index_exists:
        with op.batch_alter_table("user_chat_history") as batch_op:
            batch_op.create_unique_constraint(
                "uq_user_chat_history_user_session", ["user_id", "session_id"]
            )


def downgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    constraint_names = {
        constraint.get("name")
        for constraint in inspector.get_unique_constraints("user_chat_history")
    }
    if "uq_user_chat_history_user_session" in constraint_names:
        with op.batch_alter_table("user_chat_history") as batch_op:
            batch_op.drop_constraint("uq_user_chat_history_user_session", type_="unique")
        return
    index_names = {
        index.get("name") for index in inspector.get_indexes("user_chat_history")
    }
    if "uq_user_chat_history_user_session" in index_names:
        op.drop_index(
            "uq_user_chat_history_user_session",
            table_name="user_chat_history",
        )
