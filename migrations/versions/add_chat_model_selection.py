import sqlalchemy as sa
from alembic import op

revision = "add_chat_model_selection"
down_revision = "add_chat_context_checkpoint"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("chat_model_selection"):
        op.create_table(
            "chat_model_selection",
            sa.Column(
                "chat_id",
                sa.Integer(),
                sa.ForeignKey("user_chat_history.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("pending", sa.JSON(none_as_null=True)),
            sa.Column("last_used", sa.JSON(none_as_null=True)),
            sa.Column("last_request_order", sa.BigInteger()),
        )


def downgrade():
    if sa.inspect(op.get_bind()).has_table("chat_model_selection"):
        op.drop_table("chat_model_selection")
