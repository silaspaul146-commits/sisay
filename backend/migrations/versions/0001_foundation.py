"""0001_foundation: see migrations/sql/0001_foundation.sql"""
from migrations.sqlfile import forbid_in_production, run_sql, run_sql_file

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0001_foundation.sql")


def downgrade() -> None:
    forbid_in_production(revision)
    run_sql("DROP SCHEMA IF EXISTS humanitarian, alerting, subscription, disclosure, review, reporting, incident, ops, org, identity, ref CASCADE;")
