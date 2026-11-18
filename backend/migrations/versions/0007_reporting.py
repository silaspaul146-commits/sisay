"""0007_reporting: see migrations/sql/0007_reporting.sql"""
from migrations.sqlfile import forbid_in_production, run_sql, run_sql_file

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0007_reporting.sql")


def downgrade() -> None:
    forbid_in_production(revision)
    run_sql("DROP TABLE reporting.report_association_history, reporting.report_match_candidates, reporting.report_match_decisions, reporting.report_evidence, reporting.report_access_credentials, reporting.report_submitters, reporting.reports;")
