-- 0005_ops: transactional outbox and audit log (DB spec 4.11, 11.2)
CREATE TABLE ops.outbox_events (
  id             uuid        NOT NULL DEFAULT gen_random_uuid(),
  sequence       bigint      GENERATED ALWAYS AS IDENTITY,
  aggregate_type text        NOT NULL,
  aggregate_id   uuid        NOT NULL,
  event_type     text        NOT NULL,
  event_version  smallint    NOT NULL DEFAULT 1,
  payload        jsonb       NOT NULL,
  status         text        NOT NULL DEFAULT 'pending',
  attempts       smallint    NOT NULL DEFAULT 0,
  available_at   timestamptz NOT NULL DEFAULT now(),
  locked_by      text,
  locked_until   timestamptz,
  last_error     text,
  created_at     timestamptz NOT NULL DEFAULT now(),
  processed_at   timestamptz,
  CONSTRAINT pk_outbox_events PRIMARY KEY (id),
  CONSTRAINT uq_outbox_events_sequence UNIQUE (sequence),
  CONSTRAINT ck_outbox_events_status CHECK (status IN ('pending','processing','processed','dead')),
  CONSTRAINT ck_outbox_events_type CHECK (event_type ~ '^[a-z_]+\.[a-z_]+$'),
  CONSTRAINT ck_outbox_events_attempts CHECK (attempts BETWEEN 0 AND 50),
  CONSTRAINT ck_outbox_events_processed CHECK ((status = 'processed') = (processed_at IS NOT NULL)),
  CONSTRAINT ck_outbox_events_lock CHECK (status <> 'processing' OR locked_until IS NOT NULL),
  CONSTRAINT ck_outbox_events_payload_size CHECK (pg_column_size(payload) <= 65536)
);
CREATE INDEX ix_outbox_events_claim ON ops.outbox_events (available_at, sequence)
  WHERE status IN ('pending','processing');
CREATE INDEX ix_outbox_events_aggregate ON ops.outbox_events (aggregate_type, aggregate_id, sequence);
CREATE INDEX ix_outbox_events_processed_at ON ops.outbox_events (processed_at) WHERE status = 'processed';

CREATE FUNCTION ops.notify_outbox() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM pg_notify('outbox', '');
  RETURN NULL;
END $$;
CREATE TRIGGER trg_outbox_notify AFTER INSERT ON ops.outbox_events
  FOR EACH STATEMENT EXECUTE FUNCTION ops.notify_outbox();

CREATE TABLE ops.audit_logs (
  id              uuid        NOT NULL DEFAULT gen_random_uuid(),
  occurred_at     timestamptz NOT NULL DEFAULT now(),
  actor_id        uuid,
  actor_type      text        NOT NULL,
  organization_id uuid,
  action          text        NOT NULL,
  resource_type   text        NOT NULL,
  resource_id     uuid        NOT NULL,
  request_id      uuid,
  metadata        jsonb       NOT NULL DEFAULT '{}',
  CONSTRAINT pk_audit_logs PRIMARY KEY (id),
  CONSTRAINT fk_audit_logs_actor_id FOREIGN KEY (actor_id) REFERENCES identity.users (id),
  CONSTRAINT fk_audit_logs_organization_id FOREIGN KEY (organization_id) REFERENCES org.organizations (id),
  CONSTRAINT ck_audit_logs_actor_type CHECK (actor_type IN ('user','system','worker','anonymous_token')),
  CONSTRAINT ck_audit_logs_actor CHECK ((actor_type = 'user') = (actor_id IS NOT NULL)),
  CONSTRAINT ck_audit_logs_action CHECK (action ~ '^[a-z_]+\.[a-z_]+$')
);
CREATE INDEX ix_audit_logs_resource ON ops.audit_logs (resource_type, resource_id, occurred_at);
CREATE INDEX ix_audit_logs_actor ON ops.audit_logs (actor_id, occurred_at) WHERE actor_id IS NOT NULL;
CREATE INDEX bx_audit_logs_occurred_at ON ops.audit_logs USING brin (occurred_at);
