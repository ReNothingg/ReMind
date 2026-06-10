"""Add GitHub agent feature

Revision ID: add_github_agent_feature
Revises: add_auto_web_search_setting
Create Date: 2026-06-05

"""

from alembic import op
import sqlalchemy as sa

revision = "add_github_agent_feature"
down_revision = "add_auto_web_search_setting"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "github_installation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("account_login", sa.String(length=120), nullable=False),
        sa.Column("account_html_url", sa.String(length=500), nullable=True),
        sa.Column("account_avatar_url", sa.String(length=500), nullable=True),
        sa.Column("target_type", sa.String(length=40), nullable=True),
        sa.Column("repository_selection", sa.String(length=40), nullable=True),
        sa.Column("permissions_data", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "installation_id",
            name="uq_github_installation_user_installation",
        ),
    )
    op.create_index(
        op.f("ix_github_installation_installation_id"),
        "github_installation",
        ["installation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_github_installation_user_id"),
        "github_installation",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "github_agent_task",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("repo_full_name", sa.String(length=260), nullable=False),
        sa.Column("base_branch", sa.String(length=260), nullable=False),
        sa.Column("branch_name", sa.String(length=260), nullable=True),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("plan_data", sa.Text(), nullable=False),
        sa.Column("edits_data", sa.Text(), nullable=False),
        sa.Column("diff", sa.Text(), nullable=True),
        sa.Column("pull_request_number", sa.Integer(), nullable=True),
        sa.Column("pull_request_url", sa.String(length=500), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_github_agent_task_installation_id"),
        "github_agent_task",
        ["installation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_github_agent_task_public_id"),
        "github_agent_task",
        ["public_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_github_agent_task_repo_full_name"),
        "github_agent_task",
        ["repo_full_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_github_agent_task_status"),
        "github_agent_task",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_github_agent_task_user_id"),
        "github_agent_task",
        ["user_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_github_agent_task_user_id"), table_name="github_agent_task")
    op.drop_index(op.f("ix_github_agent_task_status"), table_name="github_agent_task")
    op.drop_index(op.f("ix_github_agent_task_repo_full_name"), table_name="github_agent_task")
    op.drop_index(op.f("ix_github_agent_task_public_id"), table_name="github_agent_task")
    op.drop_index(op.f("ix_github_agent_task_installation_id"), table_name="github_agent_task")
    op.drop_table("github_agent_task")

    op.drop_index(op.f("ix_github_installation_user_id"), table_name="github_installation")
    op.drop_index(
        op.f("ix_github_installation_installation_id"),
        table_name="github_installation",
    )
    op.drop_table("github_installation")
