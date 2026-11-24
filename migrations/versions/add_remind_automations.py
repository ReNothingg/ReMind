import sqlalchemy as sa
from alembic import op

revision = "add_remind_automations"
down_revision = "add_remind_workspaces"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("automation_task"):
        op.create_table(
            "automation_task",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("title", sa.String(120), nullable=False),
            sa.Column("prompt", sa.Text(), nullable=False),
            sa.Column("model", sa.String(200), nullable=False),
            sa.Column("web_search", sa.Boolean(), nullable=False),
            sa.Column(
                "workspace_id",
                sa.String(32),
                sa.ForeignKey("remind_workspace.id", ondelete="SET NULL"),
            ),
            sa.Column("target_session_id", sa.String(100)),
            sa.Column("timing", sa.JSON(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("next_run_at", sa.DateTime()),
            sa.Column("last_requested_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_automation_task_user_id", "automation_task", ["user_id"])
        op.create_index("ix_automation_task_due", "automation_task", ["enabled", "next_run_at"])
    if not inspector.has_table("automation_run"):
        op.create_table(
            "automation_run",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column(
                "task_id",
                sa.String(32),
                sa.ForeignKey("automation_task.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("session_id", sa.String(100)),
            sa.Column("occurrence_at", sa.DateTime(), nullable=False),
            sa.Column("queued_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime()),
            sa.Column("finished_at", sa.DateTime()),
            sa.Column("error", sa.String(64)),
        )
        op.create_index("ix_automation_run_queue", "automation_run", ["status", "queued_at"])
        op.create_index("ix_automation_run_task_time", "automation_run", ["task_id", "queued_at"])


def downgrade():
    op.drop_table("automation_run")
    op.drop_table("automation_task")
