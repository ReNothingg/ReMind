"""Add token expiry fields for security

Revision ID: add_token_expiry
Revises: 57c7ee8ff8ec
Create Date: 2026-01-25

"""
from alembic import op
import sqlalchemy as sa
revision = 'add_token_expiry'
down_revision = '57c7ee8ff8ec'
branch_labels = None
depends_on = None


def upgrade():

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('confirmation_token_expires', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('reset_token_expires', sa.DateTime(), nullable=True))


def downgrade():

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('reset_token_expires')
        batch_op.drop_column('confirmation_token_expires')
