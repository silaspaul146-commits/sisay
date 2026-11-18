"""0016_operational_assessment: see migrations/sql/0016_operational_assessment.sql"""
from migrations.sqlfile import forbid_in_production, run_sql, run_sql_file

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0016_operational_assessment.sql")


def downgrade() -> None:
    forbid_in_production(revision)
    # NOT VALID: operational rows written meanwhile are append-only history and stay.
    run_sql("""
        ALTER TABLE incident.incident_assessments DROP CONSTRAINT ck_incident_assessments_value;
        ALTER TABLE incident.incident_assessments ADD CONSTRAINT ck_incident_assessments_value CHECK (
             (assessment_type = 'severity'     AND assessment_value IN ('unknown','low','moderate','high','critical'))
          OR (assessment_type = 'confidence'   AND assessment_value IN ('low','medium','high'))
          OR (assessment_type = 'freshness'    AND assessment_value IN ('current','aging','stale','expired'))
          OR (assessment_type = 'verification' AND assessment_value IN
               ('unverified','under_review','verified','disputed','rejected'))) NOT VALID;
    """)
