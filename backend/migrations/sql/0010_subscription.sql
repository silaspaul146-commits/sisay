-- 0010_subscription: subscriber principals, saved places, subscriptions, journey checks (DB spec 4.8)
-- Tables only; the code for these modules is a later phase (docs/DECISIONS.md).
CREATE TABLE subscription.subscriber_principals (
  id              uuid        NOT NULL DEFAULT gen_random_uuid(),
  user_id         uuid,
  installation_id uuid,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_subscriber_principals PRIMARY KEY (id),
  CONSTRAINT fk_subscriber_principals_user_id FOREIGN KEY (user_id) REFERENCES identity.users (id),
  CONSTRAINT fk_subscriber_principals_installation_id
    FOREIGN KEY (installation_id) REFERENCES identity.installations (id),
  CONSTRAINT ck_subscriber_principals_exactly_one_owner
    CHECK (num_nonnulls(user_id, installation_id) = 1)
);
CREATE UNIQUE INDEX uq_subscriber_principals_user ON subscription.subscriber_principals (user_id)
  WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX uq_subscriber_principals_installation
  ON subscription.subscriber_principals (installation_id) WHERE installation_id IS NOT NULL;

CREATE TABLE subscription.saved_locations (
  id            uuid        NOT NULL DEFAULT gen_random_uuid(),
  subscriber_id uuid        NOT NULL,
  name          text        NOT NULL,
  location      geography(Point, 4326) NOT NULL,
  radius_m      integer     NOT NULL DEFAULT 1000,
  enabled       boolean     NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_saved_locations PRIMARY KEY (id),
  CONSTRAINT uq_saved_locations_id_subscriber UNIQUE (id, subscriber_id),
  CONSTRAINT fk_saved_locations_subscriber_id
    FOREIGN KEY (subscriber_id) REFERENCES subscription.subscriber_principals (id),
  CONSTRAINT ck_saved_locations_radius CHECK (radius_m BETWEEN 100 AND 50000),
  CONSTRAINT ck_saved_locations_name_len CHECK (char_length(name) BETWEEN 1 AND 100)
);
CREATE INDEX gx_saved_locations_location ON subscription.saved_locations USING gist (location) WHERE enabled;
CREATE INDEX ix_saved_locations_subscriber_id ON subscription.saved_locations (subscriber_id);
CREATE TRIGGER trg_saved_locations_touch BEFORE UPDATE ON subscription.saved_locations
  FOR EACH ROW EXECUTE FUNCTION ops.touch_updated_at();

CREATE TABLE subscription.saved_routes (
  id               uuid        NOT NULL DEFAULT gen_random_uuid(),
  subscriber_id    uuid        NOT NULL,
  name             text        NOT NULL,
  route_geometry   geography(MultiLineString, 4326) NOT NULL,
  corridor_width_m integer     NOT NULL DEFAULT 1000,
  enabled          boolean     NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_saved_routes PRIMARY KEY (id),
  CONSTRAINT uq_saved_routes_id_subscriber UNIQUE (id, subscriber_id),
  CONSTRAINT fk_saved_routes_subscriber_id
    FOREIGN KEY (subscriber_id) REFERENCES subscription.subscriber_principals (id),
  CONSTRAINT ck_saved_routes_corridor CHECK (corridor_width_m BETWEEN 100 AND 20000),
  CONSTRAINT ck_saved_routes_name_len CHECK (char_length(name) BETWEEN 1 AND 100),
  CONSTRAINT ck_saved_routes_valid CHECK (ST_IsValid(route_geometry::geometry)),
  CONSTRAINT ck_saved_routes_points CHECK (ST_NPoints(route_geometry::geometry) BETWEEN 2 AND 5000),
  CONSTRAINT ck_saved_routes_length CHECK (ST_Length(route_geometry) <= 1000000)
);
CREATE INDEX gx_saved_routes_route ON subscription.saved_routes USING gist (route_geometry) WHERE enabled;
CREATE INDEX ix_saved_routes_subscriber_id ON subscription.saved_routes (subscriber_id);
CREATE TRIGGER trg_saved_routes_touch BEFORE UPDATE ON subscription.saved_routes
  FOR EACH ROW EXECUTE FUNCTION ops.touch_updated_at();

CREATE TABLE subscription.alert_subscriptions (
  id                uuid        NOT NULL DEFAULT gen_random_uuid(),
  subscriber_id     uuid        NOT NULL,
  saved_location_id uuid,
  saved_route_id    uuid,
  all_categories    boolean     NOT NULL DEFAULT true,
  min_severity      text        NOT NULL DEFAULT 'moderate',
  enabled           boolean     NOT NULL DEFAULT true,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_alert_subscriptions PRIMARY KEY (id),
  CONSTRAINT fk_alert_subscriptions_subscriber_id
    FOREIGN KEY (subscriber_id) REFERENCES subscription.subscriber_principals (id),
  CONSTRAINT fk_alert_subscriptions_saved_location
    FOREIGN KEY (saved_location_id, subscriber_id)
    REFERENCES subscription.saved_locations (id, subscriber_id) ON DELETE CASCADE,
  CONSTRAINT fk_alert_subscriptions_saved_route
    FOREIGN KEY (saved_route_id, subscriber_id)
    REFERENCES subscription.saved_routes (id, subscriber_id) ON DELETE CASCADE,
  CONSTRAINT ck_alert_subscriptions_exactly_one_target
    CHECK (num_nonnulls(saved_location_id, saved_route_id) = 1),
  CONSTRAINT ck_alert_subscriptions_min_severity
    CHECK (min_severity IN ('low','moderate','high','critical'))
);
CREATE UNIQUE INDEX uq_alert_subscriptions_location ON subscription.alert_subscriptions (saved_location_id)
  WHERE saved_location_id IS NOT NULL;
CREATE UNIQUE INDEX uq_alert_subscriptions_route ON subscription.alert_subscriptions (saved_route_id)
  WHERE saved_route_id IS NOT NULL;
CREATE INDEX ix_alert_subscriptions_subscriber_id ON subscription.alert_subscriptions (subscriber_id);
CREATE TRIGGER trg_alert_subscriptions_touch BEFORE UPDATE ON subscription.alert_subscriptions
  FOR EACH ROW EXECUTE FUNCTION ops.touch_updated_at();

CREATE TABLE subscription.alert_subscription_categories (
  subscription_id uuid     NOT NULL,
  category_id     smallint NOT NULL,
  CONSTRAINT pk_alert_subscription_categories PRIMARY KEY (subscription_id, category_id),
  CONSTRAINT fk_asc_subscription_id FOREIGN KEY (subscription_id)
    REFERENCES subscription.alert_subscriptions (id) ON DELETE CASCADE,
  CONSTRAINT fk_asc_category_id FOREIGN KEY (category_id) REFERENCES ref.incident_categories (id)
);
CREATE INDEX ix_asc_category_id ON subscription.alert_subscription_categories (category_id);

CREATE TABLE subscription.journey_checks (
  id               uuid        NOT NULL DEFAULT gen_random_uuid(),
  subscriber_id    uuid,
  origin           geography(Point, 4326) NOT NULL,
  destination      geography(Point, 4326) NOT NULL,
  route_geometry   geography(MultiLineString, 4326) NOT NULL,
  corridor_width_m integer     NOT NULL DEFAULT 1000,
  status           text        NOT NULL DEFAULT 'pending',
  result_summary   jsonb,
  requested_at     timestamptz NOT NULL DEFAULT now(),
  expires_at       timestamptz NOT NULL DEFAULT now() + interval '12 hours',
  CONSTRAINT pk_journey_checks PRIMARY KEY (id),
  CONSTRAINT fk_journey_checks_subscriber_id
    FOREIGN KEY (subscriber_id) REFERENCES subscription.subscriber_principals (id) ON DELETE CASCADE,
  CONSTRAINT ck_journey_checks_status CHECK (status IN ('pending','completed','failed','expired')),
  CONSTRAINT ck_journey_checks_corridor CHECK (corridor_width_m BETWEEN 100 AND 20000),
  CONSTRAINT ck_journey_checks_expiry
    CHECK (expires_at > requested_at AND expires_at <= requested_at + interval '72 hours'),
  CONSTRAINT ck_journey_checks_valid CHECK (ST_IsValid(route_geometry::geometry)),
  CONSTRAINT ck_journey_checks_points CHECK (ST_NPoints(route_geometry::geometry) BETWEEN 2 AND 5000),
  CONSTRAINT ck_journey_checks_length CHECK (ST_Length(route_geometry) <= 1000000)
);
CREATE INDEX ix_journey_checks_expires_at ON subscription.journey_checks (expires_at);
CREATE INDEX ix_journey_checks_subscriber_id ON subscription.journey_checks (subscriber_id)
  WHERE subscriber_id IS NOT NULL;
