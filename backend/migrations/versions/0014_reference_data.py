"""0014_reference_data: see migrations/sql/0014_reference_data.sql"""
from migrations.sqlfile import forbid_in_production, run_sql, run_sql_file

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0014_reference_data.sql")


def downgrade() -> None:
    forbid_in_production(revision)
    run_sql("DELETE FROM ref.category_compatibility; DELETE FROM ref.incident_categories; DELETE FROM ref.disclosure_policies;")
