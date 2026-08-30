"""Add hashed one-time password reset codes.

Revision ID: add_password_reset_challenges
Revises: add_apple_auth_security
Create Date: 2026-08-28
"""

import sqlalchemy as sa
from alembic import op


revision = "add_password_reset_challenges"
down_revision = "add_apple_auth_security"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("auth_version", sa.Integer(), server_default="0", nullable=False)
        )
    op.create_table(
        "password_reset_challenge",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=24), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_password_reset_challenge_request_id",
        "password_reset_challenge",
        ["request_id"],
        unique=True,
    )
    op.create_index(
        "ix_password_reset_challenge_user_id",
        "password_reset_challenge",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_password_reset_challenge_expires_at",
        "password_reset_challenge",
        ["expires_at"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_password_reset_challenge_expires_at",
        table_name="password_reset_challenge",
    )
    op.drop_index(
        "ix_password_reset_challenge_user_id",
        table_name="password_reset_challenge",
    )
    op.drop_index(
        "ix_password_reset_challenge_request_id",
        table_name="password_reset_challenge",
    )
    op.drop_table("password_reset_challenge")
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("auth_version")
