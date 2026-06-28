"""Add AI response feedback table

Revision ID: add_ai_response_feedback
Revises: add_github_agent_feature
Create Date: 2026-06-27

"""

from alembic import op
import sqlalchemy as sa

revision = "add_ai_response_feedback"
down_revision = "add_github_agent_feature"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_response_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=100), nullable=False),
        sa.Column("message_client_id", sa.String(length=120), nullable=True),
        sa.Column("response_hash", sa.String(length=64), nullable=False),
        sa.Column("rating", sa.String(length=12), nullable=False),
        sa.Column("reason_codes_data", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("prompt_text", sa.Text(), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("service_improvement_opt_in", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "session_id", "response_hash", name="uq_ai_feedback_user_session_response"),
    )
    op.create_index("ix_ai_response_feedback_user_id", "ai_response_feedback", ["user_id"], unique=False)
    op.create_index("ix_ai_response_feedback_session_id", "ai_response_feedback", ["session_id"], unique=False)
    op.create_index("ix_ai_response_feedback_response_hash", "ai_response_feedback", ["response_hash"], unique=False)
    op.create_index("ix_ai_response_feedback_rating", "ai_response_feedback", ["rating"], unique=False)
    op.create_index(
        "ix_ai_response_feedback_service_improvement_opt_in",
        "ai_response_feedback",
        ["service_improvement_opt_in"],
        unique=False,
    )
    op.create_index("ix_ai_response_feedback_created_at", "ai_response_feedback", ["created_at"], unique=False)


def downgrade():
    op.drop_index("ix_ai_response_feedback_created_at", table_name="ai_response_feedback")
    op.drop_index("ix_ai_response_feedback_service_improvement_opt_in", table_name="ai_response_feedback")
    op.drop_index("ix_ai_response_feedback_rating", table_name="ai_response_feedback")
    op.drop_index("ix_ai_response_feedback_response_hash", table_name="ai_response_feedback")
    op.drop_index("ix_ai_response_feedback_session_id", table_name="ai_response_feedback")
    op.drop_index("ix_ai_response_feedback_user_id", table_name="ai_response_feedback")
    op.drop_table("ai_response_feedback")
