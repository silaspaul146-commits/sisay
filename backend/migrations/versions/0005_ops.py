"""0005_ops: see migrations/sql/0005_ops.sql"""
from migrations.sqlfile import forbid_in_production, run_sql, run_sql_file

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0005_ops.sql")


def downgrade() -> None:
    forbid_in_production(revision)
    run_sql("DROP TABLE ops.audit_logs, ops.outbox_events; DROP FUNCTION ops.notify_outbox();")
