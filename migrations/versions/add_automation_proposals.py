import sqlalchemy as sa
from alembic import op

revision = "add_automation_proposals"
down_revision = "add_remind_plugins"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("automation_proposal"):
        op.create_table(
            "automation_proposal",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("request_id", sa.String(100), nullable=False),
            sa.Column("session_id", sa.String(100), nullable=False),
            sa.Column("operation", sa.String(12), nullable=False),
            sa.Column("task_id", sa.String(32)),
            sa.Column("task_state", sa.String(64)),
            sa.Column("changes", sa.JSON(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("applied_at", sa.DateTime()),
            sa.Column("result", sa.JSON()),
            sa.UniqueConstraint("user_id", "request_id", name="uq_automation_proposal_request"),
        )
        op.create_index("ix_automation_proposal_user_id", "automation_proposal", ["user_id"])
        op.create_index("ix_automation_proposal_expires_at", "automation_proposal", ["expires_at"])


def downgrade():
    op.drop_table("automation_proposal")
