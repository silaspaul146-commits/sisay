"""0012_humanitarian: see migrations/sql/0012_humanitarian.sql"""
from migrations.sqlfile import forbid_in_production, run_sql, run_sql_file

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0012_humanitarian.sql")


def downgrade() -> None:
    forbid_in_production(revision)
    run_sql("DROP TABLE humanitarian.humanitarian_impact_records; DROP FUNCTION ops.is_partner(uuid, uuid);")
