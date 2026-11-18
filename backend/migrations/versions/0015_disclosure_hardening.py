"""0015_disclosure_hardening: see migrations/sql/0015_disclosure_hardening.sql"""
from migrations.sqlfile import forbid_in_production, run_sql, run_sql_file

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0015_disclosure_hardening.sql")


def downgrade() -> None:
    forbid_in_production(revision)
    run_sql("""
        CREATE OR REPLACE VIEW disclosure.public_incident_removals_v WITH (security_barrier = true) AS
        SELECT id AS public_id, version, generated_at AS removed_at
        FROM   disclosure.public_incident_projections
        WHERE  NOT (is_visible AND publication_state = 'published')
          AND  generated_at > now() - interval '7 days';
        ALTER POLICY hir_org_read ON humanitarian.humanitarian_impact_records
          USING (organization_id = current_setting('app.organization_id', true)::uuid
                 OR sharing_scope = 'platform'
                 OR (sharing_scope = 'partners' AND ops.is_partner(organization_id,
                       current_setting('app.organization_id', true)::uuid)));
        ALTER POLICY hir_org_write ON humanitarian.humanitarian_impact_records
          WITH CHECK (organization_id = current_setting('app.organization_id', true)::uuid);
        DROP FUNCTION ops.current_organization_id();
    """)
