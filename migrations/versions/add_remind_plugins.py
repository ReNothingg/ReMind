import sqlalchemy as sa
from alembic import op

revision = "add_remind_plugins"
down_revision = "add_remind_automations"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("agent_plugin"):
        op.create_table(
            "agent_plugin",
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("user.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("plugin_id", sa.String(72), primary_key=True),
            sa.Column("manifest", sa.JSON()),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )


def downgrade():
    op.drop_table("agent_plugin")
