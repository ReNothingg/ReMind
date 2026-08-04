"""Add linked authentication identities.

Revision ID: add_linked_auth_identities
Revises: enable_auto_web_search_default
Create Date: 2026-08-04
"""

from alembic import op
import sqlalchemy as sa


revision = "add_linked_auth_identities"
down_revision = "enable_auto_web_search_default"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_identity",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_user_id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "provider_user_id", name="uq_auth_identity_provider_subject"
        ),
        sa.UniqueConstraint("user_id", "provider", name="uq_auth_identity_user_provider"),
    )
    op.create_index("ix_auth_identity_user_id", "auth_identity", ["user_id"], unique=False)
    op.execute(
        sa.text(
            "INSERT INTO auth_identity (user_id, provider, provider_user_id, created_at) "
            "SELECT MIN(id), oauth_provider, oauth_id, CURRENT_TIMESTAMP FROM \"user\" "
            "WHERE oauth_provider IN ('google', 'telegram') "
            "AND oauth_id IS NOT NULL AND TRIM(oauth_id) <> '' "
            "GROUP BY oauth_provider, oauth_id"
        )
    )


def downgrade():
    op.drop_index("ix_auth_identity_user_id", table_name="auth_identity")
    op.drop_table("auth_identity")
