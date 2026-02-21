"""Initial migration

Revision ID: 57c7ee8ff8ec
Revises:
Create Date: 2025-12-16 23:45:52.805499

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
revision: str = '57c7ee8ff8ec'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.drop_table('admin_log')
    op.drop_table('admin')
    op.drop_table('system_stats')
    with op.batch_alter_table('user_chat_history', schema=None) as batch_op:
        batch_op.alter_column('messages_data',
               existing_type=sa.TEXT(),
               type_=sa.JSON(),
               existing_nullable=True)

    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.alter_column('user_id',
               existing_type=sa.INTEGER(),
               nullable=True)
        batch_op.create_index(batch_op.f('ix_user_settings_user_id'), ['user_id'], unique=False)


def downgrade() -> None:

    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_settings_user_id'))
        batch_op.alter_column('user_id',
               existing_type=sa.INTEGER(),
               nullable=False)

    with op.batch_alter_table('user_chat_history', schema=None) as batch_op:
        batch_op.alter_column('messages_data',
               existing_type=sa.JSON(),
               type_=sa.TEXT(),
               existing_nullable=True)

    op.create_table('system_stats',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('total_users', sa.INTEGER(), nullable=True),
    sa.Column('total_chats', sa.INTEGER(), nullable=True),
    sa.Column('total_images_generated', sa.INTEGER(), nullable=True),
    sa.Column('total_storage_used', sa.BIGINT(), nullable=True),
    sa.Column('last_updated', sa.DATETIME(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('admin',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('user_id', sa.INTEGER(), nullable=False),
    sa.Column('is_super_admin', sa.BOOLEAN(), nullable=True),
    sa.Column('permissions', sa.TEXT(), nullable=True),
    sa.Column('created_at', sa.DATETIME(), nullable=True),
    sa.Column('updated_at', sa.DATETIME(), nullable=True),
    sa.Column('notes', sa.TEXT(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    op.create_table('admin_log',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('admin_id', sa.INTEGER(), nullable=False),
    sa.Column('action', sa.VARCHAR(length=100), nullable=False),
    sa.Column('target', sa.VARCHAR(length=255), nullable=True),
    sa.Column('details', sa.TEXT(), nullable=True),
    sa.Column('ip_address', sa.VARCHAR(length=50), nullable=True),
    sa.Column('timestamp', sa.DATETIME(), nullable=True),
    sa.ForeignKeyConstraint(['admin_id'], ['admin.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
