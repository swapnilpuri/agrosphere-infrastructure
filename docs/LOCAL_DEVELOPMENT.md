# Local development

Use PowerShell in C:\Projects\agrosphere\agrosphere-infrastructure. Docker Desktop must run Linux containers. Install Python 3.12+; independent builds require Java 25 for Gateway/Estate and Java 21 for Spatial, or use their Dockerfiles.

~~~powershell
Set-Location C:\Projects\agrosphere\agrosphere-infrastructure
python scripts/init_local.py
python -m pip install -r requirements-test.txt
docker compose --profile apps up -d --build --wait --wait-timeout 240
python scripts/configure_identity.py
python scripts/dev_identity.py
python scripts/smoke_platform.py --faults
~~~

init_local.py refuses to overwrite .env. On subsequent runs, omit that command. No persistent volumes or developer data are deleted. The schema upgrade is additive: each service applies its own V3 outbox trace metadata migration, preserving V1/V2 and all existing rows. Never use the PostgreSQL administrator credentials in application processes.

Generated local users are dev-admin, dev-manager, dev-viewer and dev-outsider. Their random passwords are in ignored local-secrets/dev-users.json; the helper never resets a preexisting user's password. Only dev-admin has PLATFORM_ADMIN. The integration suite assigns its new estate UUID to manager/viewer; the outsider retains no estate access. Use these users in the Keycloak account/login UI. Browser clients use Authorization Code + PKCE S256. scripts/dev_identity.py contains a real PKCE flow; no password-grant browser client or client secret exists. The loopback HTTP test client models Chromium's trustworthy-localhost cookie behavior without relaxing remote-cookie or JWT checks.

The Estate contract requires PLATFORM_ADMIN to create an estate/clone. Integration authenticates a manager first and proves that it cannot create a global estate; the administrator bootstraps the estate, then the assigned ESTATE_MANAGER owns the remaining workflow. This preserves the existing authorization contract.

To run only backing infrastructure:

~~~powershell
docker compose --profile identity --profile observability up -d --build --wait
~~~

Export each service's documented DB/OIDC/Rabbit variables when running Java from VS Code. Spring does not automatically load .env. The existing shared PostgreSQL server exposes separate estate/spatial databases on loopback 5432. For host execution use the public issuer and public JWKS; containers use the same issuer with internal JWKS DNS. See ENVIRONMENT_CONFIGURATION.md.

~~~powershell
# Stop without deleting data:
docker compose --profile apps down
# Rebuild only the service being changed:
docker compose --profile apps build estate
docker compose --profile apps up -d --no-deps --wait estate
# Export authenticated API descriptions without exposing backend ports:
python scripts/export_openapi.py
code target/estate.openapi.json
code target/spatial.openapi.json
~~~

OpenAPI may be imported into an API client. Business routes are at http://localhost:8080/api/v1; the internal Swagger/OpenAPI endpoints require a JWT and are not publicly proxied. Keycloak: http://localhost:8180/admin/; RabbitMQ: http://localhost:15672; Jaeger: http://localhost:16686. Bootstrap identity login is agrosphere_admin with KEYCLOAK_ADMIN_PASSWORD from private .env. RabbitMQ login is agrosphere with its private .env password. Never paste these values into committed examples or logs.

## Clean rebuild and safe reset procedure

A clean image rebuild preserves all data:

~~~powershell
docker compose --profile apps down
docker compose --profile apps build --no-cache
docker compose --profile apps up -d --wait --wait-timeout 240
~~~

No reset script is supplied. For a new empty sandbox without deleting any developer data, select a new project name and generate a separate private environment; first stop the original stack to free loopback ports. Keep credentials paired with their project. Returning to the original project restores its existing named volumes. Before any true reset, explicitly approve the specific database/volume deletion, stop services, take verified backups and identify exactly the project-owned volumes. Changing .env passwords does not rotate initialized credentials. Never use down --volumes as a routine rebuild command.

The local-only cookie policy matches Chromium behavior for Secure cookies on loopback HTTP; normal Secure-cookie restrictions remain elsewhere. See the [HTTP Working Group localhost discussion](https://github.com/httpwg/http-extensions/issues/2605). Use HTTPS when testing clients outside this local context.
