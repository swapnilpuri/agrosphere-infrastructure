# Environment configuration

.env.example contains placeholders only; scripts/init_local.py creates private random values in ignored .env. local-secrets/ and target/ are ignored. Do not commit credentials, access/refresh tokens, session cookies or exported private identity configuration. The central compose.yaml supplies per-service settings; each repository retains independent standalone configuration.

| Setting | Purpose |
|---|---|
| POSTGRES_ADMIN_PASSWORD | Infrastructure-only database bootstrap credential |
| ESTATE_DB_PASSWORD / SPATIAL_DB_PASSWORD | Separate least-privilege service roles/databases |
| OPERATIONS_DB_PASSWORD / TELEMETRY_DB_PASSWORD / ANALYTICS_DB_PASSWORD / AI_DB_PASSWORD | Preserved M0 fresh-volume bootstrap placeholders; these services are not implemented/run |
| KEYCLOAK_DB_PASSWORD | Separate identity database ownership |
| KEYCLOAK_ADMIN_PASSWORD | Local bootstrap admin, never an application credential |
| RABBITMQ_PASSWORD | Local development broker credential |
| OIDC_PUBLIC_URL | Advertised Keycloak URL, default http://localhost:8180 |
| CORS_ALLOWED_ORIGINS | Exact origins, default http://localhost:4200; comma-separated |
| GATEWAY_CONNECT_TIMEOUT / GATEWAY_READ_TIMEOUT | 2s / 10s positive Java durations |
| GATEWAY_RATE_LIMIT | 120 requests per verified subject per minute per gateway process |
| TRACING_SAMPLE_PROBABILITY | 1.0 locally; standalone service defaults remain 0.1 |
| GATEWAY_IMAGE / ESTATE_IMAGE / SPATIAL_IMAGE | Independently tagged or digest-pinned images; current local defaults 0.2.0 / 0.2.1 / 0.2.1 |
| COMPOSE_PROJECT_NAME | Separate development project/network/volume namespace |

Gateway/Estate/Spatial enforce a default 2 MiB JSON body limit for both known-length and streamed POST/PUT/PATCH requests. Property overrides are gateway.limits.body-bytes, estate.limits.body-bytes and spatial.limits.body-bytes (1–16 MiB validated bounds). Compose accepts GATEWAY_MAX_BODY_BYTES, ESTATE_MAX_BODY_BYTES and SPATIAL_MAX_BODY_BYTES, each defaulting to 2097152. Changing the limit must be accompanied by appropriate coordinate/import bounds; Spatial still independently enforces its geometry, bbox and result limits.

Public issuer is OIDC_PUBLIC_URL + /realms/agrosphere. Internal OIDC_JWK_SET_URI is http://keycloak:8080/realms/agrosphere/protocol/openid-connect/certs; it selects only key retrieval, never a different accepted issuer. Audiences are agrosphere-api, estate-service and spatial-service. The realm defines resource-server clients for all three, a future public Angular client, and an integration public PKCE client. All user claims come from trusted administration; estate_ids is multivalued and administrator-editable only. PLATFORM_ADMIN has global access intentionally; manager/admin/viewer estate roles do not. AGRONOMIST is read-only in Spatial under its existing contract.

Gateway-to-service requests forward the signed user bearer token. Backends independently validate signature, issuer, audience, expiry, role and estate scope; acceptance also calls them directly on the Docker network. Spatial reads its own event projection and geometry and makes no synchronous Estate calls. No client-credential service account is needed for those paths. Future machine callers must use a separate narrowly scoped confidential client, audience and estate grants; never use the bootstrap administrator token as an internal business credential.

All exposed ports bind 127.0.0.1: 8080 gateway, 8180 identity, 5432 PostgreSQL, 5672/15672 broker, 4317/4318 collector, 16686 Jaeger and optional 1883 MQTT. Backend APIs, Keycloak management 9000, Collector health 13133 and Jaeger admin 14269 remain internal. Network name is project-name + -dev. HTTP loopback is development-only; external exposure requires TLS and trusted certificates. There were no existing certificates to reuse.
