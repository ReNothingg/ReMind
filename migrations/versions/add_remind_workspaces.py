import sqlalchemy as sa
from alembic import op

revision = "add_remind_workspaces"
down_revision = "add_mind_external_use"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("remind_workspace"):
        op.create_table(
            "remind_workspace",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_remind_workspace_user_id", "remind_workspace", ["user_id"])
    if "workspace_id" not in {
        c["name"] for c in sa.inspect(op.get_bind()).get_columns("user_chat_history")
    }:
        with op.batch_alter_table("user_chat_history") as batch:
            batch.add_column(sa.Column("workspace_id", sa.String(32)))
            batch.create_foreign_key(
                "fk_user_chat_history_workspace_id",
                "remind_workspace",
                ["workspace_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch.create_index("ix_user_chat_history_workspace_id", ["workspace_id"])


def downgrade():
    with op.batch_alter_table("user_chat_history") as batch:
        batch.drop_index("ix_user_chat_history_workspace_id")
        batch.drop_constraint("fk_user_chat_history_workspace_id", type_="foreignkey")
        batch.drop_column("workspace_id")
    op.drop_table("remind_workspace")
