"""Add one-time Telegram bot linking requests.

Revision ID: add_telegram_link_requests
Revises: add_telegram_bot_channel
Create Date: 2026-08-07
"""

import sqlalchemy as sa
from alembic import op


revision = "add_telegram_link_requests"
down_revision = "add_telegram_bot_channel"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "telegram_link_request",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=24), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime()),
        sa.Column("failure_code", sa.String(length=32)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_telegram_link_request_request_id",
        "telegram_link_request",
        ["request_id"],
        unique=True,
    )
    op.create_index(
        "ix_telegram_link_request_token_hash",
        "telegram_link_request",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_telegram_link_request_user_id",
        "telegram_link_request",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_telegram_link_request_expires_at",
        "telegram_link_request",
        ["expires_at"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_telegram_link_request_expires_at", table_name="telegram_link_request")
    op.drop_index("ix_telegram_link_request_user_id", table_name="telegram_link_request")
    op.drop_index("ix_telegram_link_request_token_hash", table_name="telegram_link_request")
    op.drop_index("ix_telegram_link_request_request_id", table_name="telegram_link_request")
    op.drop_table("telegram_link_request")
