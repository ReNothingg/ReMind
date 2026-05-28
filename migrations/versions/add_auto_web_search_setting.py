"""Add automatic web search setting

Revision ID: add_auto_web_search_setting
Revises: add_admin_restriction_expiry_fields
Create Date: 2026-05-27

"""

from alembic import op
import sqlalchemy as sa


revision = "add_auto_web_search_setting"
down_revision = "add_admin_restriction_expiry_fields"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "automatic_web_search",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade():
    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.drop_column("automatic_web_search")
