"""Bind chat sessions to minds

Revision ID: add_chat_mind_binding
Revises: add_minds_feature
Create Date: 2026-04-29

"""

from alembic import op
import sqlalchemy as sa

revision = "add_chat_mind_binding"
down_revision = "add_minds_feature"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user_chat_history") as batch_op:
        batch_op.add_column(sa.Column("mind_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_user_chat_history_mind_id", ["mind_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_user_chat_history_mind_id_mind",
            "mind",
            ["mind_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    with op.batch_alter_table("user_chat_history") as batch_op:
        batch_op.drop_constraint("fk_user_chat_history_mind_id_mind", type_="foreignkey")
        batch_op.drop_index("ix_user_chat_history_mind_id")
        batch_op.drop_column("mind_id")
