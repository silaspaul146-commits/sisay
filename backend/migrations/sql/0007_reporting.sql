-- 0007_reporting: reports, identity link, credentials, evidence, matching, association (DB spec 4.5)
CREATE TABLE reporting.reports (
  id                  uuid        NOT NULL DEFAULT gen_random_uuid(),
  public_reference    text        NOT NULL,
  category_id         smallint    NOT NULL,
  incident_id         uuid,
  description         text,
  incident_location   geography(Point, 4326) NOT NULL,
  location_accuracy_m integer     NOT NULL,
  location_source     text        NOT NULL,
  observed_at         timestamptz NOT NULL,
  client_created_at   timestamptz,
  received_at         timestamptz NOT NULL DEFAULT now(),
  source_type         text        NOT NULL,
  idempotency_scope   text        NOT NULL,
  idempotency_key     uuid        NOT NULL,
  request_fingerprint bytea       NOT NULL,
  intake_status       text        NOT NULL DEFAULT 'received',
  intake_reason       text,
  redacted_at         timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_reports PRIMARY KEY (id),
  CONSTRAINT uq_reports_public_reference UNIQUE (public_reference),
  CONSTRAINT uq_reports_idempotency UNIQUE (idempotency_scope, idempotency_key),
  CONSTRAINT fk_reports_category_id FOREIGN KEY (category_id) REFERENCES ref.incident_categories (id),
  CONSTRAINT fk_reports_incident_id FOREIGN KEY (incident_id) REFERENCES incident.incidents (id),
  CONSTRAINT ck_reports_public_reference
    CHECK (public_reference ~ '^[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$'),
  CONSTRAINT ck_reports_accuracy CHECK (location_accuracy_m BETWEEN 0 AND 100000),
  CONSTRAINT ck_reports_location_source CHECK (location_source IN
    ('device_gps','device_network','manual_pin','geocoded_address')),
  CONSTRAINT ck_reports_source_type CHECK (source_type IN
    ('citizen_app','citizen_web','partner_org','staff_entry')),
  CONSTRAINT ck_reports_intake_status CHECK (intake_status IN
    ('received','accepted','needs_review','rejected','quarantined')),
  CONSTRAINT ck_reports_association_requires_accepted
    CHECK (incident_id IS NULL OR intake_status = 'accepted'),
  CONSTRAINT ck_reports_description_len CHECK (description IS NULL OR char_length(description) <= 5000),
  CONSTRAINT ck_reports_observed_not_future CHECK (observed_at <= received_at + interval '15 minutes'),
  CONSTRAINT ck_reports_scope_format CHECK (idempotency_scope ~ '^(inst|user|org|anon):[0-9a-f-]{0,36}$'),
  CONSTRAINT ck_reports_fingerprint_len CHECK (octet_length(request_fingerprint) = 32)
);
CREATE INDEX gx_reports_incident_location ON reporting.reports USING gist (incident_location);
CREATE INDEX ix_reports_incident_id ON reporting.reports (incident_id) WHERE incident_id IS NOT NULL;
CREATE INDEX ix_reports_intake_queue ON reporting.reports (intake_status, received_at)
  WHERE intake_status IN ('received','needs_review','quarantined');
CREATE INDEX ix_reports_category_observed ON reporting.reports (category_id, observed_at DESC);
CREATE TRIGGER trg_reports_touch BEFORE UPDATE ON reporting.reports
  FOR EACH ROW EXECUTE FUNCTION ops.touch_updated_at();

CREATE TABLE reporting.report_submitters (
  report_id          uuid        NOT NULL,
  user_id            uuid,
  installation_id    uuid,
  organization_id    uuid,
  identity_purged_at timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_report_submitters PRIMARY KEY (report_id),
  CONSTRAINT fk_report_submitters_report_id FOREIGN KEY (report_id) REFERENCES reporting.reports (id),
  CONSTRAINT fk_report_submitters_user_id FOREIGN KEY (user_id) REFERENCES identity.users (id),
  CONSTRAINT fk_report_submitters_installation_id
    FOREIGN KEY (installation_id) REFERENCES identity.installations (id),
  CONSTRAINT fk_report_submitters_organization_id
    FOREIGN KEY (organization_id) REFERENCES org.organizations (id)
);
CREATE INDEX ix_report_submitters_user_id ON reporting.report_submitters (user_id) WHERE user_id IS NOT NULL;
CREATE INDEX ix_report_submitters_installation_id
  ON reporting.report_submitters (installation_id, created_at) WHERE installation_id IS NOT NULL;

CREATE TABLE reporting.report_access_credentials (
  id               uuid        NOT NULL DEFAULT gen_random_uuid(),
  report_id        uuid        NOT NULL,
  token_hash       bytea       NOT NULL,
  hash_key_version smallint    NOT NULL,
  expires_at       timestamptz NOT NULL DEFAULT now() + interval '180 days',
  revoked_at       timestamptz,
  last_used_at     timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_report_access_credentials PRIMARY KEY (id),
  CONSTRAINT fk_report_access_credentials_report_id
    FOREIGN KEY (report_id) REFERENCES reporting.reports (id),
  CONSTRAINT uq_report_access_credentials_token_hash UNIQUE (token_hash),
  CONSTRAINT ck_report_access_credentials_hash_len CHECK (octet_length(token_hash) = 32),
  CONSTRAINT ck_report_access_credentials_expiry CHECK (expires_at > created_at)
);
CREATE INDEX ix_report_access_credentials_report_id ON reporting.report_access_credentials (report_id);

CREATE TABLE reporting.report_evidence (
  id                    uuid        NOT NULL DEFAULT gen_random_uuid(),
  report_id             uuid        NOT NULL,
  client_evidence_id    uuid        NOT NULL,
  storage_key           text        NOT NULL,
  mime_type             text        NOT NULL,
  checksum              bytea,
  original_checksum     bytea,
  file_size             bigint,
  access_classification text        NOT NULL DEFAULT 'restricted',
  upload_status         text        NOT NULL DEFAULT 'pending_upload',
  exif_stripped         boolean     NOT NULL DEFAULT false,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_report_evidence PRIMARY KEY (id),
  CONSTRAINT fk_report_evidence_report_id FOREIGN KEY (report_id) REFERENCES reporting.reports (id),
  CONSTRAINT uq_report_evidence_client_id UNIQUE (report_id, client_evidence_id),
  CONSTRAINT uq_report_evidence_storage_key UNIQUE (storage_key),
  CONSTRAINT ck_report_evidence_mime CHECK (mime_type IN
    ('image/jpeg','image/png','image/webp','image/heic','video/mp4','audio/mp4','audio/mpeg')),
  CONSTRAINT ck_report_evidence_size CHECK (file_size IS NULL OR file_size BETWEEN 1 AND 104857600),
  CONSTRAINT ck_report_evidence_checksum_len CHECK (checksum IS NULL OR octet_length(checksum) = 32),
  CONSTRAINT ck_report_evidence_classification CHECK (access_classification IN
    ('restricted','internal','partner_shareable','public_eligible')),
  CONSTRAINT ck_report_evidence_upload_status CHECK (upload_status IN
    ('pending_upload','uploaded','processing','processed','rejected','purged')),
  CONSTRAINT ck_report_evidence_processed_stripped
    CHECK (upload_status <> 'processed' OR (exif_stripped AND checksum IS NOT NULL)),
  CONSTRAINT ck_report_evidence_public_requires_processed
    CHECK (access_classification <> 'public_eligible' OR upload_status = 'processed')
);
CREATE INDEX ix_report_evidence_report_id ON reporting.report_evidence (report_id);
CREATE INDEX ix_report_evidence_processing ON reporting.report_evidence (upload_status, created_at)
  WHERE upload_status IN ('uploaded','processing');
CREATE TRIGGER trg_report_evidence_touch BEFORE UPDATE ON reporting.report_evidence
  FOR EACH ROW EXECUTE FUNCTION ops.touch_updated_at();

CREATE TABLE reporting.report_match_decisions (
  id                   uuid        NOT NULL DEFAULT gen_random_uuid(),
  report_id            uuid        NOT NULL,
  attempt              smallint    NOT NULL DEFAULT 1,
  outcome              text        NOT NULL,
  selected_incident_id uuid,
  created_incident_id  uuid,
  policy_version       text        NOT NULL,
  explanation          jsonb       NOT NULL,
  decided_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_report_match_decisions PRIMARY KEY (id),
  CONSTRAINT fk_rmd_report_id FOREIGN KEY (report_id) REFERENCES reporting.reports (id),
  CONSTRAINT fk_rmd_selected FOREIGN KEY (selected_incident_id) REFERENCES incident.incidents (id),
  CONSTRAINT fk_rmd_created FOREIGN KEY (created_incident_id) REFERENCES incident.incidents (id),
  CONSTRAINT uq_rmd_report_attempt UNIQUE (report_id, attempt),
  CONSTRAINT ck_rmd_outcome CHECK (outcome IN ('strong_match','ambiguous','no_match','ineligible')),
  CONSTRAINT ck_rmd_outcome_shape CHECK (
       (outcome = 'strong_match' AND selected_incident_id IS NOT NULL AND created_incident_id IS NULL)
    OR (outcome = 'no_match'     AND selected_incident_id IS NULL AND created_incident_id IS NOT NULL)
    OR (outcome IN ('ambiguous','ineligible')
          AND selected_incident_id IS NULL AND created_incident_id IS NULL))
);

CREATE TABLE reporting.report_match_candidates (
  match_decision_id uuid          NOT NULL,
  incident_id       uuid          NOT NULL,
  rank              smallint      NOT NULL,
  total_score       numeric(5,4)  NOT NULL,
  distance_m        numeric(10,1) NOT NULL,
  category_score    numeric(5,4)  NOT NULL,
  spatial_score     numeric(5,4)  NOT NULL,
  temporal_score    numeric(5,4)  NOT NULL,
  state_score       numeric(5,4)  NOT NULL,
  contradictions    text[]        NOT NULL DEFAULT '{}',
  CONSTRAINT pk_report_match_candidates PRIMARY KEY (match_decision_id, incident_id),
  CONSTRAINT fk_rmc_decision FOREIGN KEY (match_decision_id)
    REFERENCES reporting.report_match_decisions (id) ON DELETE CASCADE,
  CONSTRAINT fk_rmc_incident FOREIGN KEY (incident_id) REFERENCES incident.incidents (id),
  CONSTRAINT uq_rmc_decision_rank UNIQUE (match_decision_id, rank),
  CONSTRAINT ck_rmc_scores CHECK (total_score BETWEEN 0 AND 1 AND category_score BETWEEN 0 AND 1
    AND spatial_score BETWEEN 0 AND 1 AND temporal_score BETWEEN 0 AND 1 AND state_score BETWEEN 0 AND 1)
);
CREATE INDEX ix_rmc_incident_id ON reporting.report_match_candidates (incident_id);

CREATE TABLE reporting.report_association_history (
  id                   uuid        NOT NULL DEFAULT gen_random_uuid(),
  report_id            uuid        NOT NULL,
  previous_incident_id uuid,
  new_incident_id      uuid,
  action               text        NOT NULL,
  reason               text        NOT NULL,
  match_decision_id    uuid,
  actor_id             uuid,
  actor_type           text        NOT NULL,
  created_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_report_association_history PRIMARY KEY (id),
  CONSTRAINT fk_rah_report_id FOREIGN KEY (report_id) REFERENCES reporting.reports (id),
  CONSTRAINT fk_rah_previous_incident_id FOREIGN KEY (previous_incident_id) REFERENCES incident.incidents (id),
  CONSTRAINT fk_rah_new_incident_id FOREIGN KEY (new_incident_id) REFERENCES incident.incidents (id),
  CONSTRAINT fk_rah_match_decision_id
    FOREIGN KEY (match_decision_id) REFERENCES reporting.report_match_decisions (id),
  CONSTRAINT fk_rah_actor_id FOREIGN KEY (actor_id) REFERENCES identity.users (id),
  CONSTRAINT ck_rah_changed CHECK (previous_incident_id IS DISTINCT FROM new_incident_id),
  CONSTRAINT ck_rah_action CHECK (action IN ('auto_match','auto_create_provisional',
    'review_assign','review_unassign','reassign','merge_reassign')),
  CONSTRAINT ck_rah_action_shape CHECK (
       (action IN ('auto_match','auto_create_provisional','review_assign')
          AND previous_incident_id IS NULL AND new_incident_id IS NOT NULL)
    OR (action = 'review_unassign' AND previous_incident_id IS NOT NULL AND new_incident_id IS NULL)
    OR (action IN ('reassign','merge_reassign')
          AND previous_incident_id IS NOT NULL AND new_incident_id IS NOT NULL)),
  CONSTRAINT ck_rah_auto_has_decision
    CHECK (action NOT IN ('auto_match','auto_create_provisional') OR match_decision_id IS NOT NULL),
  CONSTRAINT ck_rah_actor_type CHECK (actor_type IN ('user','system','worker')),
  CONSTRAINT ck_rah_actor CHECK ((actor_type = 'user') = (actor_id IS NOT NULL))
);
CREATE INDEX ix_rah_report_time ON reporting.report_association_history (report_id, created_at);
CREATE INDEX ix_rah_new_incident ON reporting.report_association_history (new_incident_id)
  WHERE new_incident_id IS NOT NULL;
CREATE INDEX ix_rah_previous_incident ON reporting.report_association_history (previous_incident_id)
  WHERE previous_incident_id IS NOT NULL;
