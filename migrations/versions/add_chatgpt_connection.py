import sqlalchemy as sa
from alembic import op

revision = "add_chatgpt_connection"
down_revision = "add_mind_skills"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("chatgpt_connection"):
        return
    op.create_table(
        "chatgpt_connection",
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("host_id", sa.String(64), nullable=False),
        sa.Column("credentials", sa.Text()),
        sa.Column("pending", sa.Text()),
        sa.Column("models", sa.JSON()),
        sa.Column("catalog_time", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_table("chatgpt_connection")
