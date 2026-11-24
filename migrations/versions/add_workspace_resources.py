import sqlalchemy as sa
from alembic import op

revision = "add_workspace_resources"
down_revision = "add_automation_proposals"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "instructions" not in {
        column["name"] for column in inspector.get_columns("remind_workspace")
    }:
        op.add_column(
            "remind_workspace",
            sa.Column("instructions", sa.Text(), server_default="", nullable=False),
        )
    if not inspector.has_table("remind_workspace_file"):
        op.create_table(
            "remind_workspace_file",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column(
                "workspace_id",
                sa.String(32),
                sa.ForeignKey("remind_workspace.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("storage_name", sa.String(48), unique=True, nullable=False),
            sa.Column("original_name", sa.String(255), nullable=False),
            sa.Column("name_key", sa.String(64), nullable=False),
            sa.Column("mime_type", sa.String(120), nullable=False),
            sa.Column("size", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("workspace_id", "name_key", name="uq_workspace_file_name"),
        )
        op.create_index(
            "ix_remind_workspace_file_workspace_id", "remind_workspace_file", ["workspace_id"]
        )


def downgrade():
    op.drop_table("remind_workspace_file")
    with op.batch_alter_table("remind_workspace") as batch:
        batch.drop_column("instructions")
