-- 0016_operational_assessment: record "is it still going on?" decisions as assessments.
-- Operational status is set by reviewers with a reason (UC-06), and the append-only assessments table
-- is where such decisions live. 'merged' and 'withdrawn' are not assessments: merge has its own
-- workflow and relationship row.
ALTER TABLE incident.incident_assessments DROP CONSTRAINT ck_incident_assessments_value;
ALTER TABLE incident.incident_assessments ADD CONSTRAINT ck_incident_assessments_value CHECK (
     (assessment_type = 'severity'     AND assessment_value IN ('unknown','low','moderate','high','critical'))
  OR (assessment_type = 'confidence'   AND assessment_value IN ('low','medium','high'))
  OR (assessment_type = 'freshness'    AND assessment_value IN ('current','aging','stale','expired'))
  OR (assessment_type = 'verification' AND assessment_value IN
       ('unverified','under_review','verified','disputed','rejected'))
  OR (assessment_type = 'operational'  AND assessment_value IN ('active','monitoring','resolved','closed')));
