-- 0009_disclosure: deterministic public snapping, projections, public views (DB spec 4.7, 7.1, 11.3)

-- Snap to the centre of a metric grid cell in the point's UTM zone. Deterministic, so repeated
-- regeneration cannot be averaged to recover the true point (F-18). Max displacement grid_m * 0.71.
CREATE FUNCTION disclosure.snap_public_point(p geography, grid_m integer)
RETURNS geography LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
  WITH z AS (
    SELECT p::geometry AS g,
           (CASE WHEN ST_Y(p::geometry) >= 0 THEN 32600 ELSE 32700 END)
             + LEAST(60, floor((ST_X(p::geometry) + 180) / 6)::int + 1) AS srid
  )
  SELECT ST_Transform(
           ST_Translate(
             ST_SnapToGrid(ST_Translate(ST_Transform(g, srid), -grid_m / 2.0, -grid_m / 2.0), grid_m),
             grid_m / 2.0, grid_m / 2.0),
           4326)::geography
  FROM z;
$$;

CREATE TABLE disclosure.public_incident_projections (
  id                   uuid        NOT NULL DEFAULT gen_random_uuid(),   -- v4 only; this is the public id
  incident_id          uuid        NOT NULL,
  version              integer     NOT NULL DEFAULT 1,
  is_visible           boolean     NOT NULL,
  publication_state    text        NOT NULL DEFAULT 'pending',
  restricted_reason    text,
  source_lock_version  integer     NOT NULL,
  public_category_code text        NOT NULL,
  public_location      geography(Point, 4326),
  public_precision_m   integer     NOT NULL,
  public_area          geography(MultiPolygon, 4326),
  public_description   text,
  public_verification  text        NOT NULL,
  public_lifecycle     text        NOT NULL,
  public_confidence    text        NOT NULL,
  public_severity      text        NOT NULL,
  uncertainty_note     text        NOT NULL,
  public_observed_at   timestamptz NOT NULL,
  disclosure_policy_id smallint    NOT NULL,
  content_hash         bytea       NOT NULL,
  generated_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_public_incident_projections PRIMARY KEY (id),
  CONSTRAINT uq_public_incident_projections_incident UNIQUE (incident_id),
  CONSTRAINT fk_pip_incident_id FOREIGN KEY (incident_id) REFERENCES incident.incidents (id),
  CONSTRAINT fk_pip_disclosure_policy_id
    FOREIGN KEY (disclosure_policy_id) REFERENCES ref.disclosure_policies (id),
  CONSTRAINT ck_pip_visible_has_location CHECK (NOT is_visible OR public_location IS NOT NULL),
  CONSTRAINT ck_pip_publication_state CHECK (publication_state IN
    ('pending','published','restricted','withdrawn')),
  CONSTRAINT ck_pip_restricted_reason
    CHECK ((publication_state = 'restricted') = (restricted_reason IS NOT NULL)),
  CONSTRAINT ck_pip_precision CHECK (public_precision_m BETWEEN 50 AND 50000),
  CONSTRAINT ck_pip_verification CHECK (public_verification IN
    ('unverified','under_review','verified','disputed','rejected')),
  CONSTRAINT ck_pip_lifecycle CHECK (public_lifecycle IN ('active','monitoring','resolved','removed')),
  CONSTRAINT ck_pip_confidence CHECK (public_confidence IN ('low','medium','high')),
  CONSTRAINT ck_pip_severity CHECK (public_severity IN ('unknown','low','moderate','high','critical')),
  CONSTRAINT ck_pip_description_len CHECK (public_description IS NULL OR char_length(public_description) <= 1000),
  CONSTRAINT ck_pip_rejected_hidden CHECK (public_verification <> 'rejected' OR NOT is_visible)
);
CREATE INDEX gx_pip_public_location ON disclosure.public_incident_projections
  USING gist (public_location) WHERE is_visible AND publication_state = 'published';
CREATE INDEX ix_pip_generated_at ON disclosure.public_incident_projections (generated_at);

CREATE TABLE disclosure.public_incident_projection_history (
  incident_id          uuid        NOT NULL,
  version              integer     NOT NULL,
  is_visible           boolean     NOT NULL,
  publication_state    text        NOT NULL,
  source_lock_version  integer     NOT NULL,
  public_category_code text        NOT NULL,
  public_location      geography(Point, 4326),
  public_precision_m   integer     NOT NULL,
  public_area          geography(MultiPolygon, 4326),
  public_description   text,
  public_verification  text        NOT NULL,
  public_lifecycle     text        NOT NULL,
  public_confidence    text        NOT NULL,
  public_severity      text        NOT NULL,
  uncertainty_note     text        NOT NULL,
  public_observed_at   timestamptz NOT NULL,
  disclosure_policy_id smallint    NOT NULL,
  content_hash         bytea       NOT NULL,
  generated_at         timestamptz NOT NULL,
  trigger_reason       text        NOT NULL,
  CONSTRAINT pk_public_incident_projection_history PRIMARY KEY (incident_id, version),
  CONSTRAINT fk_piph_incident_id FOREIGN KEY (incident_id) REFERENCES incident.incidents (id),
  CONSTRAINT fk_piph_disclosure_policy_id
    FOREIGN KEY (disclosure_policy_id) REFERENCES ref.disclosure_policies (id)
);

-- The only objects the public API role can read. The internal incident UUID is never exposed.
CREATE VIEW disclosure.public_incidents_v WITH (security_barrier = true) AS
SELECT id AS public_id,
       version, public_category_code, public_location, public_precision_m, public_area,
       public_description, public_verification, public_lifecycle, public_confidence,
       public_severity, uncertainty_note, public_observed_at, generated_at
FROM   disclosure.public_incident_projections
WHERE  is_visible AND publication_state = 'published';

CREATE VIEW disclosure.public_incident_removals_v WITH (security_barrier = true) AS
SELECT id AS public_id, version, generated_at AS removed_at
FROM   disclosure.public_incident_projections
WHERE  NOT (is_visible AND publication_state = 'published')
  AND  generated_at > now() - interval '7 days';
