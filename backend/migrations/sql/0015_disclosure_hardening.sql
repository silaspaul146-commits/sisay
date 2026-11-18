-- 0015_disclosure_hardening: fixes found in the 2026-11-18 review.

-- 1. The removals feed listed every projection that is not currently published, including ones
--    that were never public (e.g. a kidnapping awaiting publication review). Polling it revealed
--    that a hidden incident had just been created. Only incidents that were once published are
--    "removed". Same columns, so existing grants on the view are kept.
CREATE OR REPLACE VIEW disclosure.public_incident_removals_v WITH (security_barrier = true) AS
SELECT p.id AS public_id, p.version, p.generated_at AS removed_at
FROM   disclosure.public_incident_projections p
WHERE  NOT (p.is_visible AND p.publication_state = 'published')
  AND  p.generated_at > now() - interval '7 days'
  AND  EXISTS (SELECT 1 FROM disclosure.public_incident_projection_history h
               WHERE h.incident_id = p.incident_id AND h.is_visible AND h.publication_state = 'published');

-- 2. After SET LOCAL app.organization_id ends, the setting reads '' (not NULL) for the rest of the
--    session, and ''::uuid raises. With pooled connections that broke every later RLS query.
CREATE FUNCTION ops.current_organization_id() RETURNS uuid
LANGUAGE sql STABLE PARALLEL SAFE AS $$
  SELECT NULLIF(current_setting('app.organization_id', true), '')::uuid
$$;

ALTER POLICY hir_org_read ON humanitarian.humanitarian_impact_records
  USING (organization_id = ops.current_organization_id()
         OR sharing_scope = 'platform'
         OR (sharing_scope = 'partners' AND ops.is_partner(organization_id, ops.current_organization_id())));
ALTER POLICY hir_org_write ON humanitarian.humanitarian_impact_records
  WITH CHECK (organization_id = ops.current_organization_id());
