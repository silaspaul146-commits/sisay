-- 0011_alerting: alerts, versions, distribution decisions, deliveries (DB spec 4.9)
-- Tables only; alerting code is a later phase (docs/DECISIONS.md).
CREATE TABLE alerting.alerts (
  id                     uuid        NOT NULL DEFAULT gen_random_uuid(),
  incident_id            uuid        NOT NULL,
  current_version_number integer     NOT NULL DEFAULT 1,
  distribution_level     text        NOT NULL,
  geographic_scope       geography(MultiPolygon, 4326) NOT NULL,
  status                 text        NOT NULL DEFAULT 'draft',
  distribution_reason    text        NOT NULL,
  uncertainty_message    text        NOT NULL,
  expires_at             timestamptz NOT NULL,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_alerts PRIMARY KEY (id),
  CONSTRAINT fk_alerts_incident_id FOREIGN KEY (incident_id) REFERENCES incident.incidents (id),
  CONSTRAINT ck_alerts_distribution_level CHECK (distribution_level IN ('internal','subscribers','priority')),
  CONSTRAINT ck_alerts_status CHECK (status IN ('draft','active','withdrawn','expired')),
  CONSTRAINT ck_alerts_expiry CHECK (expires_at > created_at),
  CONSTRAINT ck_alerts_scope_valid CHECK (ST_IsValid(geographic_scope::geometry)),
  CONSTRAINT ck_alerts_scope_size CHECK (ST_Area(geographic_scope) <= 5.0e10)
);
CREATE UNIQUE INDEX uq_alerts_one_active_per_incident ON alerting.alerts (incident_id) WHERE status = 'active';
CREATE INDEX gx_alerts_geographic_scope ON alerting.alerts USING gist (geographic_scope) WHERE status = 'active';
CREATE INDEX ix_alerts_expiry ON alerting.alerts (expires_at) WHERE status = 'active';
CREATE TRIGGER trg_alerts_touch BEFORE UPDATE ON alerting.alerts
  FOR EACH ROW EXECUTE FUNCTION ops.touch_updated_at();

CREATE TABLE alerting.alert_versions (
  id                  uuid        NOT NULL DEFAULT gen_random_uuid(),
  alert_id            uuid        NOT NULL,
  version_number      integer     NOT NULL,
  message             text        NOT NULL,
  uncertainty_message text        NOT NULL,
  geographic_scope    geography(MultiPolygon, 4326) NOT NULL,
  distribution_level  text        NOT NULL,
  change_reason       text,
  actor_id            uuid,
  actor_type          text        NOT NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_alert_versions PRIMARY KEY (id),
  CONSTRAINT uq_alert_versions_alert_version UNIQUE (alert_id, version_number),
  CONSTRAINT uq_alert_versions_id_alert UNIQUE (id, alert_id),
  CONSTRAINT fk_alert_versions_alert_id FOREIGN KEY (alert_id) REFERENCES alerting.alerts (id),
  CONSTRAINT fk_alert_versions_actor_id FOREIGN KEY (actor_id) REFERENCES identity.users (id),
  CONSTRAINT ck_alert_versions_number CHECK (version_number >= 1),
  CONSTRAINT ck_alert_versions_level CHECK (distribution_level IN ('internal','subscribers','priority')),
  CONSTRAINT ck_alert_versions_message_len CHECK (char_length(message) BETWEEN 1 AND 1000),
  CONSTRAINT ck_alert_versions_actor_type CHECK (actor_type IN ('user','system','worker')),
  CONSTRAINT ck_alert_versions_actor CHECK ((actor_type = 'user') = (actor_id IS NOT NULL))
);

CREATE TABLE alerting.alert_distribution_decisions (
  id               uuid        NOT NULL DEFAULT gen_random_uuid(),
  alert_id         uuid        NOT NULL,
  alert_version_id uuid,
  previous_level   text,
  new_level        text        NOT NULL,
  reason           text        NOT NULL,
  decision_source  text        NOT NULL,
  inputs           jsonb       NOT NULL DEFAULT '{}',
  actor_id         uuid,
  actor_type       text        NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_alert_distribution_decisions PRIMARY KEY (id),
  CONSTRAINT fk_add_alert_id FOREIGN KEY (alert_id) REFERENCES alerting.alerts (id),
  CONSTRAINT fk_add_alert_version FOREIGN KEY (alert_version_id, alert_id)
    REFERENCES alerting.alert_versions (id, alert_id),
  CONSTRAINT fk_add_actor_id FOREIGN KEY (actor_id) REFERENCES identity.users (id),
  CONSTRAINT ck_add_levels CHECK (new_level IN ('internal','subscribers','priority','withdrawn')
    AND (previous_level IS NULL OR previous_level IN ('internal','subscribers','priority','withdrawn'))),
  CONSTRAINT ck_add_changed CHECK (previous_level IS DISTINCT FROM new_level),
  CONSTRAINT ck_add_source CHECK (decision_source IN ('policy_engine','alert_officer','expiry_job')),
  CONSTRAINT ck_add_actor_type CHECK (actor_type IN ('user','system','worker')),
  CONSTRAINT ck_add_actor CHECK ((actor_type = 'user') = (actor_id IS NOT NULL))
);
CREATE INDEX ix_add_alert_time ON alerting.alert_distribution_decisions (alert_id, created_at);

CREATE TABLE alerting.alert_deliveries (
  id                   uuid        NOT NULL DEFAULT gen_random_uuid(),
  alert_id             uuid        NOT NULL,
  alert_version_id     uuid        NOT NULL,
  subscriber_id        uuid        NOT NULL,
  subscription_id      uuid,
  endpoint_id          uuid        NOT NULL,
  delivery_status      text        NOT NULL DEFAULT 'queued',
  attempts             smallint    NOT NULL DEFAULT 0,
  provider_message_id  text,
  last_error           text,
  queued_at            timestamptz NOT NULL DEFAULT now(),
  next_attempt_at      timestamptz NOT NULL DEFAULT now(),
  attempted_at         timestamptz,
  provider_accepted_at timestamptz,
  delivered_at         timestamptz,
  CONSTRAINT pk_alert_deliveries PRIMARY KEY (id),
  CONSTRAINT fk_alert_deliveries_version FOREIGN KEY (alert_version_id, alert_id)
    REFERENCES alerting.alert_versions (id, alert_id),
  CONSTRAINT fk_alert_deliveries_subscriber_id
    FOREIGN KEY (subscriber_id) REFERENCES subscription.subscriber_principals (id),
  CONSTRAINT fk_alert_deliveries_subscription_id
    FOREIGN KEY (subscription_id) REFERENCES subscription.alert_subscriptions (id) ON DELETE SET NULL,
  CONSTRAINT fk_alert_deliveries_endpoint_id FOREIGN KEY (endpoint_id) REFERENCES identity.push_endpoints (id),
  CONSTRAINT uq_alert_deliveries_dedup UNIQUE (alert_version_id, endpoint_id),
  CONSTRAINT ck_alert_deliveries_status CHECK (delivery_status IN
    ('queued','sending','provider_accepted','provider_rejected','failed','cancelled','client_acknowledged')),
  CONSTRAINT ck_alert_deliveries_attempts CHECK (attempts BETWEEN 0 AND 20),
  CONSTRAINT ck_alert_deliveries_accept_order
    CHECK (provider_accepted_at IS NULL OR attempted_at IS NOT NULL)
);
CREATE INDEX ix_alert_deliveries_dispatch ON alerting.alert_deliveries (next_attempt_at)
  WHERE delivery_status IN ('queued','sending');
CREATE INDEX ix_alert_deliveries_alert_id ON alerting.alert_deliveries (alert_id);
CREATE INDEX ix_alert_deliveries_subscriber_id ON alerting.alert_deliveries (subscriber_id, queued_at DESC);
