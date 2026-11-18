-- 0003_identity: users, installations, push endpoints, platform permissions (DB spec 4.2)
CREATE TABLE identity.users (
  id           uuid        NOT NULL DEFAULT gen_random_uuid(),
  email        citext,
  phone        text,
  auth_subject text,
  status       text        NOT NULL DEFAULT 'pending',
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_users PRIMARY KEY (id),
  CONSTRAINT uq_users_auth_subject UNIQUE (auth_subject),
  CONSTRAINT ck_users_status CHECK (status IN ('pending','active','suspended','deleted')),
  CONSTRAINT ck_users_phone CHECK (phone IS NULL OR phone ~ '^\+[1-9][0-9]{6,14}$'),
  CONSTRAINT ck_users_contact CHECK (status = 'deleted' OR email IS NOT NULL OR phone IS NOT NULL)
);
CREATE UNIQUE INDEX uq_users_email ON identity.users (email) WHERE status <> 'deleted';
CREATE UNIQUE INDEX uq_users_phone ON identity.users (phone) WHERE status <> 'deleted';
CREATE TRIGGER trg_users_touch BEFORE UPDATE ON identity.users
  FOR EACH ROW EXECUTE FUNCTION ops.touch_updated_at();

CREATE TABLE identity.installations (
  id           uuid        NOT NULL DEFAULT gen_random_uuid(),
  platform     text        NOT NULL,
  app_version  text,
  status       text        NOT NULL DEFAULT 'active',
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_installations PRIMARY KEY (id),
  CONSTRAINT ck_installations_platform CHECK (platform IN ('android','ios','web')),
  CONSTRAINT ck_installations_status CHECK (status IN ('active','dormant','revoked'))
);
CREATE INDEX ix_installations_last_seen_at ON identity.installations (last_seen_at);

CREATE TABLE identity.push_endpoints (
  id              uuid        NOT NULL DEFAULT gen_random_uuid(),
  installation_id uuid        NOT NULL,
  user_id         uuid,
  provider        text        NOT NULL DEFAULT 'fcm',
  token           text        NOT NULL,
  status          text        NOT NULL DEFAULT 'active',
  last_success_at timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_push_endpoints PRIMARY KEY (id),
  CONSTRAINT fk_push_endpoints_installation_id
    FOREIGN KEY (installation_id) REFERENCES identity.installations (id),
  CONSTRAINT fk_push_endpoints_user_id FOREIGN KEY (user_id) REFERENCES identity.users (id),
  CONSTRAINT uq_push_endpoints_provider_token UNIQUE (provider, token),
  CONSTRAINT ck_push_endpoints_provider CHECK (provider IN ('fcm','apns')),
  CONSTRAINT ck_push_endpoints_status CHECK (status IN ('active','invalid','revoked')),
  CONSTRAINT ck_push_endpoints_token_len CHECK (char_length(token) BETWEEN 16 AND 4096)
);
CREATE INDEX ix_push_endpoints_installation_id ON identity.push_endpoints (installation_id) WHERE status = 'active';
CREATE INDEX ix_push_endpoints_user_id ON identity.push_endpoints (user_id) WHERE user_id IS NOT NULL;
CREATE TRIGGER trg_push_endpoints_touch BEFORE UPDATE ON identity.push_endpoints
  FOR EACH ROW EXECUTE FUNCTION ops.touch_updated_at();

CREATE TABLE identity.platform_permissions (
  id                 uuid        NOT NULL DEFAULT gen_random_uuid(),
  user_id            uuid        NOT NULL,
  permission_code    text        NOT NULL,
  granted_by_user_id uuid,
  granted_at         timestamptz NOT NULL DEFAULT now(),
  revoked_at         timestamptz,
  CONSTRAINT pk_platform_permissions PRIMARY KEY (id),
  CONSTRAINT fk_platform_permissions_user_id FOREIGN KEY (user_id) REFERENCES identity.users (id),
  CONSTRAINT fk_platform_permissions_granted_by
    FOREIGN KEY (granted_by_user_id) REFERENCES identity.users (id),
  CONSTRAINT ck_platform_permissions_code CHECK (permission_code IN
    ('incident.view','incident.assess','incident.verify','incident.correct','incident.merge',
     'report.review','reporter_identity.view','evidence.view_restricted',
     'alert.issue','alert.withdraw','disclosure_policy.manage','platform.admin')),
  CONSTRAINT ck_platform_permissions_revoked CHECK (revoked_at IS NULL OR revoked_at >= granted_at),
  CONSTRAINT ck_platform_permissions_not_self_granted CHECK (granted_by_user_id IS DISTINCT FROM user_id)
);
CREATE UNIQUE INDEX uq_platform_permissions_active
  ON identity.platform_permissions (user_id, permission_code) WHERE revoked_at IS NULL;
