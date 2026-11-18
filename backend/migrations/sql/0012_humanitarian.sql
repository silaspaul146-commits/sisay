-- 0012_humanitarian: impact records and organization-scoped RLS (DB spec 4.10, 9.3)
CREATE TABLE humanitarian.humanitarian_impact_records (
  id               uuid          NOT NULL DEFAULT gen_random_uuid(),
  incident_id      uuid          NOT NULL,
  organization_id  uuid          NOT NULL,
  impact_type      text          NOT NULL,
  value            numeric(14,2) NOT NULL,
  value_low        numeric(14,2),
  value_high       numeric(14,2),
  unit             text          NOT NULL,
  evidence_status  text          NOT NULL,
  source           text          NOT NULL,
  source_reference text,
  as_of            timestamptz   NOT NULL,
  sharing_scope    text          NOT NULL DEFAULT 'organization',
  supersedes_id    uuid,
  recorded_at      timestamptz   NOT NULL DEFAULT now(),
  recorded_by      uuid          NOT NULL,
  CONSTRAINT pk_humanitarian_impact_records PRIMARY KEY (id),
  CONSTRAINT fk_hir_incident_id FOREIGN KEY (incident_id) REFERENCES incident.incidents (id),
  CONSTRAINT fk_hir_organization_id FOREIGN KEY (organization_id) REFERENCES org.organizations (id),
  CONSTRAINT fk_hir_recorded_by FOREIGN KEY (recorded_by) REFERENCES identity.users (id),
  CONSTRAINT fk_hir_supersedes_id FOREIGN KEY (supersedes_id)
    REFERENCES humanitarian.humanitarian_impact_records (id),
  CONSTRAINT ck_hir_impact_type CHECK (impact_type IN ('deaths','injuries','missing_persons',
    'abductions','displaced_persons','people_affected','homes_damaged','facilities_damaged')),
  CONSTRAINT ck_hir_unit CHECK (unit IN ('persons','households','structures','facilities')),
  CONSTRAINT ck_hir_evidence_status CHECK (evidence_status IN
    ('reported','estimated','independently_confirmed')),
  CONSTRAINT ck_hir_sharing_scope CHECK (sharing_scope IN ('organization','partners','platform')),
  CONSTRAINT ck_hir_value CHECK (value >= 0),
  CONSTRAINT ck_hir_range CHECK ((value_low IS NULL OR value_low <= value)
                             AND (value_high IS NULL OR value_high >= value)),
  CONSTRAINT ck_hir_range_only_for_estimates
    CHECK (evidence_status = 'estimated' OR (value_low IS NULL AND value_high IS NULL))
);
CREATE UNIQUE INDEX uq_hir_supersedes ON humanitarian.humanitarian_impact_records (supersedes_id)
  WHERE supersedes_id IS NOT NULL;
CREATE INDEX ix_hir_incident_type ON humanitarian.humanitarian_impact_records (incident_id, impact_type, as_of DESC);
CREATE INDEX ix_hir_organization_id ON humanitarian.humanitarian_impact_records (organization_id);

-- Stub until U-3 (cross-organization sharing) is decided: partners behaves as organization.
CREATE FUNCTION ops.is_partner(a uuid, b uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$ SELECT false $$;

ALTER TABLE humanitarian.humanitarian_impact_records ENABLE ROW LEVEL SECURITY;
CREATE POLICY hir_org_read ON humanitarian.humanitarian_impact_records FOR SELECT
  USING (organization_id = current_setting('app.organization_id', true)::uuid
         OR sharing_scope = 'platform'
         OR (sharing_scope = 'partners' AND ops.is_partner(organization_id,
               current_setting('app.organization_id', true)::uuid)));
CREATE POLICY hir_org_write ON humanitarian.humanitarian_impact_records FOR INSERT
  WITH CHECK (organization_id = current_setting('app.organization_id', true)::uuid);
