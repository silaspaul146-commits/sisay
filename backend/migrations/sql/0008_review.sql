-- 0008_review: review queue and reviewer notes (DB spec 4.6)
CREATE TABLE review.review_items (
  id                uuid        NOT NULL DEFAULT gen_random_uuid(),
  item_type         text        NOT NULL,
  report_id         uuid,
  incident_id       uuid,
  match_decision_id uuid,
  status            text        NOT NULL DEFAULT 'open',
  priority          smallint    NOT NULL DEFAULT 3,
  assigned_to       uuid,
  resolution        text,
  resolved_by       uuid,
  resolved_at       timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_review_items PRIMARY KEY (id),
  CONSTRAINT fk_review_items_report_id FOREIGN KEY (report_id) REFERENCES reporting.reports (id),
  CONSTRAINT fk_review_items_incident_id FOREIGN KEY (incident_id) REFERENCES incident.incidents (id),
  CONSTRAINT fk_review_items_match_decision_id
    FOREIGN KEY (match_decision_id) REFERENCES reporting.report_match_decisions (id),
  CONSTRAINT fk_review_items_assigned_to FOREIGN KEY (assigned_to) REFERENCES identity.users (id),
  CONSTRAINT fk_review_items_resolved_by FOREIGN KEY (resolved_by) REFERENCES identity.users (id),
  CONSTRAINT ck_review_items_type CHECK (item_type IN
    ('ambiguous_match','report_quarantine','incident_verification','publication_review')),
  CONSTRAINT ck_review_items_target CHECK (report_id IS NOT NULL OR incident_id IS NOT NULL),
  CONSTRAINT ck_review_items_ambiguous_shape
    CHECK (item_type <> 'ambiguous_match' OR (report_id IS NOT NULL AND match_decision_id IS NOT NULL)),
  CONSTRAINT ck_review_items_status CHECK (status IN ('open','claimed','resolved','dismissed')),
  CONSTRAINT ck_review_items_priority CHECK (priority BETWEEN 1 AND 5),
  CONSTRAINT ck_review_items_resolution
    CHECK ((status IN ('resolved','dismissed')) = (resolved_at IS NOT NULL AND resolved_by IS NOT NULL))
);
CREATE UNIQUE INDEX uq_review_items_open_report ON review.review_items (item_type, report_id)
  WHERE status IN ('open','claimed') AND report_id IS NOT NULL;
CREATE UNIQUE INDEX uq_review_items_open_incident ON review.review_items (item_type, incident_id)
  WHERE status IN ('open','claimed') AND report_id IS NULL;
CREATE INDEX ix_review_items_queue ON review.review_items (status, priority, created_at)
  WHERE status IN ('open','claimed');
CREATE TRIGGER trg_review_items_touch BEFORE UPDATE ON review.review_items
  FOR EACH ROW EXECUTE FUNCTION ops.touch_updated_at();

CREATE TABLE review.review_notes (
  id              uuid        NOT NULL DEFAULT gen_random_uuid(),
  review_item_id  uuid,
  report_id       uuid,
  incident_id     uuid,
  author_id       uuid        NOT NULL,
  organization_id uuid,
  body            text        NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_review_notes PRIMARY KEY (id),
  CONSTRAINT fk_review_notes_review_item_id FOREIGN KEY (review_item_id) REFERENCES review.review_items (id),
  CONSTRAINT fk_review_notes_report_id FOREIGN KEY (report_id) REFERENCES reporting.reports (id),
  CONSTRAINT fk_review_notes_incident_id FOREIGN KEY (incident_id) REFERENCES incident.incidents (id),
  CONSTRAINT fk_review_notes_author_id FOREIGN KEY (author_id) REFERENCES identity.users (id),
  CONSTRAINT fk_review_notes_organization_id FOREIGN KEY (organization_id) REFERENCES org.organizations (id),
  CONSTRAINT ck_review_notes_target
    CHECK (num_nonnulls(review_item_id, report_id, incident_id) >= 1),
  CONSTRAINT ck_review_notes_body_len CHECK (char_length(body) BETWEEN 1 AND 10000)
);
CREATE INDEX ix_review_notes_report_id ON review.review_notes (report_id) WHERE report_id IS NOT NULL;
CREATE INDEX ix_review_notes_incident_id ON review.review_notes (incident_id) WHERE incident_id IS NOT NULL;
CREATE INDEX ix_review_notes_review_item_id ON review.review_notes (review_item_id) WHERE review_item_id IS NOT NULL;
