import sqlalchemy as sa
from alembic import op

revision = "add_telegram_agent"
down_revision = "add_agent_provider_keys"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("telegram_agent_settings"):
        op.create_table(
            "telegram_agent_settings",
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("user.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("model", sa.String(200), nullable=False, server_default="base"),
            sa.Column("mind_id", sa.String(128)),
            sa.Column("service_tier", sa.String(16), nullable=False, server_default="standard"),
            sa.Column("web_search", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("secretary_mode", sa.String(16), nullable=False, server_default="off"),
        )
    if not inspector.has_table("telegram_business_link"):
        op.create_table(
            "telegram_business_link",
            sa.Column("connection_id", sa.String(200), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("user.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("telegram_user_id", sa.String(32), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("can_reply", sa.Boolean(), nullable=False),
            sa.Column("last_update", sa.BigInteger(), nullable=False),
        )
    if not inspector.has_table("telegram_business_delivery"):
        op.create_table(
            "telegram_business_delivery",
            sa.Column(
                "connection_id",
                sa.String(200),
                sa.ForeignKey("telegram_business_link.connection_id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("chat_id", sa.BigInteger(), primary_key=True),
            sa.Column("message_id", sa.BigInteger(), primary_key=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        )


def downgrade():
    for table in (
        "telegram_business_delivery",
        "telegram_business_link",
        "telegram_agent_settings",
    ):
        op.drop_table(table)
