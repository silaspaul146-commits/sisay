-- 0013_guards_and_grants: report immutability, association consistency, privileged functions, grants
-- (DB spec 11.4, 11.5, 11.6, 9.2)

-- Original submission fields are immutable, except through redaction (DB spec 9.1).
CREATE FUNCTION reporting.protect_report_original() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.category_id         <> OLD.category_id
  OR NEW.location_source     <> OLD.location_source
  OR NEW.observed_at         <> OLD.observed_at
  OR NEW.received_at         <> OLD.received_at
  OR NEW.client_created_at   IS DISTINCT FROM OLD.client_created_at
  OR NEW.public_reference    <> OLD.public_reference
  OR NEW.idempotency_scope   <> OLD.idempotency_scope
  OR NEW.idempotency_key     <> OLD.idempotency_key
  OR NEW.request_fingerprint <> OLD.request_fingerprint
  OR (OLD.redacted_at IS NOT NULL AND NEW.redacted_at IS DISTINCT FROM OLD.redacted_at) THEN
    RAISE EXCEPTION 'report %: original submission fields are immutable', OLD.id
      USING ERRCODE = 'check_violation';
  END IF;
  -- Redactable fields may change only in the statement that first sets redacted_at
  IF NOT (OLD.redacted_at IS NULL AND NEW.redacted_at IS NOT NULL) AND (
       NEW.description IS DISTINCT FROM OLD.description
    OR NEW.location_accuracy_m <> OLD.location_accuracy_m
    OR NOT ST_Equals(NEW.incident_location::geometry, OLD.incident_location::geometry)
    OR NEW.redacted_at IS DISTINCT FROM OLD.redacted_at) THEN
    RAISE EXCEPTION 'report %: original submission fields are immutable', OLD.id
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_reports_protect_original BEFORE UPDATE ON reporting.reports
  FOR EACH ROW EXECUTE FUNCTION reporting.protect_report_original();

-- Every change of reports.incident_id must have a matching history row in the same transaction.
CREATE FUNCTION reporting.check_association_history() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  prev uuid := CASE WHEN TG_OP = 'UPDATE' THEN OLD.incident_id END;
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM   reporting.report_association_history h
    WHERE  h.report_id = NEW.id
      AND  h.previous_incident_id IS NOT DISTINCT FROM prev
      AND  h.new_incident_id      IS NOT DISTINCT FROM NEW.incident_id
      AND  h.created_at = now())
  THEN
    RAISE EXCEPTION 'report %: incident association changed without history', NEW.id
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER trg_reports_association_history_upd
  AFTER UPDATE OF incident_id ON reporting.reports
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
  WHEN (OLD.incident_id IS DISTINCT FROM NEW.incident_id)
  EXECUTE FUNCTION reporting.check_association_history();
CREATE CONSTRAINT TRIGGER trg_reports_association_history_ins
  AFTER INSERT ON reporting.reports
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
  WHEN (NEW.incident_id IS NOT NULL)
  EXECUTE FUNCTION reporting.check_association_history();

-- Audited, policy-driven redaction: the only path that may change original report fields.
CREATE FUNCTION reporting.redact_report(p_report_id uuid, p_reason text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
BEGIN
  UPDATE reporting.reports
  SET    redacted_at         = now(),
         description         = NULL,
         incident_location   = disclosure.snap_public_point(incident_location, 1000),
         location_accuracy_m = GREATEST(location_accuracy_m, 1000)
  WHERE  id = p_report_id AND redacted_at IS NULL;
  IF NOT FOUND THEN RETURN; END IF;

  UPDATE reporting.report_access_credentials
  SET    revoked_at = now()
  WHERE  report_id = p_report_id AND revoked_at IS NULL;

  UPDATE reporting.report_submitters
  SET    user_id = NULL, installation_id = NULL, identity_purged_at = now()
  WHERE  report_id = p_report_id;

  INSERT INTO ops.outbox_events (aggregate_type, aggregate_id, event_type, payload)
  VALUES ('report', p_report_id, 'evidence.purge_requested', jsonb_build_object('report_id', p_report_id));

  INSERT INTO ops.audit_logs (actor_type, action, resource_type, resource_id, metadata)
  VALUES ('worker', 'report.redact', 'report', p_report_id, jsonb_build_object('reason', p_reason));
END $$;

-- Reporter identity is readable only through this audited checkpoint.
CREATE FUNCTION reporting.get_report_submitter(
  p_report_id uuid, p_actor_id uuid, p_organization_id uuid, p_reason text)
RETURNS TABLE (submitter_user_id uuid, submitter_installation_id uuid, submitter_organization_id uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM   identity.platform_permissions pp
    WHERE  pp.user_id = p_actor_id
      AND  pp.permission_code = 'reporter_identity.view'
      AND  pp.revoked_at IS NULL)
  THEN
    RAISE EXCEPTION 'not authorized' USING ERRCODE = 'insufficient_privilege';
  END IF;

  INSERT INTO ops.audit_logs (actor_id, actor_type, organization_id, action, resource_type, resource_id, metadata)
  VALUES (p_actor_id, 'user', p_organization_id, 'reporter_identity.access', 'report', p_report_id,
          jsonb_build_object('reason', p_reason));

  RETURN QUERY
    SELECT s.user_id, s.installation_id, s.organization_id
    FROM   reporting.report_submitters s
    WHERE  s.report_id = p_report_id;
END $$;

REVOKE EXECUTE ON FUNCTION reporting.redact_report(uuid, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION reporting.get_report_submitter(uuid, uuid, uuid, text) FROM PUBLIC;

-- Grants live in grants.sql so they can be re-applied after roles are created (python -m app.manage).
