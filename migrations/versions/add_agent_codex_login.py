import sqlalchemy as sa
from alembic import op

revision = "add_agent_codex_login"
down_revision = "add_chat_provider_replay"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("agent_codex_login"):
        op.create_table(
            "agent_codex_login",
            sa.Column(
                "slot_id", sa.Integer(), sa.ForeignKey("agent_workspace_slot.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("attempt_id", sa.String(32), nullable=False),
            sa.Column("expires_at", sa.BigInteger(), nullable=False),
            sa.Column("encrypted_code", sa.Text()),
        )
        op.create_index("ix_agent_codex_login_expires_at", "agent_codex_login", ["expires_at"])


def downgrade():
    op.drop_table("agent_codex_login")
