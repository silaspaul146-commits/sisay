-- 0017_alerts_and_installations: anonymous device credentials, alert inbox, alert snapshots.
-- See docs/DECISIONS.md "Alerts (2026-11-19)".

-- 1. Installation credentials. Saved places reveal where someone lives or travels, so the app
--    proves it owns an installation with a secret token (stored as an HMAC, like report tokens),
--    not just by sending its id. Installations created before this (from report headers) have none
--    and cannot use personal routes until the app registers.
ALTER TABLE identity.installations
  ADD COLUMN token_hash bytea,
  ADD COLUMN token_pepper_version smallint,
  ADD CONSTRAINT ck_installations_token_pair CHECK ((token_hash IS NULL) = (token_pepper_version IS NULL));
CREATE UNIQUE INDEX uq_installations_token_hash ON identity.installations (token_hash) WHERE token_hash IS NOT NULL;

-- 2. Alert inbox: one row per subscriber per alert version, written by the fan-out worker. It is what
--    the app's alert list shows, whether or not push delivery worked (or the phone has push at all).
--    alert_deliveries stays the per-device push record.
CREATE TABLE alerting.alert_inbox (
  id               uuid        NOT NULL DEFAULT gen_random_uuid(),
  alert_id         uuid        NOT NULL,
  alert_version_id uuid        NOT NULL,
  subscriber_id    uuid        NOT NULL,
  subscription_id  uuid,
  created_at       timestamptz NOT NULL DEFAULT now(),
  acknowledged_at  timestamptz,
  CONSTRAINT pk_alert_inbox PRIMARY KEY (id),
  CONSTRAINT fk_alert_inbox_version FOREIGN KEY (alert_version_id, alert_id)
    REFERENCES alerting.alert_versions (id, alert_id),
  CONSTRAINT fk_alert_inbox_subscriber_id
    FOREIGN KEY (subscriber_id) REFERENCES subscription.subscriber_principals (id) ON DELETE CASCADE,
  CONSTRAINT fk_alert_inbox_subscription_id
    FOREIGN KEY (subscription_id) REFERENCES subscription.alert_subscriptions (id) ON DELETE SET NULL,
  CONSTRAINT uq_alert_inbox_version_subscriber UNIQUE (alert_version_id, subscriber_id)
);
CREATE INDEX ix_alert_inbox_subscriber_time ON alerting.alert_inbox (subscriber_id, created_at DESC);
CREATE INDEX ix_alert_inbox_alert_id ON alerting.alert_inbox (alert_id);

-- 3. What the citizen may see about an alert, frozen per version. The citizen role cannot read
--    incident.* (internal location, reports); it reads these snapshots instead. public_point is the
--    incident location snapped to the category's public grid, never the internal point.
ALTER TABLE alerting.alerts ADD COLUMN category_id smallint REFERENCES ref.incident_categories (id);
ALTER TABLE alerting.alert_versions
  ADD COLUMN category_code       text,
  ADD COLUMN verification_status text,
  ADD COLUMN severity            text,
  ADD COLUMN status              text,
  ADD COLUMN notify              boolean NOT NULL DEFAULT true,
  ADD COLUMN public_point        geography(Point, 4326),
  ADD COLUMN public_precision_m  integer,
  ADD COLUMN policy_version      text,
  ADD CONSTRAINT ck_alert_versions_status CHECK (status IS NULL OR status IN ('active','withdrawn','expired'));

-- 4. Push token registration without letting the citizen role read tokens (DB spec: only the
--    alerting worker reads them). A reinstall can bring the same FCM token to a new installation.
CREATE FUNCTION identity.register_push_endpoint(p_installation_id uuid, p_provider text, p_token text)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE
  v_id uuid;
BEGIN
  INSERT INTO identity.push_endpoints (installation_id, provider, token, status)
  VALUES (p_installation_id, p_provider, p_token, 'active')
  ON CONFLICT (provider, token) DO UPDATE
    SET installation_id = EXCLUDED.installation_id, status = 'active', user_id = NULL, updated_at = now()
  RETURNING id INTO v_id;
  -- One active endpoint per installation and provider: older tokens of this app are superseded.
  UPDATE identity.push_endpoints SET status = 'revoked', updated_at = now()
  WHERE installation_id = p_installation_id AND provider = p_provider AND id <> v_id AND status = 'active';
  RETURN v_id;
END $$;
REVOKE ALL ON FUNCTION identity.register_push_endpoint(uuid, text, text) FROM PUBLIC;
