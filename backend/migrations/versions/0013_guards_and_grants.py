"""0013_guards_and_grants: see migrations/sql/0013_guards_and_grants.sql"""
from migrations.sqlfile import forbid_in_production, run_sql, run_sql_file

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0013_guards_and_grants.sql")
    run_sql_file("grants.sql")


def downgrade() -> None:
    forbid_in_production(revision)
    run_sql("DROP TRIGGER trg_reports_association_history_ins ON reporting.reports; DROP TRIGGER trg_reports_association_history_upd ON reporting.reports; DROP TRIGGER trg_reports_protect_original ON reporting.reports; DROP FUNCTION reporting.get_report_submitter(uuid, uuid, uuid, text); DROP FUNCTION reporting.redact_report(uuid, text); DROP FUNCTION reporting.check_association_history(); DROP FUNCTION reporting.protect_report_original();")
