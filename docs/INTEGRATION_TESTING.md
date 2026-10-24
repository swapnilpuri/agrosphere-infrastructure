# Integration testing

After the documented setup/start commands, one command runs the complete requested workflow:

~~~powershell
python scripts/smoke_platform.py --faults
~~~

The executable test authenticates real development users using Authorization Code + PKCE, obtains all IDs/tokens automatically, bootstraps an estate with the required administrator permission, scopes its manager/viewer, creates two divisions and ten rubber blocks, updates estate/block snapshots and validates domain failures. It polls bounded eventual-consistency conditions for confirmed outbox publication and Spatial reference projections.

It generates ignored target/rubber-plantation.geojson using those exact UUIDs, imports estate/two-division/ten-block geometry atomically, verifies WGS84 coordinate order, SRID, PostGIS validity, nonoverlap and spheroidal hectares, then queries boundaries, every block geometry, point membership, bounding boxes, centroids, GIS layers and paged GeoJSON export through Gateway. Real API bodies and four Estate lifecycle event types are checked against pinned contracts. No manual UUID/token editing is required.

Additional assertions cover anonymous/invalid authentication; VIEWER boundary-write denial; unassigned-user read/write/import denial; direct backend authorization without Gateway; known-length and streamed ingress bounds; role/database isolation; authenticated runtime OpenAPI; duplicate and out-of-order broker delivery; retained child snapshots arriving before an Estate parent; durable HTTP-to-outbox-to-AMQP tracing in Jaeger; Spatial reads while Estate is stopped; and recovery after Estate/broker restarts. --faults explicitly opts into service interruptions. Omit it when sharing the developer stack.

Fixtures use unique SMOKE_/SIMULATED names in the existing local service databases and remain for inspection; developer data and volumes are never reset. Generated fixture IDs, import ID, trace ID and actual check names are in ignored target/platform-smoke.json. Development credentials are generated privately in ignored local-secrets/dev-users.json. No secrets are written to the result artifact. A new project namespace can be used for isolated runs after freeing the default loopback ports.

## Independent checks

~~~powershell
# Gateway, JDK 25:
Set-Location ../agrosphere-api-gateway
.\mvnw.cmd verify
docker build -t agrosphere-api-gateway:0.2.0 .
# Estate, JDK 25:
Set-Location ../agrosphere-estate-service
.\mvnw.cmd verify -Pintegration
python scripts/validate_events.py
python scripts/validate_api.py
docker build -t agrosphere-estate-service:0.2.1 .
# Spatial, JDK 21:
Set-Location ../agrosphere-spatial-service
.\mvnw.cmd verify -Pintegration
python scripts/validate_contracts.py
docker build -t agrosphere-spatial-service:0.2.1 .
python scripts/smoke_image.py
# Infrastructure:
Set-Location ../agrosphere-infrastructure
python scripts/validate.py
docker compose --env-file .env.example --profile apps --profile iot config --quiet
~~~

Install each repository's documented Python validation dependencies first. Service suites use disposable Testcontainers databases/brokers; platform tests use Compose. No service build reads sibling Java classes. Contract snapshots are pinned to schema release 0.3.0, independently of documentation-only later contract releases. Infrastructure CI validates configuration and scripts; manually dispatched full-platform CI consumes three independently released image references, not sibling source checkouts. Images can be tagged/rebuilt independently; registry publication/Azure deployment is outside this milestone. CI shutdown also preserves volumes; runner disposal owns its ephemeral environment.

## Parent-late reconciliation

Spatial intentionally stores valid block snapshots even if the Estate snapshot has not arrived, retaining the canonical estate ID and inferred division reference without a cross-service foreign key. It neither invents the authoritative Estate nor discards the block. Geometry writes require the authoritative active Estate reference; they return an actionable validation failure until that snapshot arrives. Later Estate events upsert the missing parent automatically; no child replay or per-read Estate call is required. Stale snapshot revisions cannot overwrite newer ones.

Detect unresolved parents using a service-owned query over reference_entity where a BLOCK row has no matching ESTATE row for its estate_id. Check the broker queue/DLQ and Estate outbox before requesting a controlled existing-snapshot replay. Poison schema/identity failures use the existing three-attempt exponential consumer retry and spatial.estate.v2.dead queue. No division lifecycle events exist; inferred division membership is documented and must not be represented as authoritative lifecycle status. Tests publish a child before its parent and verify retention and later reconciliation explicitly.
