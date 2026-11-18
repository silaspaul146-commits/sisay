-- Re-runnable grants (DB spec 9.2). Applied by migration 0013 and by `python -m app.manage db-roles`.
-- Grants. Runtime roles are cluster-wide and created by infrastructure (infra/db/init) before
-- migrations run. If they do not exist (e.g. a bare local database) grants are skipped with a notice.
DO $grants$
BEGIN
  IF (SELECT count(*) FROM pg_roles
      WHERE rolname IN ('app_public','app_citizen','app_dashboard','app_worker','app_analytics')) < 5 THEN
    RAISE NOTICE 'runtime roles missing: skipping grants (create them, then re-run 0013 grants)';
    RETURN;
  END IF;

  GRANT EXECUTE ON FUNCTION reporting.redact_report(uuid, text) TO app_worker;
  GRANT EXECUTE ON FUNCTION reporting.get_report_submitter(uuid, uuid, uuid, text) TO app_dashboard;

  -- app_public: the two public views and nothing else.
  GRANT USAGE  ON SCHEMA disclosure TO app_public;
  GRANT SELECT ON disclosure.public_incidents_v, disclosure.public_incident_removals_v TO app_public;

  -- app_citizen: submission, credential lookup, own report status.
  GRANT USAGE ON SCHEMA ref, identity, reporting, disclosure, ops TO app_citizen;
  GRANT SELECT ON ref.incident_categories, ref.disclosure_policies TO app_citizen;
  GRANT SELECT, INSERT, UPDATE (last_seen_at, app_version) ON identity.installations TO app_citizen;
  GRANT INSERT, UPDATE (user_id, status, token, updated_at) ON identity.push_endpoints TO app_citizen;
  GRANT SELECT (id, installation_id, user_id, provider, status, last_success_at, created_at, updated_at)
    ON identity.push_endpoints TO app_citizen;
  GRANT SELECT, INSERT ON reporting.reports TO app_citizen;
  GRANT INSERT ON reporting.report_submitters, reporting.report_evidence TO app_citizen;
  GRANT SELECT, INSERT, UPDATE (last_used_at) ON reporting.report_access_credentials TO app_citizen;
  GRANT SELECT (id, report_id, upload_status) ON reporting.report_evidence TO app_citizen;
  GRANT SELECT ON reporting.report_match_decisions, reporting.report_association_history TO app_citizen;
  GRANT SELECT ON disclosure.public_incident_projections, disclosure.public_incidents_v TO app_citizen;
  GRANT INSERT ON ops.audit_logs, ops.outbox_events TO app_citizen;

  -- app_worker: broadest DML, then narrowed.
  GRANT USAGE ON SCHEMA ref, identity, org, ops, incident, reporting, review, disclosure,
                        subscription, alerting, humanitarian TO app_worker;
  GRANT SELECT ON ALL TABLES IN SCHEMA ref, identity, org TO app_worker;
  GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA ops, incident, reporting, review, disclosure,
                                  subscription, alerting TO app_worker;
  GRANT DELETE ON ops.outbox_events, subscription.journey_checks, reporting.report_access_credentials,
                  identity.push_endpoints, alerting.alert_deliveries TO app_worker;
  GRANT UPDATE (status, last_success_at, updated_at) ON identity.push_endpoints TO app_worker;
  REVOKE UPDATE ON reporting.reports FROM app_worker;
  GRANT UPDATE (intake_status, intake_reason, incident_id, updated_at) ON reporting.reports TO app_worker;
  GRANT SELECT ON humanitarian.humanitarian_impact_records TO app_worker;

  -- app_dashboard: incidents, review, alerts, organizations, impact records. No reporter identity.
  GRANT USAGE ON SCHEMA ref, identity, org, ops, incident, reporting, review, disclosure,
                        alerting, humanitarian TO app_dashboard;
  GRANT SELECT ON ALL TABLES IN SCHEMA ref, org, incident, review, disclosure, alerting TO app_dashboard;
  GRANT SELECT ON identity.users, identity.platform_permissions TO app_dashboard;
  GRANT SELECT ON reporting.reports, reporting.report_evidence, reporting.report_match_decisions,
                  reporting.report_match_candidates, reporting.report_association_history TO app_dashboard;
  GRANT UPDATE (intake_status, intake_reason, incident_id, updated_at) ON reporting.reports TO app_dashboard;
  GRANT INSERT ON reporting.report_association_history TO app_dashboard;
  GRANT INSERT, UPDATE ON incident.incidents, review.review_items, alerting.alerts,
                          disclosure.public_incident_projections TO app_dashboard;
  GRANT INSERT ON incident.incident_assessments, incident.incident_corrections,
                  incident.incident_relationships, review.review_notes, alerting.alert_versions,
                  alerting.alert_distribution_decisions TO app_dashboard;
  GRANT INSERT, UPDATE ON org.organizations, org.organization_memberships TO app_dashboard;
  GRANT INSERT, UPDATE (revoked_at) ON org.membership_permissions TO app_dashboard;
  GRANT SELECT, INSERT ON humanitarian.humanitarian_impact_records TO app_dashboard;
  GRANT SELECT, INSERT ON ops.audit_logs TO app_dashboard;
  GRANT INSERT ON ops.outbox_events TO app_dashboard;

  -- app_analytics: incident-level data only.
  GRANT USAGE ON SCHEMA incident, disclosure, humanitarian, ref TO app_analytics;
  GRANT SELECT ON ALL TABLES IN SCHEMA incident, disclosure, humanitarian, ref TO app_analytics;

  -- Append-only tables: no UPDATE or DELETE for any runtime role.
  REVOKE UPDATE, DELETE ON
    reporting.report_association_history, reporting.report_match_decisions,
    reporting.report_match_candidates, incident.incident_assessments, incident.incident_corrections,
    incident.incident_relationships, disclosure.public_incident_projection_history,
    alerting.alert_versions, alerting.alert_distribution_decisions, review.review_notes,
    humanitarian.humanitarian_impact_records, ops.audit_logs
  FROM app_citizen, app_dashboard, app_worker, app_analytics, app_public;
END
$grants$;
