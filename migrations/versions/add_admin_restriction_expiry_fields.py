"""Add admin restriction reasons and expirations

Revision ID: add_admin_restriction_expiry_fields
Revises: add_admin_panel_controls
Create Date: 2026-05-04

"""

from alembic import op
import sqlalchemy as sa

revision = "add_admin_restriction_expiry_fields"
down_revision = "add_admin_panel_controls"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ban_reason", sa.String(length=280), nullable=True))
        batch_op.add_column(sa.Column("block_reason", sa.String(length=280), nullable=True))
        batch_op.add_column(sa.Column("banned_until", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("blocked_until", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("blocked_until")
        batch_op.drop_column("banned_until")
        batch_op.drop_column("block_reason")
        batch_op.drop_column("ban_reason")
