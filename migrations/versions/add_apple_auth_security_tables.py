"""Add one-time Apple authentication challenge and replay tables.

Revision ID: add_apple_auth_security
Revises: add_telegram_link_requests
Create Date: 2026-08-10
"""

from alembic import op
import sqlalchemy as sa


revision = "add_apple_auth_security"
down_revision = "add_telegram_link_requests"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "apple_auth_challenge",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("challenge_hash", sa.String(length=64), nullable=False),
        sa.Column("nonce_hash", sa.String(length=64), nullable=False),
        sa.Column("flow", sa.String(length=12), nullable=False),
        sa.Column("mode", sa.String(length=12), nullable=False),
        sa.Column("link_user_id", sa.Integer(), nullable=True),
        sa.Column("redirect_to", sa.String(length=500), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["link_user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("challenge_hash"),
    )
    op.create_index(
        "ix_apple_auth_challenge_challenge_hash",
        "apple_auth_challenge",
        ["challenge_hash"],
        unique=True,
    )
    op.create_index(
        "ix_apple_auth_challenge_expires_at",
        "apple_auth_challenge",
        ["expires_at"],
        unique=False,
    )
    op.create_table(
        "apple_token_replay",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index(
        "ix_apple_token_replay_expires_at",
        "apple_token_replay",
        ["expires_at"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_apple_token_replay_expires_at", table_name="apple_token_replay")
    op.drop_table("apple_token_replay")
    op.drop_index("ix_apple_auth_challenge_expires_at", table_name="apple_auth_challenge")
    op.drop_index(
        "ix_apple_auth_challenge_challenge_hash", table_name="apple_auth_challenge"
    )
    op.drop_table("apple_auth_challenge")
