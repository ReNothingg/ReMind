import sqlalchemy as sa
from alembic import op

revision = "add_agent_skill_library"
down_revision = "add_chat_model_selection"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("agent_skill"):
        return
    op.create_table(
        "agent_skill",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column(
            "workspace_id", sa.String(32), sa.ForeignKey("remind_workspace.id", ondelete="CASCADE")
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("resources", sa.JSON(), nullable=False),
        sa.Column("properties", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "scope", "name", name="uq_agent_skill_scope_name"),
    )
    op.create_index("ix_agent_skill_workspace_id", "agent_skill", ["workspace_id"])


def downgrade():
    if sa.inspect(op.get_bind()).has_table("agent_skill"):
        op.drop_table("agent_skill")
