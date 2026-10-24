#!/usr/bin/env bash
set -euo pipefail
# Fresh-volume bootstrap only. Never use the admin role in applications.
for service in estate spatial operations telemetry analytics ai keycloak; do
  password_var="${service^^}_DB_PASSWORD"
  password="${!password_var}"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres --set=role="agrosphere_$service" --set=password="$password" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', :'role', :'password') \gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'role', :'role') \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'role') \gexec
SQL
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "agrosphere_$service" --set=role="agrosphere_$service" <<'SQL'
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SELECT format('GRANT ALL ON SCHEMA public TO %I', :'role') \gexec
SQL
done
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname agrosphere_spatial -c 'CREATE EXTENSION IF NOT EXISTS postgis;'
