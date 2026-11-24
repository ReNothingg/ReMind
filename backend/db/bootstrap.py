from __future__ import annotations

from sqlalchemy import bindparam, inspect, text

from backend.db.models import Mind, MindPin, db

CHAT_SESSION_UNIQUE_INDEX = "uq_user_chat_history_user_session"


def ensure_chat_session_uniqueness(engine) -> None:
    inspector = inspect(engine)
    if "user_chat_history" not in inspector.get_table_names():
        return

    unique_columns = {"user_id", "session_id"}
    constraint_exists = any(
        set(constraint.get("column_names") or []) == unique_columns
        for constraint in inspector.get_unique_constraints("user_chat_history")
    )
    index_exists = any(
        bool(index.get("unique")) and set(index.get("column_names") or []) == unique_columns
        for index in inspector.get_indexes("user_chat_history")
    )
    if constraint_exists or index_exists:
        return

    from migrations.versions.dedupe_chat_sessions import _merged_messages

    with engine.begin() as connection:
        duplicate_keys = (
            connection.execute(
                text(
                    "SELECT user_id, session_id FROM user_chat_history "
                    "GROUP BY user_id, session_id HAVING COUNT(*) > 1"
                )
            )
            .mappings()
            .all()
        )
        for key in duplicate_keys:
            duplicates = [
                dict(row)
                for row in connection.execute(
                    text(
                        "SELECT id, user_id, session_id, title, messages_data, mind_id, "
                        "created_at, updated_at FROM user_chat_history "
                        "WHERE user_id=:user_id AND session_id=:session_id "
                        "ORDER BY updated_at DESC, id DESC"
                    ),
                    {"user_id": key["user_id"], "session_id": key["session_id"]},
                )
                .mappings()
                .all()
            ]
            keeper = duplicates[0]
            best_title = next(
                (
                    row.get("title")
                    for row in duplicates
                    if row.get("title") and row.get("title") != "Новый чат"
                ),
                keeper.get("title") or "Новый чат",
            )
            mind_id = next(
                (row.get("mind_id") for row in duplicates if row.get("mind_id")),
                None,
            )
            connection.execute(
                text(
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
                text("DELETE FROM user_chat_history WHERE id IN :ids").bindparams(
                    bindparam("ids", expanding=True)
                ),
                {"ids": duplicate_ids},
            )

    with engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {CHAT_SESSION_UNIQUE_INDEX} "
                "ON user_chat_history (user_id, session_id)"
            )
        )


LEGACY_DEFAULT_MIND_PUBLIC_IDS = (
    "mind_study_coach",
    "mind_code_reviewer",
    "mind_product_strategist",
    "mind_security_auditor",
)


def remove_legacy_default_minds(app):
    try:
        minds = Mind.query.filter(
            Mind.public_id.in_(LEGACY_DEFAULT_MIND_PUBLIC_IDS),
            Mind.is_system.is_(True),
        ).all()
        if not minds:
            return

        mind_ids = [mind.id for mind in minds]
        MindPin.query.filter(MindPin.mind_id.in_(mind_ids)).delete(synchronize_session=False)
        for mind in minds:
            db.session.delete(mind)
        db.session.commit()
        app.logger.info("Removed %s legacy default minds", len(minds))
    except Exception:
        db.session.rollback()
        app.logger.exception("Failed to remove legacy default minds")


def configure_sqlite(app):
    from sqlalchemy import event

    db_uri = (app.config.get("SQLALCHEMY_DATABASE_URI") or "").lower()
    if db_uri.startswith("sqlite:"):
        with app.app_context():
            engine = db.engine
            if not getattr(engine, "_remind_sqlite_pragmas", False):

                @event.listens_for(engine, "connect")
                def _set_sqlite_pragmas(dbapi_connection, _connection_record):
                    cursor = dbapi_connection.cursor()
                    cursor.execute("PRAGMA journal_mode=MEMORY")
                    cursor.execute("PRAGMA temp_store=MEMORY")
                    cursor.execute("PRAGMA synchronous=NORMAL")
                    cursor.close()

                engine._remind_sqlite_pragmas = True


def initialize_schema(app):
    db.create_all()
    inspector = inspect(db.engine)
    if "instructions" not in {
        column["name"] for column in inspector.get_columns("remind_workspace")
    }:
        with db.engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE remind_workspace ADD COLUMN instructions TEXT DEFAULT '' NOT NULL"
                )
            )
    date_time_type = (
        "TIMESTAMP" if db.engine.dialect.name in {"postgresql", "postgres"} else "DATETIME"
    )
    if "user" in inspector.get_table_names():
        user_columns = {column["name"] for column in inspector.get_columns("user")}
        if "name" not in user_columns:
            with db.engine.begin() as connection:
                connection.execute(text('ALTER TABLE "user" ADD COLUMN name VARCHAR(100)'))
                connection.execute(
                    text(
                        "UPDATE \"user\" SET name = username WHERE name IS NULL OR TRIM(name) = ''"
                    )
                )
            app.logger.info("Added missing user.name column to existing database")
        user_admin_columns = {
            "is_admin": 'ALTER TABLE "user" ADD COLUMN is_admin BOOLEAN DEFAULT FALSE NOT NULL',
            "is_banned": 'ALTER TABLE "user" ADD COLUMN is_banned BOOLEAN DEFAULT FALSE NOT NULL',
            "is_blocked": 'ALTER TABLE "user" ADD COLUMN is_blocked BOOLEAN DEFAULT FALSE NOT NULL',
            "moderation_reason": 'ALTER TABLE "user" ADD COLUMN moderation_reason VARCHAR(280)',
            "ban_reason": 'ALTER TABLE "user" ADD COLUMN ban_reason VARCHAR(280)',
            "block_reason": 'ALTER TABLE "user" ADD COLUMN block_reason VARCHAR(280)',
            "banned_until": f'ALTER TABLE "user" ADD COLUMN banned_until {date_time_type}',
            "blocked_until": f'ALTER TABLE "user" ADD COLUMN blocked_until {date_time_type}',
            "auth_version": 'ALTER TABLE "user" ADD COLUMN auth_version INTEGER DEFAULT 0 NOT NULL',
        }
        missing_user_admin_columns = [
            (column_name, ddl)
            for column_name, ddl in user_admin_columns.items()
            if column_name not in user_columns
        ]
        if missing_user_admin_columns:
            with db.engine.begin() as connection:
                for _column_name, ddl in missing_user_admin_columns:
                    connection.execute(text(ddl))
            app.logger.info("Added missing user admin/moderation columns")
    if "user_settings" in inspector.get_table_names():
        settings_columns = {column["name"] for column in inspector.get_columns("user_settings")}
        if "automatic_web_search" not in settings_columns:
            with db.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE user_settings "
                        "ADD COLUMN automatic_web_search BOOLEAN DEFAULT TRUE NOT NULL"
                    )
                )
            app.logger.info("Added missing user_settings.automatic_web_search column")
    if "user_chat_history" in inspector.get_table_names():
        chat_columns = {column["name"] for column in inspector.get_columns("user_chat_history")}
        chat_source_columns = {
            "source": (
                "ALTER TABLE user_chat_history ADD COLUMN source VARCHAR(32) DEFAULT 'web' NOT NULL"
            ),
            "external_ref_hash": (
                "ALTER TABLE user_chat_history ADD COLUMN external_ref_hash VARCHAR(64)"
            ),
            "workspace_id": (
                "ALTER TABLE user_chat_history ADD COLUMN workspace_id VARCHAR(32) "
                "CONSTRAINT fk_user_chat_history_workspace_id "
                "REFERENCES remind_workspace(id) ON DELETE SET NULL"
            ),
            "source_context_data": (
                "ALTER TABLE user_chat_history "
                "ADD COLUMN source_context_data TEXT DEFAULT '{}' NOT NULL"
            ),
        }
        missing_chat_source_columns = [
            ddl
            for column_name, ddl in chat_source_columns.items()
            if column_name not in chat_columns
        ]
        if missing_chat_source_columns:
            with db.engine.begin() as connection:
                for ddl in missing_chat_source_columns:
                    connection.execute(text(ddl))
            app.logger.info("Added missing chat metadata columns")
        with db.engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_user_chat_history_workspace_id ON user_chat_history (workspace_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_user_chat_history_user_external_ref "
                    "ON user_chat_history (user_id, external_ref_hash)"
                )
            )
    if "mind" in inspector.get_table_names():
        mind_columns = {column["name"] for column in inspector.get_columns("mind")}
        mind_admin_columns = {
            "allow_external_use": "ALTER TABLE mind ADD COLUMN allow_external_use BOOLEAN DEFAULT FALSE NOT NULL",
            "skill_ids": "ALTER TABLE mind ADD COLUMN skill_ids JSON",
            "custom_skills": "ALTER TABLE mind ADD COLUMN custom_skills JSON",
            "is_featured": "ALTER TABLE mind ADD COLUMN is_featured BOOLEAN DEFAULT FALSE NOT NULL",
            "is_banned": "ALTER TABLE mind ADD COLUMN is_banned BOOLEAN DEFAULT FALSE NOT NULL",
            "moderation_reason": "ALTER TABLE mind ADD COLUMN moderation_reason VARCHAR(280)",
        }
        missing_mind_admin_columns = [
            (column_name, ddl)
            for column_name, ddl in mind_admin_columns.items()
            if column_name not in mind_columns
        ]
        if missing_mind_admin_columns:
            with db.engine.begin() as connection:
                for _column_name, ddl in missing_mind_admin_columns:
                    connection.execute(text(ddl))
                connection.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_mind_is_featured ON mind (is_featured)")
                )
                connection.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_mind_is_banned ON mind (is_banned)")
                )
            app.logger.info("Added missing mind admin/moderation columns")
    if "user_chat_history" in inspector.get_table_names():
        chat_columns = {column["name"] for column in inspector.get_columns("user_chat_history")}
        if "mind_id" not in chat_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE user_chat_history ADD COLUMN mind_id INTEGER"))
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_user_chat_history_mind_id "
                        "ON user_chat_history (mind_id)"
                    )
                )
            app.logger.info("Added missing user_chat_history.mind_id column")
        ensure_chat_session_uniqueness(db.engine)
