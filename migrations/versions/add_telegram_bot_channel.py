"""Add Telegram bot chat sources and inline-result synchronization.

Revision ID: add_telegram_bot_channel
Revises: add_linked_auth_identities
Create Date: 2026-08-04
"""

import sqlalchemy as sa
from alembic import op

revision = "add_telegram_bot_channel"
down_revision = "add_linked_auth_identities"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user_chat_history", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("source", sa.String(length=32), server_default="web", nullable=False)
        )
        batch_op.add_column(sa.Column("external_ref_hash", sa.String(length=64)))
        batch_op.add_column(
            sa.Column("source_context_data", sa.Text(), server_default="{}", nullable=False)
        )
        batch_op.create_index("ix_user_chat_history_source", ["source"], unique=False)
        batch_op.create_index(
            "ix_user_chat_history_external_ref_hash", ["external_ref_hash"], unique=False
        )
        batch_op.create_unique_constraint(
            "uq_user_chat_history_user_external_ref", ["user_id", "external_ref_hash"]
        )

    op.create_table(
        "telegram_inline_result",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("result_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("telegram_user_id", sa.String(length=32), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=12)),
        sa.Column("selected_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("result_id"),
    )
    op.create_index(
        "ix_telegram_inline_result_result_id", "telegram_inline_result", ["result_id"], unique=True
    )
    op.create_index(
        "ix_telegram_inline_result_user_id", "telegram_inline_result", ["user_id"], unique=False
    )
    op.create_index(
        "ix_telegram_inline_result_telegram_user_id",
        "telegram_inline_result",
        ["telegram_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_telegram_inline_result_created_at",
        "telegram_inline_result",
        ["created_at"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_telegram_inline_result_created_at", table_name="telegram_inline_result")
    op.drop_index("ix_telegram_inline_result_telegram_user_id", table_name="telegram_inline_result")
    op.drop_index("ix_telegram_inline_result_user_id", table_name="telegram_inline_result")
    op.drop_index("ix_telegram_inline_result_result_id", table_name="telegram_inline_result")
    op.drop_table("telegram_inline_result")

    with op.batch_alter_table("user_chat_history", schema=None) as batch_op:
        batch_op.drop_constraint("uq_user_chat_history_user_external_ref", type_="unique")
        batch_op.drop_index("ix_user_chat_history_external_ref_hash")
        batch_op.drop_index("ix_user_chat_history_source")
        batch_op.drop_column("source_context_data")
        batch_op.drop_column("external_ref_hash")
        batch_op.drop_column("source")
