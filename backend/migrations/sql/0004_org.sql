-- 0004_org: organizations, memberships, per-action permissions (DB spec 4.3)
CREATE TABLE org.organizations (
  id                uuid        NOT NULL DEFAULT gen_random_uuid(),
  name              citext      NOT NULL,
  organization_type text        NOT NULL,
  status            text        NOT NULL DEFAULT 'pending',
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_organizations PRIMARY KEY (id),
  CONSTRAINT uq_organizations_name UNIQUE (name),
  CONSTRAINT ck_organizations_type CHECK (organization_type IN
    ('humanitarian_ngo','un_agency','government','research')),
  CONSTRAINT ck_organizations_status CHECK (status IN ('pending','active','suspended','closed'))
);
CREATE TRIGGER trg_organizations_touch BEFORE UPDATE ON org.organizations
  FOR EACH ROW EXECUTE FUNCTION ops.touch_updated_at();

CREATE TABLE org.organization_memberships (
  id              uuid        NOT NULL DEFAULT gen_random_uuid(),
  organization_id uuid        NOT NULL,
  user_id         uuid        NOT NULL,
  role_bundle     text        NOT NULL DEFAULT 'custom',
  status          text        NOT NULL DEFAULT 'invited',
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pk_organization_memberships PRIMARY KEY (id),
  CONSTRAINT fk_organization_memberships_organization_id
    FOREIGN KEY (organization_id) REFERENCES org.organizations (id),
  CONSTRAINT fk_organization_memberships_user_id FOREIGN KEY (user_id) REFERENCES identity.users (id),
  CONSTRAINT uq_organization_memberships_org_user UNIQUE (organization_id, user_id),
  CONSTRAINT ck_organization_memberships_role_bundle CHECK (role_bundle IN
    ('org_admin','reviewer','analyst','viewer','custom')),
  CONSTRAINT ck_organization_memberships_status CHECK (status IN ('invited','active','suspended','revoked'))
);
CREATE INDEX ix_organization_memberships_user_id ON org.organization_memberships (user_id) WHERE status = 'active';
CREATE TRIGGER trg_organization_memberships_touch BEFORE UPDATE ON org.organization_memberships
  FOR EACH ROW EXECUTE FUNCTION ops.touch_updated_at();

CREATE TABLE org.membership_permissions (
  id                 uuid        NOT NULL DEFAULT gen_random_uuid(),
  membership_id      uuid        NOT NULL,
  permission_code    text        NOT NULL,
  granted_by_user_id uuid        NOT NULL,
  granted_at         timestamptz NOT NULL DEFAULT now(),
  revoked_at         timestamptz,
  CONSTRAINT pk_membership_permissions PRIMARY KEY (id),
  CONSTRAINT fk_membership_permissions_membership_id
    FOREIGN KEY (membership_id) REFERENCES org.organization_memberships (id),
  CONSTRAINT fk_membership_permissions_granted_by
    FOREIGN KEY (granted_by_user_id) REFERENCES identity.users (id),
  CONSTRAINT ck_membership_permissions_code CHECK (permission_code IN
    ('incident.view','incident.assess','incident.verify','incident.correct','incident.merge',
     'humanitarian.view','humanitarian.manage','org.manage_members')),
  CONSTRAINT ck_membership_permissions_revoked CHECK (revoked_at IS NULL OR revoked_at >= granted_at)
);
CREATE UNIQUE INDEX uq_membership_permissions_active
  ON org.membership_permissions (membership_id, permission_code) WHERE revoked_at IS NULL;
