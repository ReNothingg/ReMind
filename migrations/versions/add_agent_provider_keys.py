import sqlalchemy as sa
from alembic import op

revision = "add_agent_provider_keys"
down_revision = "add_chatgpt_connection"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("agent_provider_key"):
        return
    op.create_table(
        "agent_provider_key",
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("provider", sa.String(48), primary_key=True),
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column("catalog", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("agent_provider_key")
