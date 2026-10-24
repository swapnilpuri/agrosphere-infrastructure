# Milestone 1C completion report

Date: 2026-10-24 (America/Chicago). Final scope: the complete requirements in the user's follow-up, including sections 6–19. This report supersedes the earlier partial-attachment report.

## Outcome

All sixteen definition-of-done criteria are implemented and locally verified. Gateway 0.2.0, Estate 0.2.1, Spatial 0.2.1 and infrastructure 0.2.0 run as independently built images. Architecture 0.4.0 records integration decisions. Contracts 0.3.1 adds compatibility documentation only; API/event schema snapshots remain pinned to unchanged release 0.3.0 (Estate API/v2 semantics from 0.2.0). The stack remains running and healthy.

The requested estate-manager authentication uses a real development user and Authorization Code + PKCE S256. Existing Estate policy reserves global estate/clone creation to PLATFORM_ADMIN: the test proves a manager cannot bootstrap an estate, uses a development administrator for that step, then assigns the new canonical UUID to a manager who executes division/block/import/query commands. Authorization was preserved rather than broadened to make the test pass. No client-credential account impersonates human users.

No agent action created GitHub repositories/remotes, committed, pushed, published a registry image or deployed to Azure. All .git roots and existing connections are preserved; remotes present during the final audit are allowed. No persistent developer volume was deleted. No credentials/tokens/private users file were committed. The workflow creates clearly named SIMULATED test records and retains them for inspection.

## Preparation and implementation sequence

Read infrastructure AGENTS/README, all existing ADRs, architecture/requirements/diagrams, contracts and event versions, Estate/Spatial completion reports and implementation, gateway scaffold, environment/certificate inventory, service migrations, Compose/overlays and all affected CI workflows before modifying their repositories. No reusable local certificate files existed. Existing implementation was verified rather than assumed complete.

The initial inspection/plan selected reuse of isolated databases, existing outboxes/projection and compatible Gateway MVC. Baseline builds/contracts were recorded before configuration work. Implementation then connected identity, broker topology and gateway, added health-gated orchestration/HTTP tracing, executed initial integration and fixed discovered issues. When the full request arrived, it added real PKCE users, the exact ten-block GeoJSON scenario, durable outbox trace context, direct backend/request-size assertions, dedicated runbooks and full reporting. No business service was replaced or expanded beyond M1C.

| Baseline repository | Actually executed before implementation |
|---|---|
| Infrastructure | Existing all-profile Compose parse passed; existing seven-database/non-superuser bootstrap inspected |
| Gateway | Maven verify: 4 security tests passed |
| Estate | Maven verify: 38 unit/security tests; actual Java 25 integration: 9 PostgreSQL/RabbitMQ/HTTP/JWT cases passed |
| Spatial | Maven verify: 19 tests; actual Java 21 container integration: 12 PostGIS/RabbitMQ/HTTP/JWT cases passed |
| Contracts | v1/v2/spatial schemas/examples/negative cases and OpenAPI validation passed |
| Architecture | Source/workflow checks and independent 12-repository audit passed |

Host default Java was 27; authoritative final Gateway/Estate verification used Java 25, and Spatial used Java 21 containers. The sandbox launcher initially failed with OS access denied; reviewed local command execution worked. No failed launcher or previous report was treated as proof that a test passed.

## A. Repositories and files modified

Each repository retains its own Git root, build/tests, Dockerfile/CI, independent version and service-owned migrations. No shared parent build/repository, Git submodule, shared JPA model or cross-service SQL was introduced. Local Docker build contexts reference sibling repositories only for orchestration; released-image CI consumes independent image references without sibling Java sources.

### agrosphere-infrastructure — 0.2.0

Central health-gated Compose, trusted Keycloak/PKCE/user setup, Rabbit topology, Collector/Jaeger, private configuration, pinned contracts, end-to-end/recovery tests and Windows runbooks.

Changed/added files:

- AGENTS.md; README.md; VERSION; CHANGELOG.md; .env.example; compose.yaml; requirements-test.txt.
- .github/workflows/ci.yml; .github/workflows/platform.yml.
- otel/collector.yaml; otel/Dockerfile; jaeger/Dockerfile; rabbitmq/definitions.json.
- scripts/init_local.py; scripts/init_broker.py; scripts/platform_support.py; scripts/configure_identity.py; scripts/dev_identity.py; scripts/smoke_platform.py; scripts/export_openapi.py; scripts/validate.py.
- keycloak/agrosphere-realm.json.
- docs/LOCAL_DEVELOPMENT.md; docs/ENVIRONMENT_CONFIGURATION.md; docs/INTEGRATION_TESTING.md; docs/TROUBLESHOOTING.md; docs/MILESTONE_1C_REPORT.md.
- tests/contracts/estate.openapi.json; tests/contracts/spatial.openapi.json; tests/contracts/manifest.json.
- tests/contracts/events/v2/EstateCreated.schema.json; EstateUpdated.schema.json; PlantationBlockCreated.schema.json; PlantationBlockUpdated.schema.json.
- tests/contracts/events/spatial/v1/SpatialFeatureCreated.schema.json; SpatialFeatureUpdated.schema.json; SpatialBoundaryChanged.schema.json; SpatialLayerCreated.schema.json; DigitalTwinAssetRegistered.schema.json.

postgres/init.sh and its existing ownership bootstrap remain unchanged. No reset helper deletes volumes. Private .env, local-secrets/dev-users.json, generated GeoJSON, logs and results are ignored runtime artifacts.

### agrosphere-api-gateway — 0.2.0

Retained Boot 4.0.9/Cloud 2025.1.4/Gateway MVC 5.0.4 and Java 25. Added routes, RS256 issuer/audience validation, UUID correlation, structured access fields, CORS, bounded subject limiter, tested request timeouts/503 behavior and 2 MiB known/streamed body limits.

Changed/added files:

- AGENTS.md; README.md; VERSION; CHANGELOG.md; .env.example; pom.xml; Dockerfile; .github/workflows/ci.yml.
- src/main/resources/application.yaml.
- src/main/java/com/agrosphere/gateway/SecurityConfiguration.java; JwtValidationConfiguration.java; ProxyClientConfiguration.java; RequestContextFilter.java; ActiveTraceFilter.java; SubjectRateLimit.java; BodyLimitFilter.java; GatewayProblem.java.
- src/test/java/com/agrosphere/gateway/SecurityPolicyTest.java; GatewayIntegrationTest.java.

No domain logic, database or discovery server was added. The old test-only configuration is excluded from application component discovery; the original four assertions remain.

### agrosphere-estate-service — 0.2.1

Optional internal JWKS with exact public issuer retained; additive durable trace metadata and observed outbox publication; request bound. Existing domain/API/event semantics and V1/V2 migrations remain unchanged.

Changed/added files:

- AGENTS.md; README.md; VERSION; CHANGELOG.md; .env.example; pom.xml; Dockerfile.
- src/main/resources/application.yaml; src/main/resources/db/migration/V3__outbox_trace_context.sql.
- src/main/java/com/agrosphere/estate/adapter/out/security/JwtValidationConfiguration.java.
- src/main/java/com/agrosphere/estate/adapter/out/messaging/JdbcEventOutbox.java; OutboxDispatcher.java; TraceTransport.java.
- src/main/java/com/agrosphere/estate/adapter/in/web/BodyLimitFilter.java.
- src/test/java/com/agrosphere/estate/EstateServiceIT.java (additive migration count).

### agrosphere-spatial-service — 0.2.1

Optional internal JWKS, additive durable outbox trace metadata, observed publisher/listener and correlated projection logging. Existing geometry, projection/deduplication/revision behavior and V1/V2 migrations remain unchanged. The packaged-image smoke now waits for final TCP PostgreSQL readiness.

Changed/added files:

- AGENTS.md; README.md; VERSION; CHANGELOG.md; .env.example; pom.xml; Dockerfile; .github/workflows/ci.yml.
- deploy/compose.spatial.yaml; scripts/smoke_image.py.
- src/main/resources/application.yaml; src/main/resources/db/migration/V3__outbox_trace_context.sql.
- src/main/java/com/agrosphere/spatial/adapter/out/security/JwtValidationConfiguration.java.
- src/main/java/com/agrosphere/spatial/adapter/out/messaging/JdbcEventOutbox.java; OutboxDispatcher.java; TraceTransport.java.
- src/main/java/com/agrosphere/spatial/adapter/in/messaging/EstateProjection.java (MDC correlation).
- src/test/java/com/agrosphere/spatial/SpatialServiceIT.java (additive migration count).

### agrosphere-contracts — 0.3.1

Changed/added: AGENTS.md; README.md; VERSION; CHANGELOG.md; docs/COMPATIBILITY.md. Documentation-only release; every existing OpenAPI/event schema is preserved. Canonical UUIDs, v1/v2/spatial namespaces, compatibility rules, trace transport outside the envelope and parent-late behavior are explicit. Service/platform schema snapshots remain pinned to 0.3.0.

### agrosphere-architecture — 0.4.0

Changed/added: AGENTS.md; README.md; VERSION; CHANGELOG.md; scripts/validate.py; docs/adr/0010-local-platform-integration.md; docs/adr/0011-outbox-tracing-and-reference-reconciliation.md; docs/roadmap/MILESTONE_1C.md; docs/roadmap/MILESTONES.md; docs/roadmap/MILESTONE_1B.md; docs/architecture/CONTAINER_ARCHITECTURE.puml; DEPLOYMENT_ARCHITECTURE.puml; EVENT_FLOWS.puml; DATA_OWNERSHIP.puml; INTEGRATION_PATTERNS.md. The audit checks eleven ADRs and independent Git roots while preserving valid existing remotes.

## B. Running infrastructure and dependencies

| Container/service | Host loopback ports | Dependencies |
|---|---|---|
| postgres / PostGIS 17-3.6 | 5432 | Existing persistent postgres-data; separate owned databases/roles |
| rabbitmq / 4.3.6-management | 5672, 15672 | Persistent rabbitmq-data |
| rabbitmq-init / Python one-shot | none | Broker health + retried management readiness; exits successfully after topology import |
| keycloak / 26.5.7 | 8180 | PostgreSQL health; isolated identity DB; internal management health 9000 |
| jaeger / 1.76.0 | 16686 | Internal admin health 14269; in-memory traces |
| otel-collector / 0.135.0 | 4317, 4318 | Healthy Jaeger; internal health 13133 |
| spatial / 0.2.1 | none (internal 8082) | DB, broker topology, Keycloak and collector healthy |
| estate / 0.2.1 | none (internal 8081) | Those dependencies plus healthy Spatial consumer topology |
| gateway / 0.2.0 | 8080 | Estate/Spatial healthy |

Network: agrosphere-local-dev, explicitly project-scoped. Profiles: default backing DB/broker/topology; identity; observability; apps (includes applications + identity + tracing); optional authenticated iot/Mosquitto on loopback 1883. All published ports bind 127.0.0.1; business-service and management health ports remain internal. Startup uses real health/completion gates, not fixed delays.

## C. Actual integration results

The final script passes twelve acceptance groups:

1. Real generated dev users authenticate through Authorization Code + PKCE S256. Manager global-estate creation is denied; administrator creates the estate and assigns its UUID. Issuer validation is retained with internal JWKS retrieval.
2. Creates two divisions and ten unique rubber blocks with clone, planting date, hectares, planted/tappable counts; validates response schemas/persistence/relationships and create/read/update behavior. Duplicate codes and invalid tree counts are rejected.
3. EstateCreated, EstateUpdated, PlantationBlockCreated and PlantationBlockUpdated all occur in the atomic outbox, are publisher-confirmed and are consumed into canonical Spatial references using bounded polling.
4. Imports generated GeoJSON for the same estate/division/block UUIDs: thirteen valid WGS84/SRID4326 polygons, no block overlaps, parent coverage and correct spheroidal hectare values (block areas between 1 and 1.5 ha).
5. Gateway queries retrieve the Estate boundary, all ten block geometries, point membership, bounding boxes, centroids, a GIS boundary layer and thirteen-feature GeoJSON export.
6. Actual spatial v1 envelopes validate and confirmed publications arrive at the durable diagnostic queue.
7. VIEWER cannot modify Estate boundary; unassigned user cannot read/write/import; application DB roles cannot connect to the other's database.
8. Direct container-network calls independently enforce backend JWT/estate authorization without Gateway; oversized backend requests return 413; authenticated runtime OpenAPI operation sets match pinned contracts.
9. Duplicate messages create one deduplication marker; older revisions delivered after newer ones do not overwrite projections. A child delivered before Estate remains stored and automatically reconciles when the authoritative parent arrives.
10. The initiating W3C trace continues through HTTP, persisted outbox context, Rabbit producer and Spatial consumer spans and is visible in Jaeger. Structured logs include timestamp/service/level and active trace/span/correlation fields, without tokens/passwords/bodies.
11. With Estate stopped, Spatial still serves existing geometry and layers. Gateway returns safe 503 for Estate; restarting Estate recovers independently.
12. With RabbitMQ stopped, a new Estate command remains atomic with a PENDING outbox record; restarting broker resumes publication/projection without duplicate effects.

Actual fixture IDs/import/trace and check labels are in ignored target/platform-smoke.json; the matching generated dataset is target/rubber-plantation.geojson. Authenticated runtime descriptions are target/estate.openapi.json and target/spatial.openapi.json. No IDs or tokens require manual editing.

## D. Testing commands and actual results

| Command/check | Result |
|---|---|
| Gateway Java 25 Maven verify / Docker build verification | PASS: 12 tests (4 original + 8 real HTTP/JWKS integration), zero failures/errors/skips |
| Estate Java 25 mvnw.cmd verify -Pintegration | PASS: 38 unit/security + 9 real integration tests, zero failures/errors/skips |
| Spatial Java 21 container mvn verify -Pintegration | PASS: 19 unit/security + 12 real integration tests, zero failures/errors/skips |
| Total Java checks | 90 passing tests |
| Estate validate_events.py + validate_api.py | PASS: actual envelopes for all four v2 event types; all 16 pinned/runtime API operations |
| Spatial validate_contracts.py | PASS: actual HTTP/event samples, synthetic estate snapshots, sample import and runtime OpenAPI |
| Docker Compose all application/observability builds | PASS: independent Gateway/Estate/Spatial and Collector/Jaeger images |
| Spatial scripts/smoke_image.py | PASS: Java21/nonroot runtime, V1–V3 migration, readiness/liveness and anonymous 401; disposable resources cleaned |
| Infrastructure scripts/validate.py --local | PASS: placeholder/private configuration validation, distinct credentials, bounded values, health/network/PKCE/contract hashes/workflows |
| docker compose --env-file .env.example --profile apps --profile iot config --quiet | PASS |
| python -m compileall -q scripts | PASS |
| bash -n postgres/init.sh in PostgreSQL container | PASS |
| Contracts python scripts/validate.py | PASS: unchanged v1/v2/spatial schemas/examples/negative cases and all OpenAPI |
| Architecture validator --workspace plus PlantUML -checkonly | PASS: 11 ADRs, seven diagrams, 12 independent Git roots, no parent/submodules, existing remotes preserved, workflows/YAML/ignore/heuristic secrets |
| python scripts/smoke_platform.py --faults | PASS: twelve complete acceptance groups |
| python scripts/export_openapi.py | Authenticated export is also exercised by the same internal HTTP helper/full-suite assertions |

No required local validation is skipped. Remote GitHub Actions execution and remote registry publication are outside this milestone and were not performed; workflows were syntax/structure checked. Service-level suites use disposable Testcontainers. Platform fixtures are uniquely identified SIMULATED development records, with no unexpected developer-data reset.

Logs are ignored: baseline-1c.log/baseline-integration-1c.log; service milestone-1c-full.log; infrastructure milestone-1c-full-build.log, milestone-1c-final-gateway-build.log, milestone-1c-full-start.log and milestone-1c-full-smoke.log. Maven reports and actual contract evidence remain under each service's target. Secrets are never included in result artifacts.

Issues found and fixed included a gateway/Boot bean-name collision; ignored proxy timeout settings (replaced by a tested explicit JDK client factory); Rabbit import before initial user/vhost readiness (one-shot importer); explicit trusted role mappers; expired initial service-account test cleanup (superseded by real PKCE user flow); temporary PostgreSQL Unix-socket readiness race; binary-float JSON Schema multipleOf false negatives (exact-decimal validation); and legacy workspace-audit assumptions prohibiting legitimate existing remotes. Additive migration counts were updated; unchanged business regressions pass.

## E. Exact Windows run instructions

~~~powershell
Set-Location C:\Projects\agrosphere\agrosphere-infrastructure
# First setup only; refuses to overwrite an existing private .env:
python scripts/init_local.py
python -m pip install -r requirements-test.txt
# Start the full integrated platform:
docker compose --profile apps up -d --build --wait --wait-timeout 240
python scripts/configure_identity.py
python scripts/dev_identity.py
# Run the complete end-to-end suite, including intentional service outages:
python scripts/smoke_platform.py --faults
# Inspect health:
docker compose --profile apps ps
Invoke-RestMethod http://localhost:8080/actuator/health/readiness
# Export authenticated backend OpenAPI for VS Code/API-client import:
python scripts/export_openapi.py
code target/estate.openapi.json
code target/spatial.openapi.json
# Open local development UIs:
Start-Process http://localhost:8180/admin/
Start-Process http://localhost:15672
Start-Process http://localhost:16686
# Stop safely, retaining all database/broker volumes:
docker compose --profile apps down
~~~

On subsequent starts omit init_local.py. Keycloak bootstrap username is agrosphere_admin; its password is private KEYCLOAK_ADMIN_PASSWORD. Rabbit username is agrosphere with private RABBITMQ_PASSWORD. Generated user passwords are in ignored local-secrets/dev-users.json. No password/token is printed by setup/auth helpers. Health is public; runtime docs and business APIs require signed scoped JWTs. Internal service authentication forwards user bearer identity and is independently checked at each backend; no synchronous Spatial-to-Estate call is required.

Individual service changes require only that repository's independent build/tag plus the affected Compose service restart. Set GATEWAY_IMAGE/ESTATE_IMAGE/SPATIAL_IMAGE to independently built/pulled tags or digests for --no-build operation. Detailed local/configuration/testing/recovery instructions are in the four required docs files. A clean no-cache image rebuild preserves volumes. Use a fresh project namespace for an empty sandbox; true data deletion requires explicit approval/backups and is never automated, including CI shutdown.

## F. Definition of done and remaining boundaries

All sixteen criteria pass: Compose startup; correct Gateway routes; real Keycloak; independent service validation; Estate/block APIs; reliable events; Spatial projection; canonical GeoJSON import; PostGIS queries; database isolation; independent builds/runtime; passing integration; Jaeger distributed traces; health/readiness; reproducible documentation; and unchanged business regression tests.

No required Milestone 1C feature remains incomplete. Remaining engineering limits are explicit: workstation start-dev/HTTP and local bootstrap credentials; per-process bounded gateway rate limiting; ephemeral Jaeger storage; no retained metrics/log backend or JDBC agent; image digest/security/backup/load-SLA hardening; operator-controlled exhausted-outbox/DLQ replay; and the existing absence of authoritative division lifecycle events. None is represented as a production guarantee. Legacy outbox rows with null trace context remain publishable but cannot recover an initiating trace that was never stored. Changing private .env values does not rotate initialized credentials. Existing volume data and Git connections remain intact.

## G. Recommended Milestone 2 sequence (not started)

1. Initialize the independent Angular client with typed versioned API clients, PKCE login/logout/refresh and role/estate-aware navigation.
2. Build the estate/division/block selector and metadata panels with bounded pagination, loading/error states and stable canonical IDs.
3. Add CesiumJS globe/terrain/imagery under reviewed licensing and environment configuration; render canonical GeoJSON with correct coordinate order.
4. Implement estate fly-to, block picking/highlighting, authoritative metadata lookup and GIS layer controls, preserving provenance labels.
5. Add role-aware editing affordances only for existing permitted APIs; backend authorization remains authoritative.
6. Verify end-to-end user login, estate isolation, geometry selection, paging and recovery in browser tests; establish named-device rendering/LOD budgets.

Operations, Telemetry, Analytics, AI, Unreal, Kubernetes and Azure remain outside this milestone. Stop after Milestone 1C.
