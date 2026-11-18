-- 0002_ref: disclosure policies, categories, compatibility (DB spec 4.1)
CREATE TABLE ref.disclosure_policies (
  id                    smallint GENERATED ALWAYS AS IDENTITY,
  code                  text        NOT NULL,
  version               integer     NOT NULL,
  public_grid_m         integer     NOT NULL,
  min_alert_radius_m    integer     NOT NULL,
  public_location_mode  text        NOT NULL DEFAULT 'generalized',
  publish_on_map        boolean     NOT NULL DEFAULT true,
  publish_description   boolean     NOT NULL DEFAULT false,
  publish_affected_area boolean     NOT NULL DEFAULT false,
  review_before_publish boolean     NOT NULL DEFAULT false,
  public_delay          interval    NOT NULL DEFAULT interval '0',
  max_public_age        interval    NOT NULL DEFAULT interval '7 days',
  status                text        NOT NULL DEFAULT 'draft',
  created_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_disclosure_policies PRIMARY KEY (id),
  CONSTRAINT uq_disclosure_policies_code_version UNIQUE (code, version),
  CONSTRAINT ck_disclosure_policies_version CHECK (version >= 1),
  CONSTRAINT ck_disclosure_policies_grid CHECK (public_grid_m BETWEEN 50 AND 50000),
  CONSTRAINT ck_disclosure_policies_min_radius CHECK (min_alert_radius_m >= public_grid_m),
  CONSTRAINT ck_disclosure_policies_delay CHECK (public_delay >= interval '0'),
  CONSTRAINT ck_disclosure_policies_location_mode
    CHECK (public_location_mode IN ('generalized','area_only','hidden')),
  CONSTRAINT ck_disclosure_policies_status CHECK (status IN ('draft','active','retired'))
);

CREATE TABLE ref.incident_categories (
  id                   smallint GENERATED ALWAYS AS IDENTITY,
  code                 text        NOT NULL,
  name                 text        NOT NULL,
  description          text,
  disclosure_policy_id smallint    NOT NULL,
  is_sensitive         boolean     NOT NULL DEFAULT false,
  match_radius_m       integer     NOT NULL DEFAULT 500,
  match_time_window    interval    NOT NULL DEFAULT interval '6 hours',
  default_severity     text        NOT NULL DEFAULT 'moderate',
  active               boolean     NOT NULL DEFAULT true,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_incident_categories PRIMARY KEY (id),
  CONSTRAINT uq_incident_categories_code UNIQUE (code),
  CONSTRAINT fk_incident_categories_disclosure_policy_id
    FOREIGN KEY (disclosure_policy_id) REFERENCES ref.disclosure_policies (id),
  CONSTRAINT ck_incident_categories_code CHECK (code ~ '^[a-z][a-z0-9_]{1,62}$'),
  CONSTRAINT ck_incident_categories_radius CHECK (match_radius_m BETWEEN 10 AND 50000),
  CONSTRAINT ck_incident_categories_window
    CHECK (match_time_window BETWEEN interval '5 minutes' AND interval '30 days'),
  CONSTRAINT ck_incident_categories_severity
    CHECK (default_severity IN ('low','moderate','high','critical'))
);
CREATE INDEX ix_incident_categories_disclosure_policy_id ON ref.incident_categories (disclosure_policy_id);
CREATE TRIGGER trg_incident_categories_touch BEFORE UPDATE ON ref.incident_categories
  FOR EACH ROW EXECUTE FUNCTION ops.touch_updated_at();

CREATE TABLE ref.category_compatibility (
  category_id            smallint     NOT NULL,
  compatible_category_id smallint     NOT NULL,
  weight                 numeric(3,2) NOT NULL,
  CONSTRAINT pk_category_compatibility PRIMARY KEY (category_id, compatible_category_id),
  CONSTRAINT fk_category_compatibility_category_id
    FOREIGN KEY (category_id) REFERENCES ref.incident_categories (id),
  CONSTRAINT fk_category_compatibility_compatible_category_id
    FOREIGN KEY (compatible_category_id) REFERENCES ref.incident_categories (id),
  CONSTRAINT ck_category_compatibility_distinct CHECK (category_id <> compatible_category_id),
  CONSTRAINT ck_category_compatibility_weight CHECK (weight > 0 AND weight <= 1)
);
