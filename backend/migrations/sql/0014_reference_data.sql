-- 0014_reference_data: disclosure policies, categories, compatibility (DB spec 10.3, 11.7)
-- Idempotent: safe to re-run.
INSERT INTO ref.disclosure_policies
  (code, version, public_grid_m, min_alert_radius_m, publish_description,
   review_before_publish, public_delay, max_public_age, status)
VALUES
  ('standard',  1,  250,  500, true,  false, interval '0',          interval '7 days', 'active'),
  ('security',  1,  500, 1000, false, false, interval '0',          interval '3 days', 'active'),
  ('sensitive', 1, 2000, 3000, false, false, interval '30 minutes', interval '3 days', 'active'),
  ('protected', 1, 5000, 5000, false, true,  interval '2 hours',    interval '3 days', 'active')
ON CONFLICT (code, version) DO NOTHING;

-- The first 8 rows come from the DB spec. The last 7 are API-contract codes whose policy and
-- matching parameters are PROPOSED and must be reviewed with field and protection specialists.
INSERT INTO ref.incident_categories
  (code, name, disclosure_policy_id, is_sensitive, match_radius_m, match_time_window, default_severity)
SELECT v.code, v.name, p.id, v.sensitive, v.radius, v.win, v.sev
FROM (VALUES
  ('shooting',                 'Shooting',                 'security',  false,  750, interval '3 hours',  'high'),
  ('armed_clash',              'Armed clash',              'sensitive', true,  2000, interval '12 hours', 'critical'),
  ('kidnapping',               'Kidnapping',               'protected', true,  1500, interval '24 hours', 'critical'),
  ('missing_person',           'Missing person',           'protected', true,  3000, interval '72 hours', 'high'),
  ('road_accident',            'Road accident',            'standard',  false,  300, interval '2 hours',  'moderate'),
  ('flood',                    'Flood',                    'standard',  false, 3000, interval '48 hours', 'high'),
  ('fire',                     'Fire',                     'standard',  false,  500, interval '6 hours',  'high'),
  ('infrastructure_emergency', 'Infrastructure emergency', 'standard',  false, 1000, interval '24 hours', 'moderate'),
  ('explosion',                'Explosion',                'security',  false, 1000, interval '6 hours',  'high'),
  ('road_blockage',            'Road blockage',            'security',  false, 1000, interval '12 hours', 'moderate'),
  ('building_collapse',        'Building collapse',        'standard',  false,  300, interval '24 hours', 'high'),
  ('landslide',                'Landslide',                'standard',  false, 2000, interval '48 hours', 'high'),
  ('medical_emergency',        'Medical emergency',        'security',  false,  300, interval '3 hours',  'moderate'),
  ('displacement',             'Displacement',             'sensitive', true,  5000, interval '72 hours', 'high'),
  ('other',                    'Other',                    'security',  false,  500, interval '6 hours',  'moderate')
) AS v(code, name, policy, sensitive, radius, win, sev)
JOIN ref.disclosure_policies p ON p.code = v.policy AND p.version = 1
ON CONFLICT (code) DO NOTHING;

INSERT INTO ref.category_compatibility (category_id, compatible_category_id, weight)
SELECT pair.x, pair.y, v.w
FROM (VALUES ('shooting','armed_clash',0.80), ('kidnapping','missing_person',0.60),
             ('fire','infrastructure_emergency',0.50), ('flood','infrastructure_emergency',0.50),
             ('explosion','armed_clash',0.70), ('explosion','fire',0.50),
             ('flood','landslide',0.50), ('building_collapse','infrastructure_emergency',0.60)
     ) AS v(a, b, w)
JOIN ref.incident_categories ca ON ca.code = v.a
JOIN ref.incident_categories cb ON cb.code = v.b
CROSS JOIN LATERAL (VALUES (ca.id, cb.id), (cb.id, ca.id)) AS pair(x, y)
ON CONFLICT DO NOTHING;
