-- 0001_foundation: extensions, schemas, shared functions (DB spec 11.1)
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE SCHEMA ref;
CREATE SCHEMA identity;
CREATE SCHEMA org;
CREATE SCHEMA ops;
CREATE SCHEMA incident;
CREATE SCHEMA reporting;
CREATE SCHEMA review;
CREATE SCHEMA disclosure;
CREATE SCHEMA subscription;
CREATE SCHEMA alerting;
CREATE SCHEMA humanitarian;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE FUNCTION ops.touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;

CREATE FUNCTION ops.severity_rank(s text) RETURNS smallint
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
  SELECT CASE s WHEN 'unknown' THEN 0 WHEN 'low' THEN 1 WHEN 'moderate' THEN 2
                WHEN 'high' THEN 3 WHEN 'critical' THEN 4 END::smallint
$$;
