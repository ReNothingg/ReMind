"""Add minds feature

Revision ID: add_minds_feature
Revises: add_user_name_field
Create Date: 2026-04-28

"""

from alembic import op
import sqlalchemy as sa

revision = "add_minds_feature"
down_revision = "add_user_name_field"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mind",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=280), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("starters_data", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(op.f("ix_mind_category"), "mind", ["category"], unique=False)
    op.create_index(op.f("ix_mind_public_id"), "mind", ["public_id"], unique=False)
    op.create_index(op.f("ix_mind_user_id"), "mind", ["user_id"], unique=False)
    op.create_index(op.f("ix_mind_visibility"), "mind", ["visibility"], unique=False)

    op.create_table(
        "mind_pin",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("mind_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["mind_id"], ["mind.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "mind_id", name="uq_mind_pin_user_mind"),
    )
    op.create_index(op.f("ix_mind_pin_mind_id"), "mind_pin", ["mind_id"], unique=False)
    op.create_index(op.f("ix_mind_pin_user_id"), "mind_pin", ["user_id"], unique=False)
    op.execute(
        "DELETE FROM mind WHERE is_system = 1 AND public_id IN "
        "('mind_study_coach', 'mind_code_reviewer', 'mind_product_strategist', 'mind_security_auditor')"
    )


def downgrade():
    op.drop_index(op.f("ix_mind_pin_user_id"), table_name="mind_pin")
    op.drop_index(op.f("ix_mind_pin_mind_id"), table_name="mind_pin")
    op.drop_table("mind_pin")

    op.drop_index(op.f("ix_mind_visibility"), table_name="mind")
    op.drop_index(op.f("ix_mind_user_id"), table_name="mind")
    op.drop_index(op.f("ix_mind_public_id"), table_name="mind")
    op.drop_index(op.f("ix_mind_category"), table_name="mind")
    op.drop_table("mind")
