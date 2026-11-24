import sqlalchemy as sa
from alembic import op

revision = "add_chat_provider_replay"
down_revision = "add_workspace_patch_proposals"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("chat_provider_replay"):
        op.create_table(
            "chat_provider_replay",
            sa.Column(
                "chat_id",
                sa.Integer(),
                sa.ForeignKey("user_chat_history.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("message_id", sa.String(length=120), primary_key=True),
            sa.Column("route_key", sa.String(length=64), nullable=False),
            sa.Column("history_digest", sa.String(length=64), nullable=False),
            sa.Column("payload", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )


def downgrade():
    op.drop_table("chat_provider_replay")
