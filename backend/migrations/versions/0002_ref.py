"""0002_ref: see migrations/sql/0002_ref.sql"""
from migrations.sqlfile import forbid_in_production, run_sql, run_sql_file

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0002_ref.sql")


def downgrade() -> None:
    forbid_in_production(revision)
    run_sql("DROP TABLE ref.category_compatibility, ref.incident_categories, ref.disclosure_policies;")
