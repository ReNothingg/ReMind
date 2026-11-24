import sqlalchemy as sa
from alembic import op

revision = "add_mind_skills"
down_revision = "add_password_reset_challenges"
branch_labels = None
depends_on = None


def upgrade():
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("mind")}
    for name in ("skill_ids", "custom_skills"):
        if name not in columns:
            op.add_column("mind", sa.Column(name, sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("mind") as batch:
        batch.drop_column("custom_skills")
        batch.drop_column("skill_ids")
