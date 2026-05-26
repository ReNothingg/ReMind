"""Add user name field

Revision ID: add_user_name_field
Revises: add_token_expiry
Create Date: 2026-03-26

"""

from alembic import op
import sqlalchemy as sa

revision = "add_user_name_field"
down_revision = "add_token_expiry"
branch_labels = None
depends_on = None


def upgrade():

    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(sa.Column("name", sa.String(length=100), nullable=True))

    op.execute('UPDATE "user" SET name = username WHERE name IS NULL OR TRIM(name) = \'\'')


def downgrade():

    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("name")
