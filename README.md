# AgroSphere local platform

Milestone 1C, infrastructure release 0.2.0. This independent repository orchestrates Gateway 0.2.0, Estate 0.2.1 and Spatial 0.2.1. Estate retains Java 25; Spatial retains Java 21; both use Boot 4.0.9. Each application keeps its own build, Dockerfile, migrations, tests, CI and release version. No parent build, Git repository, submodules or shared persistence models are introduced.

## Start locally

Requires Docker Compose v2/Linux containers and Python 3.12+. Run from this directory. Local source builds expect the three existing sibling repositories; released-image operation needs no sibling sources.

~~~powershell
python scripts/init_local.py
python -m pip install -r requirements-test.txt
python scripts/validate.py
docker compose --profile apps up -d --build --wait --wait-timeout 240
python scripts/configure_identity.py
python scripts/smoke_platform.py --faults
~~~

init_local.py creates an ignored .env with distinct random passwords, refuses to overwrite an existing file and never prints credentials. Alternatively copy .env.example and replace every placeholder. Existing credentials must match initialized database/broker/Keycloak volumes; changing .env does not rotate stored credentials. Keep .env private.

The smoke script creates uniquely named SIMULATED estates/divisions/blocks/clones/geometry, deletes its temporary confidential clients, and preserves database records for inspection. --faults briefly stops/restarts Estate and RabbitMQ in this Compose project; omit it to avoid intentional outages. Results and canonical IDs are written to ignored target/platform-smoke.json. It verifies actual response/event contracts, JWT/role/estate scope, database isolation, idempotency, trace continuity and outage recovery. It needs the local administrator password from .env; credentials/tokens are never logged. Use the default documented ports for the test script.

## Profiles, health and independent images

Default: postgres, rabbitmq and the one-shot rabbitmq-init topology importer. --profile identity adds Keycloak. --profile observability adds Collector and Jaeger. --profile apps adds all three applications and their identity/observability dependencies. --profile iot retains authenticated Mosquitto; provision local-secrets/mosquitto.passwd first. Explicit service targets can be supplied to Compose. Startup uses health checks and topology-import completion, with Spatial healthy before the Estate publisher starts. Runtime outages do not require dependent-container restarts: outbox and consumer retries recover independently.

~~~powershell
# Infrastructure and host-run applications:
docker compose --profile identity --profile observability up -d --build --wait
# Use independently built/pulled application releases:
# Set GATEWAY_IMAGE, ESTATE_IMAGE and SPATIAL_IMAGE to desired tags or digests.
docker compose --profile apps build jaeger otel-collector
docker compose --profile apps up -d --no-build --wait --wait-timeout 240
# Preserve all volumes when stopping:
docker compose --profile apps down
~~~

Do not delete populated volumes to upgrade. postgres/init.sh remains the original fresh-volume bootstrap. Service-owned Flyway migrations remain exclusively in the Estate/Spatial repositories; no migration was changed for 1C. Separate databases and non-superuser roles on the existing server enforce ownership, with PUBLIC CONNECT revoked. Acceptance tests verify each application's credentials cannot connect to the other database. Existing installations must already have the M0 database-role bootstrap; back up and repair missing grants explicitly rather than reinitializing data.

## Ports

| Host loopback port | Purpose |
|---|---|
| 8080 | Gateway; all public business APIs |
| 8180 | Keycloak OIDC/admin console |
| 5432 | PostgreSQL for independent host development |
| 5672 / 15672 | RabbitMQ AMQP / development management API |
| 4317 / 4318 | Collector OTLP gRPC / HTTP for host development |
| 16686 | Jaeger UI and query API |
| 1883 | Optional MQTT with iot profile |

Estate 8081, Spatial 8082, Collector health 13133, Jaeger admin 14269 and Keycloak management 9000 are internal only. Network is explicitly named agrosphere-local-dev (or COMPOSE_PROJECT_NAME + -dev). No service-discovery server is required; Compose DNS supplies names.

## Configuration

.env.example is the central development configuration. Required private values: POSTGRES_ADMIN_PASSWORD; ESTATE_DB_PASSWORD, SPATIAL_DB_PASSWORD, OPERATIONS_DB_PASSWORD, TELEMETRY_DB_PASSWORD, ANALYTICS_DB_PASSWORD, AI_DB_PASSWORD and KEYCLOAK_DB_PASSWORD (existing bootstrap creates seven databases); RABBITMQ_PASSWORD; KEYCLOAK_ADMIN_PASSWORD. The administrator accounts are infrastructure-only; application containers receive only their own DB password and broker credentials.

| Variable | Default / behavior |
|---|---|
| OIDC_PUBLIC_URL | http://localhost:8180; exact advertised Keycloak base URL |
| CORS_ALLOWED_ORIGINS | http://localhost:4200; comma-separated exact Angular origins |
| GATEWAY_CONNECT_TIMEOUT / GATEWAY_READ_TIMEOUT | 2s / 10s; positive Java durations |
| GATEWAY_RATE_LIMIT | 120 authenticated API requests per subject per minute, per gateway process |
| TRACING_SAMPLE_PROBABILITY | 1.0 in local platform; standalone services retain 0.1 |
| GATEWAY_IMAGE / ESTATE_IMAGE / SPATIAL_IMAGE | 0.2.0 / 0.2.1 / 0.2.1 repository-specific local image tags |
| COMPOSE_PROJECT_NAME | agrosphere-local; also controls development network name |

Application DB_URL/DB_USER/DB_PASSWORD and RabbitMQ address/credentials are injected per service. Publication and Spatial's Estate consumer are enabled. Estate event provenance is SIMULATED in this development stack. Every service validates its own audience: agrosphere-api, estate-service, spatial-service. OIDC_JWK_SET_URI uses internal Keycloak DNS while OIDC_ISSUER_URI uses the exact public issuer; signature, issuer, audience and lifetime checks remain enabled. Standalone service discovery remains the default when OIDC_JWK_SET_URI is absent. Applications receive the collector HTTP traces endpoint via MANAGEMENT_OPENTELEMETRY_TRACING_EXPORT_OTLP_ENDPOINT. See service READMEs for standalone variables and limits.

## Identity

Keycloak imports keycloak/agrosphere-realm.json only for a new realm. scripts/configure_identity.py idempotently applies the reviewed scope mappers and administrator-only estate_ids profile to an existing imported realm; it does not delete users. Realm import/configuration is local development only. No users, passwords or client secrets are bundled. Log into the admin console using agrosphere_admin and the private bootstrap password. Create developer users, set their passwords, assign trusted realm roles, and administer the multivalued estate_ids attribute with canonical Estate UUIDs. PLATFORM_ADMIN can create estates and clones; ESTATE_ADMIN/ESTATE_MANAGER write assigned estates; VIEWER reads assigned estates; Spatial additionally supports read-only AGRONOMIST. estate_ids is not editable by end users.

agrosphere-web is a public Authorization Code client with mandatory PKCE S256, redirect http://localhost:4200/* and exact web origin. Password grants are disabled. The agrosphere-api scope adds the three required audiences, trusted realm roles and estate_ids. The smoke test alone creates short-lived confidential service-account clients and removes them. Do not create an Angular client secret.

Local HTTP is bound to loopback; there are no repository certificates to reuse. Configure HTTPS and trusted certificates before exposing this stack beyond the workstation. Issuer changes require matching token issuer configuration; changing a JWKS address alone does not change the issuer.

## Events, tracing and recovery

Estate publishes existing v2 snapshots to agrosphere.domain. Spatial owns spatial.estate.v2 and spatial.estate.v2.dead, uses transactionally deduplicated projections, three bounded delivery attempts and its existing DLQ. Estate's confirmed mandatory outbox cannot start before Spatial has declared its consumer queue. rabbitmq-init imports durable spatial v1 diagnostic bindings after broker/user initialization, so Spatial publication has an actual route. agrosphere.dev.spatial.v1 is a local diagnostic sink capped at 10,000 messages; oldest entries may be discarded. It is not a production consumer or indefinite archive. Existing outboxes preserve pending rows during outages and retain exhausted FAILED rows. Replay and DLQ guidance remain in the owning services; never delete processed-event markers to replay duplicates blindly.

W3C HTTP trace context flows through the gateway's observed RestClient into either service and then Collector -> Jaeger. Jaeger uses bounded in-memory storage and loses traces on restart. Async outbox delivery retains event correlationId; this milestone does not claim parent-child trace continuity across the asynchronous relay. Collector exports traces only; no retained metrics/log backend is configured. Application structured JSON logs include correlation/trace IDs. Gateway access logs omit query strings, bearer tokens and bodies. Health/readiness and service logs support diagnosis; no retention, backup SLA or production deployment is claimed.

## Validation and CI

~~~powershell
python scripts/validate.py
docker compose --env-file .env.example --profile apps --profile iot config --quiet
# With Bash available:
bash -n postgres/init.sh
# With the local platform running:
python scripts/smoke_platform.py --faults
~~~

Pinned response/event snapshots under tests/contracts are from contracts release 0.3.0 (Estate API/events retain 0.2.0 semantics); SHA-256 manifest guards accidental drift. No runtime/build dependency reads sibling contracts. Each Java repository runs its own Maven/JWT/integration/contract checks. CI validates infrastructure and builds the two observability images. The manually dispatched platform workflow takes independently published application image references and runs acceptance without sibling checkouts. Registry images/remotes were not published or created here. See docs/MILESTONE_1C_REPORT.md for actual local results, baseline evidence, repository changes and limitations.
