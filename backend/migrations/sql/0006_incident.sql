-- 0006_incident: incidents and their append-only history (DB spec 4.4)
-- Vocabulary per docs/DECISIONS.md: verification uses 'rejected', freshness uses current/aging/stale/expired.
CREATE TABLE incident.incidents (
  id                      uuid        NOT NULL DEFAULT gen_random_uuid(),
  category_id             smallint    NOT NULL,
  title                   text        NOT NULL,
  description             text,
  canonical_location      geography(Point, 4326) NOT NULL,
  location_uncertainty_m  integer     NOT NULL DEFAULT 0,
  affected_area           geography(MultiPolygon, 4326),
  is_provisional          boolean     NOT NULL DEFAULT true,
  origin                  text        NOT NULL DEFAULT 'auto_from_report',
  verification_status     text        NOT NULL DEFAULT 'unverified',
  operational_status      text        NOT NULL DEFAULT 'active',
  severity                text        NOT NULL DEFAULT 'unknown',
  confidence_level        text        NOT NULL DEFAULT 'low',
  freshness_status        text        NOT NULL DEFAULT 'current',
  first_observed_at       timestamptz NOT NULL,
  last_observed_at        timestamptz NOT NULL,
  report_count            integer     NOT NULL DEFAULT 0,
  merged_into_incident_id uuid,
  lock_version            integer     NOT NULL DEFAULT 1,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_incidents PRIMARY KEY (id),
  CONSTRAINT fk_incidents_category_id FOREIGN KEY (category_id) REFERENCES ref.incident_categories (id),
  CONSTRAINT ck_incidents_origin CHECK (origin IN ('auto_from_report','manual')),
  CONSTRAINT ck_incidents_verification CHECK (verification_status IN
    ('unverified','under_review','verified','disputed','rejected')),
  CONSTRAINT ck_incidents_operational CHECK (operational_status IN
    ('active','monitoring','resolved','closed','merged','withdrawn')),
  CONSTRAINT ck_incidents_severity CHECK (severity IN ('unknown','low','moderate','high','critical')),
  CONSTRAINT ck_incidents_confidence CHECK (confidence_level IN ('low','medium','high')),
  CONSTRAINT ck_incidents_freshness CHECK (freshness_status IN ('current','aging','stale','expired')),
  CONSTRAINT ck_incidents_observed_order CHECK (first_observed_at <= last_observed_at),
  CONSTRAINT ck_incidents_report_count CHECK (report_count >= 0),
  CONSTRAINT ck_incidents_uncertainty CHECK (location_uncertainty_m BETWEEN 0 AND 100000),
  CONSTRAINT ck_incidents_title_len CHECK (char_length(title) BETWEEN 1 AND 200),
  CONSTRAINT fk_incidents_merged_into
    FOREIGN KEY (merged_into_incident_id) REFERENCES incident.incidents (id),
  CONSTRAINT ck_incidents_not_self_merged
    CHECK (merged_into_incident_id IS NULL OR merged_into_incident_id <> id),
  CONSTRAINT ck_incidents_merged_status
    CHECK ((operational_status = 'merged') = (merged_into_incident_id IS NOT NULL)),
  CONSTRAINT ck_incidents_area_valid
    CHECK (affected_area IS NULL OR ST_IsValid(affected_area::geometry))
);
CREATE INDEX gx_incidents_canonical_location ON incident.incidents USING gist (canonical_location);
CREATE INDEX gx_incidents_open_location ON incident.incidents USING gist (canonical_location)
  WHERE operational_status IN ('active','monitoring');
CREATE INDEX gx_incidents_affected_area ON incident.incidents USING gist (affected_area)
  WHERE affected_area IS NOT NULL;
CREATE INDEX ix_incidents_merged_into ON incident.incidents (merged_into_incident_id)
  WHERE merged_into_incident_id IS NOT NULL;
CREATE INDEX ix_incidents_category_last_observed ON incident.incidents (category_id, last_observed_at DESC);
CREATE INDEX ix_incidents_review_queue ON incident.incidents (verification_status, created_at)
  WHERE verification_status IN ('unverified','under_review');
CREATE TRIGGER trg_incidents_touch BEFORE UPDATE ON incident.incidents
  FOR EACH ROW EXECUTE FUNCTION ops.touch_updated_at();

CREATE TABLE incident.incident_assessments (
  id               uuid        NOT NULL DEFAULT gen_random_uuid(),
  incident_id      uuid        NOT NULL,
  assessment_type  text        NOT NULL,
  assessment_value text        NOT NULL,
  rationale        text,
  assessor_id      uuid,
  actor_type       text        NOT NULL,
  organization_id  uuid,
  source           text        NOT NULL,
  is_authoritative boolean     NOT NULL DEFAULT false,
  assessed_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_incident_assessments PRIMARY KEY (id),
  CONSTRAINT fk_incident_assessments_incident_id FOREIGN KEY (incident_id) REFERENCES incident.incidents (id),
  CONSTRAINT fk_incident_assessments_assessor_id FOREIGN KEY (assessor_id) REFERENCES identity.users (id),
  CONSTRAINT fk_incident_assessments_organization_id
    FOREIGN KEY (organization_id) REFERENCES org.organizations (id),
  CONSTRAINT ck_incident_assessments_actor_type CHECK (actor_type IN ('user','system','worker')),
  CONSTRAINT ck_incident_assessments_actor CHECK ((actor_type = 'user') = (assessor_id IS NOT NULL)),
  CONSTRAINT ck_incident_assessments_org_has_org
    CHECK (source <> 'organization' OR organization_id IS NOT NULL),
  CONSTRAINT ck_incident_assessments_source CHECK (source IN
    ('reviewer','matching_engine','freshness_job','organization')),
  CONSTRAINT ck_incident_assessments_value CHECK (
       (assessment_type = 'severity'     AND assessment_value IN ('unknown','low','moderate','high','critical'))
    OR (assessment_type = 'confidence'   AND assessment_value IN ('low','medium','high'))
    OR (assessment_type = 'freshness'    AND assessment_value IN ('current','aging','stale','expired'))
    OR (assessment_type = 'verification' AND assessment_value IN
         ('unverified','under_review','verified','disputed','rejected')))
);
CREATE INDEX ix_incident_assessments_incident_type_time
  ON incident.incident_assessments (incident_id, assessment_type, assessed_at DESC);

CREATE TABLE incident.incident_corrections (
  id              uuid        NOT NULL DEFAULT gen_random_uuid(),
  incident_id     uuid        NOT NULL,
  field_name      text        NOT NULL,
  previous_value  jsonb,
  corrected_value jsonb,
  reason          text        NOT NULL,
  actor_id        uuid        NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_incident_corrections PRIMARY KEY (id),
  CONSTRAINT fk_incident_corrections_incident_id FOREIGN KEY (incident_id) REFERENCES incident.incidents (id),
  CONSTRAINT fk_incident_corrections_actor_id FOREIGN KEY (actor_id) REFERENCES identity.users (id),
  CONSTRAINT ck_incident_corrections_field CHECK (field_name IN
    ('category_id','title','description','canonical_location','location_uncertainty_m',
     'affected_area','first_observed_at','last_observed_at')),
  CONSTRAINT ck_incident_corrections_reason_len CHECK (char_length(reason) BETWEEN 3 AND 2000)
);
CREATE INDEX ix_incident_corrections_incident_id ON incident.incident_corrections (incident_id, created_at);

CREATE TABLE incident.incident_relationships (
  id                 uuid        NOT NULL DEFAULT gen_random_uuid(),
  source_incident_id uuid        NOT NULL,
  target_incident_id uuid        NOT NULL,
  relationship_type  text        NOT NULL,
  reason             text        NOT NULL,
  actor_id           uuid,
  actor_type         text        NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_incident_relationships PRIMARY KEY (id),
  CONSTRAINT fk_incident_relationships_source FOREIGN KEY (source_incident_id) REFERENCES incident.incidents (id),
  CONSTRAINT fk_incident_relationships_target FOREIGN KEY (target_incident_id) REFERENCES incident.incidents (id),
  CONSTRAINT fk_incident_relationships_actor_id FOREIGN KEY (actor_id) REFERENCES identity.users (id),
  CONSTRAINT uq_incident_relationships UNIQUE (source_incident_id, target_incident_id, relationship_type),
  CONSTRAINT ck_incident_relationships_distinct CHECK (source_incident_id <> target_incident_id),
  CONSTRAINT ck_incident_relationships_type CHECK (relationship_type IN
    ('duplicate_of','merged_into','related_to','superseded_by')),
  CONSTRAINT ck_incident_relationships_actor_type CHECK (actor_type IN ('user','system','worker')),
  CONSTRAINT ck_incident_relationships_actor CHECK ((actor_type = 'user') = (actor_id IS NOT NULL))
);
CREATE UNIQUE INDEX uq_incident_relationships_single_successor
  ON incident.incident_relationships (source_incident_id)
  WHERE relationship_type IN ('merged_into','superseded_by');
CREATE INDEX ix_incident_relationships_target ON incident.incident_relationships (target_incident_id);
