from alembic import op
import sqlalchemy as sa


revision = "enable_auto_web_search_default"
down_revision = "dedupe_chat_sessions"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.alter_column(
            "automatic_web_search",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.true(),
        )


def downgrade():
    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.alter_column(
            "automatic_web_search",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.false(),
        )
