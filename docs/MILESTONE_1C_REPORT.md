# Milestone 1C completion report

Date: 2026-10-24 (America/Chicago).

## Outcome and supplied scope

Locally executable integration is implemented and verified with actual Docker Compose, Keycloak, PostgreSQL/PostGIS, RabbitMQ, Gateway, Estate, Spatial, OpenTelemetry Collector and Jaeger. The platform remains running and healthy at the default loopback ports. Private .env values were generated locally and ignored; no credentials or users were committed. No commits, remotes, pushes, registry publication or cloud deployment were performed. Every repository already contained untracked milestone source at preparation time; existing files and Git roots were preserved rather than reset or replaced.

The supplied attachment is 5,314 characters and ends mid-sentence in section 6: “Configure Keycloak as the local Open”. The missing remainder was requested during work. This implementation fulfills the complete requirements supplied in sections 1–5 and the listed objective, with a reasonable local Keycloak/OIDC integration; unseen acceptance requirements cannot be claimed satisfied.

## Mandatory preparation and baseline

Before editing, read each participating repository's AGENTS/README, all nine existing ADRs, architecture/requirements diagrams and integration rules, Estate/Spatial completion reports, APIs and v2/spatial-v1 event contracts, implementations, environment examples, migrations, Dockerfiles, Compose/overlay definitions and CI. No local certificate files were available to reuse. No deeper AGENTS files applied. The infrastructure had a definition-only M0 stack; the gateway had only four security tests and no real routes. Estate/Spatial had substantial code and prior evidence, which was reverified rather than assumed complete.

| Repository | Baseline actually executed |
|---|---|
| Infrastructure | Existing all-profile Compose config --quiet passed; bootstrap/roles inspected |
| Gateway | Maven verify passed: 4 security tests |
| Estate | Maven verify passed: 38 tests; JDK 25 full verify -Pintegration additionally passed 9 real PostgreSQL/RabbitMQ/HTTP/JWT cases |
| Spatial | Maven verify passed: 19 tests; actual Java 21 container verify -Pintegration additionally passed 12 real PostGIS/RabbitMQ/HTTP/JWT cases |
| Contracts | Existing v1/v2/spatial event examples, negative cases and all OpenAPI validators passed |
| Architecture | Existing nine-ADR source/workflow checks and complete 12-repository workspace audit passed |

Host default Java was 27. Final authoritative gateway and Estate verification used Java 25 (container or explicit JAVA_HOME); Spatial used Java 21 containers. The sandbox shell launcher failed with OS access denied; reviewed local command execution worked, so no checks are marked passed merely from that failed launcher.

## Reused implementation and small integration changes

Reused the existing shared PostgreSQL server with separate owned databases and non-superuser credentials, including existing PostGIS initialization. No Flyway migrations changed. Existing Estate atomic v2 outbox/confirmed publication and Spatial v2 projection/deduplication/revision checks/consumer retry/DLQ/spatial-v1 outbox remain intact. No business service was replaced, duplicated or given another service's tables. Existing API and event schemas remain unchanged in Contracts 0.3.0; infrastructure carries independent SHA-256-pinned acceptance snapshots.

The sole service-code patch in Estate/Spatial is optional internal JWKS URL selection with exact public issuer validation retained. The gateway retains compatible MVC rather than changing framework stacks. The existing service-owned deployment/image/CI lifecycles are preserved. Central Compose build contexts are local orchestration conveniences; independently released application images are also supported.

## Final checks actually executed

| Check | Result |
|---|---|
| Gateway Java 25 Maven/independent Docker verification | PASS: 11 JUnit 5 tests, zero failures/errors/skips; original security tests plus real HTTP and RSA/JWKS integration |
| Estate Java 25 verify -Pintegration | PASS: 38 unit/security and 9 integration tests, zero failures/errors/skips |
| Spatial Java 21 verify -Pintegration | PASS: 19 unit/security and 12 integration tests, zero failures/errors/skips |
| Estate contract validators | PASS: actual exported outbox envelopes; four v2 schema types and 16 runtime/pinned OpenAPI operations |
| Spatial contract validator | PASS: seven actual HTTP response shapes, actual spatial envelopes, synthetic estate snapshots, sample import and runtime OpenAPI |
| All three independently built application images | PASS: Gateway 0.2.0; Estate/Spatial 0.2.1 |
| Observability image builds and health | PASS: Collector 0.135.0 and Jaeger 1.76.0 with pinned BusyBox health probes |
| Spatial packaged-image smoke | PASS: Java 21, nonroot 10001:10001, real PostGIS migration, readiness/liveness, anonymous business 401; disposable resources removed |
| Compose configuration | PASS: apps + iot profiles parse with placeholder .env.example; real default platform starts with health gates |
| Infrastructure offline validator | PASS: health dependencies, loopback exposure, DB-user distinction, PKCE/trusted claims, contract hashes, workflows |
| Bootstrap shell syntax | PASS: bash -n inside PostgreSQL container |
| Contracts repository | PASS: unchanged v1/v2/spatial schemas/examples/negative cases/OpenAPI |
| Architecture and workspace | PASS: ten ADRs, all diagram syntax, 12 independent Git roots, no parent/submodules/remotes, workflow/YAML and heuristic secret/ignore checks |
| Shared platform acceptance with --faults | PASS: all seven groups below; temporary confidential test clients removed |

Actual platform acceptance groups:

1. Real Keycloak signatures/issuer/audiences; anonymous and wrong-audience denial; Estate/division/block/clone routing; canonical IDs; correlation propagation; actual response schema validation.
2. Estate command -> durable outbox -> RabbitMQ -> Spatial identity projection -> PostGIS feature creation -> gateway geometry read; VIEWER write denial and estate-scope isolation at both services.
3. Both application roles fail to connect to the other's database; PostGIS extension exists under Spatial credentials.
4. Actual Estate v2 and Spatial v1 event envelopes validate; diagnostic Spatial binding receives published events; duplicate Estate replay has one processed-event marker.
5. A known W3C trace appears in Jaeger with Gateway, Estate and Spatial processes, proving HTTP propagation and Collector export.
6. Stop Estate: gateway returns safe 503 Problem Details; restart and readiness recover.
7. Stop RabbitMQ: Estate accepts a command with a retained PENDING outbox record; restart broker and Spatial eventually projects the event.

Ignored local evidence includes baseline-1c.log and baseline-integration-1c.log in application repositories, service milestone-1c-verification.log files, infrastructure milestone-1c-build.log/milestone-1c-gateway-build.log/milestone-1c-smoke.log, Maven reports under target, and target/platform-smoke.json. No bearer token or password is included in the acceptance JSON. Smoke fixtures are explicitly SIMULATED and remain in local databases for inspection.

## Issues found and corrected

The new real-context gateway tests exposed a bean-name collision with Boot's requestContextFilter; the gateway filter has its own explicit bean name. Timeout configuration was initially ineffective through the selected Gateway client factory; an explicit JDK request factory with tested connect/read limits fixes that. The existing gateway Linux wrapper invocation failed distribution checksum validation during the first build; the Dockerfile now uses Maven 3.9.12 from the pinned builder image, matching both existing service Dockerfiles, without disabling wrapper checksum checks.

RabbitMQ fresh-boot definitions importing before virtual-host/user initialization failed; an authenticated one-shot importer now runs after broker health and retries management readiness. Partial realm imports did not include built-in role scopes; trusted realm-role mapping is now explicit in the supplied application scope. The first long acceptance run passed all functional groups but expired its administrator token during temporary-client cleanup; refresh fixes cleanup, and the full run subsequently passed. A preexisting Spatial image-smoke readiness race used the temporary PostgreSQL Unix socket; TCP readiness now waits for the final database server and the image test passes.

## Separate repository change summaries

### agrosphere-infrastructure — 0.2.0

Updated compose.yaml with app/identity/observability profiles, isolated credentials, internal service DNS/JWKS, health dependencies, explicit network and loopback exposure. Preserved PostgreSQL bootstrap and optional MQTT. Added Keycloak realm/PKCE/trusted claims, RabbitMQ diagnostic topology and post-bootstrap importer, Collector->Jaeger export, observability health-probe Dockerfiles, private environment initialization, identity configuration, shared test support, actual acceptance/recovery script, pinned contract snapshots/manifest, offline validator, test requirements and independent-image platform CI. Updated README, environment example, AGENTS, VERSION and CHANGELOG; added this report. No application business logic resides here.

### agrosphere-api-gateway — 0.2.0

Updated pom/version/Dockerfile/CI, application.yaml, security configuration, README, environment example, AGENTS and changelog. Added JwtValidationConfiguration, ProxyClientConfiguration, RequestContextFilter, SubjectRateLimit and safe GatewayProblem. Added seven real HTTP/JWT integration cases; adjusted the old test-only configuration annotation so it is not auto-discovered as application configuration. Original four security assertions remain. Gateway contains no plantation logic or persistence.

### agrosphere-estate-service — 0.2.1

Added optional trusted OIDC_JWK_SET_URI selection in JwtValidationConfiguration. Updated independent pom/VERSION/Dockerfile, environment example, README, AGENTS and CHANGELOG. No API, event, domain, persistence or migration changes; contracts remain pinned at the existing version.

### agrosphere-spatial-service — 0.2.1

Added optional trusted OIDC_JWK_SET_URI selection in JwtValidationConfiguration. Updated independent pom/VERSION/Dockerfile, environment example, README, AGENTS and CHANGELOG; refreshed overlay, CI and image-smoke references to 0.2.1. Fixed the image smoke's TCP database readiness race. No geometry, projection, API/event contract or migration changes.

### agrosphere-architecture — 0.4.0

Added ADR-0010 and MILESTONE_1C.md. Updated deployment/event diagrams and integration patterns to reflect the working stack, corrected the Estate diagram runtime to Java 25, and updated milestone status, README, AGENTS, VERSION, CHANGELOG and validator ADR count. Decisions record reuse of isolated databases, Gateway compatibility, local limiter tradeoff, trusted issuer/JWKS, diagnostic queue purpose, tracing boundaries and independent release/testing lifecycle.

agrosphere-contracts was reviewed and validated but not modified or version-bumped. Other repositories and all .git directories remain untouched.

## Limitations and next boundaries

The attachment remainder was unavailable. Local HTTP, generated private .env, bootstrap admin and start-dev identity are for workstation development. No HTTPS/certificate deployment, cloud service, external client application or remote release is claimed. Version tags are pinned; image digests/security scanning remain release hardening. The manually dispatched released-image CI workflow was syntax-validated locally; it was not remotely executed because no registry publication/remotes were authorized.

Rate limiting is bounded and per process, not distributed. Jaeger data is ephemeral; Collector exports traces only. HTTP tracing is proven; asynchronous outbox messages preserve correlation without cross-relay parent spans. Spatial's diagnostic queue is capped at 10,000 events and is not a production consumer/archive. Existing division lifecycle inference, outbox FAILED/DLQ operator replay, projection reconciliation, retention, backup/restore rehearsal and load/latency SLAs remain documented follow-up work. Existing stored credentials are not rotated by changing .env, and fresh-volume database initialization is not an upgrade mechanism. Populated volumes were not deleted.

Reproduce using README's setup/start/configure/acceptance commands. Stop without losing data using docker compose --profile apps down.
