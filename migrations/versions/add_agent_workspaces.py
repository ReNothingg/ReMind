import sqlalchemy as sa
from alembic import op

revision = "add_agent_workspaces"
down_revision = "add_telegram_agent"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("agent_workspace_slot"):
        op.create_table(
            "agent_workspace_slot",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
            sa.Column(
                "user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), unique=True
            ),
            sa.Column("workspace_id", sa.String(32), unique=True),
            sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("mind_public_id", sa.String(128)),
            sa.Column("codex_catalog", sa.JSON()),
            sa.Column("codex_catalog_time", sa.Integer(), nullable=False, server_default="0"),
        )
    if not inspector.has_table("agent_workspace_ticket"):
        op.create_table(
            "agent_workspace_ticket",
            sa.Column("digest", sa.String(64), primary_key=True),
            sa.Column(
                "slot_id",
                sa.Integer(),
                sa.ForeignKey("agent_workspace_slot.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("expires", sa.BigInteger(), nullable=False, index=True),
        )


def downgrade():
    op.drop_table("agent_workspace_ticket")
    op.drop_table("agent_workspace_slot")
