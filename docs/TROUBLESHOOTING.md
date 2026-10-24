# Troubleshooting

~~~powershell
docker compose --profile apps ps -a
docker compose --profile apps logs --tail 100 gateway estate spatial
docker compose --profile apps logs --tail 100 keycloak rabbitmq rabbitmq-init otel-collector jaeger
Invoke-RestMethod http://localhost:8080/actuator/health/readiness
~~~

Do not print docker compose config with private .env values. Use --env-file .env.example config --quiet for syntax validation. Logs/results must never include bearer tokens, passwords or raw request bodies.

| Symptom | Check and remediation |
|---|---|
| Port already in use | Stop the conflicting local project; backend APIs need no host ports. Do not terminate unrelated infrastructure or delete volumes. |
| OIDC 401 | Confirm exact public issuer, signature, audience and expiry. Container localhost is not Keycloak: use internal JWKS DNS, keeping public issuer unchanged. Run configure_identity.py to apply trusted mappers/clients. |
| PKCE user login fails | Run dev_identity.py; inspect required user actions and configured callback/PKCE settings. Passwords remain in ignored local-secrets/dev-users.json. Existing user passwords are never reset automatically. |
| Estate/geometry 403 | Check trusted realm role and administrator-managed estate_ids. A manager cannot create global estates; PLATFORM_ADMIN must bootstrap them. VIEWER/AGRONOMIST cannot write geometry. |
| 413 | Body exceeded the configured ingress limit. Reduce/split the bounded GeoJSON import; do not disable validation. |
| 429 | Gateway's per-subject minute budget exhausted; honor Retry-After. This local limiter is per process. |
| 503 from Gateway | Downstream is unavailable or timed out. Inspect readiness/logs and the configured connect/read limits. No command retry occurs in Gateway. |
| Missing Spatial reference | Poll briefly for eventual consistency, then inspect Estate outbox and spatial.estate.v2 / spatial.estate.v2.dead. Child-first snapshots remain stored; later Estate events reconcile them. Do not fabricate a parent or query Estate tables from Spatial. |
| Import FAILED | Inspect validationReport and source feature index; verify canonical UUIDs, WGS84 longitude/latitude, valid nonoverlapping polygons and parent containment. Failed jobs import no partial features. |
| PENDING/FAILED outbox | Check broker availability, durable bindings and confirms. FAILED rows require explicit operator-controlled replay under service instructions; no automatic deletion/purge exists. |
| RabbitMQ bootstrap failure | rabbitmq-init must run after the broker is healthy; it retries management readiness and imports topology without replacing users. Stored passwords must match .env. |
| No Jaeger traces | Confirm sampling, collector endpoint, exporter health and known trace ID. V3 must exist in both service databases so delayed outbox publication retains its initiating trace. Existing pre-V3 rows have no parent context and start new traces. |
| DB login fails after editing .env | Existing volumes retain their old credentials. Restore matching configuration or perform a reviewed credential rotation; never delete volumes as a workaround. |

Health checks gate initial startup. SQL readiness uses TCP so PostgreSQL's temporary initialization socket is not mistaken for the final server. Existing services tolerate broker/database reconnects after startup. The additive V3 transport migration leaves every existing event envelope/migration intact. Jaeger uses ephemeral in-memory storage; SQL operation spans are not claimed without JDBC instrumentation. Rabbit producer/consumer observations and W3C transport continuity are enabled and asserted by the full acceptance suite.

Stop safely with docker compose --profile apps down. There is no automatic data reset or volume-deletion command. See LOCAL_DEVELOPMENT.md for clean image rebuilds and a fresh project namespace.
