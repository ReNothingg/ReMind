import sqlalchemy as sa
from alembic import op

revision = "add_chat_context_checkpoint"
down_revision = "add_workspace_resources"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("chat_context_checkpoint"):
        op.create_table(
            "chat_context_checkpoint",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "chat_id",
                sa.Integer(),
                sa.ForeignKey("user_chat_history.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("covered_count", sa.Integer(), nullable=False),
            sa.Column("prefix_digest", sa.String(64), nullable=False),
            sa.Column("excerpts", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("chat_id", "prefix_digest", name="uq_chat_context_prefix"),
        )
        op.create_index(
            "ix_chat_context_checkpoint_chat_id", "chat_context_checkpoint", ["chat_id"]
        )


def downgrade():
    op.drop_table("chat_context_checkpoint")
