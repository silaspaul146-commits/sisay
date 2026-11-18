"""0011_alerting: see migrations/sql/0011_alerting.sql"""
from migrations.sqlfile import forbid_in_production, run_sql, run_sql_file

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0011_alerting.sql")


def downgrade() -> None:
    forbid_in_production(revision)
    run_sql("DROP TABLE alerting.alert_deliveries, alerting.alert_distribution_decisions, alerting.alert_versions, alerting.alerts;")
