-- Operator-controlled Operations-only provisioning; no password arguments/output.
-- Existing roles are validated, never silently repaired or password-rotated.
\set ON_ERROR_STOP on
\getenv runtime_password OPERATIONS_APP_DB_PASSWORD
\getenv owner_password OPERATIONS_DB_PASSWORD
SELECT current_database()='agrosphere_operations' AS correct_database \gset
\if :correct_database
\else
 DO $$ BEGIN RAISE EXCEPTION 'Refusing provisioning outside the Operations database'; END $$;
\endif
\if :{?runtime_password}
 SELECT length(:'runtime_password')>=16 AND :'runtime_password' NOT LIKE '%REPLACE%' AS password_valid \gset
 \if :password_valid
 \else
  DO $$ BEGIN RAISE EXCEPTION 'A generated private runtime password of at least 16 characters is required'; END $$;
 \endif
\else
 DO $$ BEGIN RAISE EXCEPTION 'OPERATIONS_APP_DB_PASSWORD is required in the process environment'; END $$;
\endif
\if :{?owner_password}
 SELECT :'owner_password'<>:'runtime_password' AS distinct_passwords \gset
 \if :distinct_passwords
 \else
  DO $$ BEGIN RAISE EXCEPTION 'Runtime and migration-owner credentials must be distinct'; END $$;
 \endif
\else
 DO $$ BEGIN RAISE EXCEPTION 'Supply migration-owner credentials privately for distinctness validation'; END $$;
\endif
BEGIN;
SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='agrosphere_operations_app') AS runtime_exists \gset
\if :runtime_exists
 SELECT NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='agrosphere_operations_app'
   AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
   AND NOT EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname='agrosphere_operations_app')
   AND NOT EXISTS(SELECT 1 FROM pg_database d JOIN pg_roles r ON r.oid=d.datdba WHERE r.rolname='agrosphere_operations_app')
   AND NOT EXISTS(SELECT 1 FROM pg_namespace n JOIN pg_roles r ON r.oid=n.nspowner WHERE r.rolname='agrosphere_operations_app')
   AS role_safe \gset
 \if :role_safe
 \else
  DO $$ BEGIN RAISE EXCEPTION 'Existing runtime role is unsafe; explicit operator review is required'; END $$;
 \endif
\else
 SELECT format('CREATE ROLE agrosphere_operations_app LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS', :'runtime_password') \gexec
\endif
GRANT CONNECT ON DATABASE agrosphere_operations TO agrosphere_operations_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO agrosphere_operations_app;
COMMIT;
\unset runtime_password
\unset owner_password
