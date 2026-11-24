import sqlalchemy as sa
from alembic import op

revision = "add_mind_external_use"
down_revision = "add_agent_workspaces"
branch_labels = None
depends_on = None


def upgrade():
    if "allow_external_use" not in {
        c["name"] for c in sa.inspect(op.get_bind()).get_columns("mind")
    }:
        op.add_column(
            "mind",
            sa.Column(
                "allow_external_use", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )


def downgrade():
    with op.batch_alter_table("mind") as batch:
        batch.drop_column("allow_external_use")
