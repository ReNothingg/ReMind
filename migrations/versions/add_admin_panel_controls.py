"""Add admin roles and moderation controls

Revision ID: add_admin_panel_controls
Revises: add_chat_mind_binding
Create Date: 2026-05-03

"""

from alembic import op
import sqlalchemy as sa

revision = "add_admin_panel_controls"
down_revision = "add_chat_mind_binding"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("is_banned", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("moderation_reason", sa.String(length=280), nullable=True))

    with op.batch_alter_table("mind", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("is_banned", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("moderation_reason", sa.String(length=280), nullable=True))
        batch_op.create_index("ix_mind_is_featured", ["is_featured"], unique=False)
        batch_op.create_index("ix_mind_is_banned", ["is_banned"], unique=False)


def downgrade():
    with op.batch_alter_table("mind", schema=None) as batch_op:
        batch_op.drop_index("ix_mind_is_banned")
        batch_op.drop_index("ix_mind_is_featured")
        batch_op.drop_column("moderation_reason")
        batch_op.drop_column("is_banned")
        batch_op.drop_column("is_featured")

    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("moderation_reason")
        batch_op.drop_column("is_blocked")
        batch_op.drop_column("is_banned")
        batch_op.drop_column("is_admin")
