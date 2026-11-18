-- Runtime roles are cluster-wide, so infrastructure creates them before migrations (DB spec 10).
-- DEVELOPMENT PASSWORDS ONLY. Use a secret store and rotate in any shared environment.
CREATE ROLE app_public    LOGIN PASSWORD 'app_public';
CREATE ROLE app_citizen   LOGIN PASSWORD 'app_citizen';
CREATE ROLE app_dashboard LOGIN PASSWORD 'app_dashboard';
CREATE ROLE app_worker    LOGIN PASSWORD 'app_worker';
CREATE ROLE app_analytics LOGIN PASSWORD 'app_analytics';
CREATE DATABASE crisis_test;
