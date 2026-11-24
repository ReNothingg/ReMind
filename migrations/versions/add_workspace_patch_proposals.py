import sqlalchemy as sa
from alembic import op

revision = "add_workspace_patch_proposals"
down_revision = "add_agent_skill_library"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("workspace_patch_proposal"):
        return
    op.create_table(
        "workspace_patch_proposal",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("remind_workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chat_id",
            sa.Integer(),
            sa.ForeignKey("user_chat_history.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(100), nullable=False),
        sa.Column("patch", sa.Text(), nullable=False),
        sa.Column("base_revision", sa.String(64), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("applied_at", sa.DateTime()),
        sa.UniqueConstraint("chat_id", "request_id", name="uq_workspace_patch_request"),
    )
    op.create_index("ix_workspace_patch_proposal_chat_id", "workspace_patch_proposal", ["chat_id"])
    op.create_index(
        "ix_workspace_patch_owner_expires", "workspace_patch_proposal", ["user_id", "expires_at"]
    )


def downgrade():
    if sa.inspect(op.get_bind()).has_table("workspace_patch_proposal"):
        op.drop_table("workspace_patch_proposal")
