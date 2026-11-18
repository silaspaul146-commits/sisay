"""0009_disclosure: see migrations/sql/0009_disclosure.sql"""
from migrations.sqlfile import forbid_in_production, run_sql, run_sql_file

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0009_disclosure.sql")


def downgrade() -> None:
    forbid_in_production(revision)
    run_sql("DROP VIEW disclosure.public_incident_removals_v, disclosure.public_incidents_v; DROP TABLE disclosure.public_incident_projection_history, disclosure.public_incident_projections; DROP FUNCTION disclosure.snap_public_point(geography, integer);")
