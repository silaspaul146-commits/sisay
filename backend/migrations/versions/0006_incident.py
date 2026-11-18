"""0006_incident: see migrations/sql/0006_incident.sql"""
from migrations.sqlfile import forbid_in_production, run_sql, run_sql_file

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0006_incident.sql")


def downgrade() -> None:
    forbid_in_production(revision)
    run_sql("DROP TABLE incident.incident_relationships, incident.incident_corrections, incident.incident_assessments, incident.incidents;")
