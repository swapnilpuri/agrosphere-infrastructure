# M5 owned desktop fixture

Authorized by Architecture `M5_DELIVERY_APPROVAL_2026_11_10.json` and the exact M5 package, with physical VR deferred. This fixture does not enable REAL data, update the developer stack or supply owner functional acceptance.

Run from this independent repository:

```powershell
python scripts/verify_m5.py --hold-seconds 3600
```

The default hold is zero (verify then clean up); maximum requested hold is 14,400 seconds. Use an available Docker daemon and the existing pinned build/dependency toolchains. The script builds independently tagged Estate/Spatial/Gateway and existing observability images, then starts only the new Gateway dependency graph. It never loads `.env`, `local-secrets/dev-users.json` or an existing Compose project.

Every run has a random `agrosphere-m5-<run>` Compose name and separately generated credentials. It uses the existing public topology with a new disposable realm file, new volume names and random loopback Gateway/identity ports. No host DB/broker/observability ports are exposed. The existing `postgres/init.sh` runs only against the new empty owned volume; applications keep their service-owned schemas/migrations. The sole SQL inspection is a Spatial-role count of Spatial's own event-consumed block references. No cross-service SQL, migration modification or existing role/credential update occurs.

The fixture creates a generated administrator for setup, scoped VIEWER, foreign-estate VIEWER and a roleless negative-test subject. The native `agrosphere-immersive` public client has one exact redirect, `http://127.0.0.1:49152/oauth/callback`, authorization code/S256 only, no direct password grant, and a 30-minute session limit. Web/integration clients remain as defined in the public realm. Realm provisioning and role mappings affect only this new owned realm. API tests authenticate through the existing real authorization-code/PKCE test helper; they do not claim that the Unreal login UI was exercised.

Twelve generated blocks in the allowed estate and one block in a foreign estate receive canonical 2D WGS84 polygon geometry through the existing Spatial API after event references settle. Metadata and geometry are compared through all six reads used by M5. The checks cover scoped estate listing, each selected block's UUID/geometry/provenance, foreign estate/object denial, missing role, missing/invalid token and VIEWER write denial. The generated plantation coordinates are illustrative and are not a survey; neither the metadata area nor decorative trees assert real inventory.

## Native-client handoff

Wait for the script's `M5 fixture ready` message. `target/m5-latest.json` contains only safe identifiers/status, Gateway/issuer endpoints, image IDs, DTO hashes, the evidence path, and paths to the owned generated credentials and stop sentinel. Credentials are never printed and tokens are never persisted. The actual generated username/password file and geometry copy exist only in that run's disposable temporary directory. Use only the credentials for this run when exercising the external-browser native login. Never copy them into source, logs, configuration or a durable export.

Keep the script running while the native/browser checks execute. To end the fixture early, create the exact `stopFile` named in its manifest. Do not kill the process or delete arbitrary Compose resources. The script's `finally` checks exact container labels, removes only its named project's containers/volumes, removes only its own unique image tags, deletes only known files in the resolved owned temporary directory, and writes cleanup status. On Docker/ownership failure, cleanup remains explicitly blocked; it never substitutes a broad prune/reset.

Results are in `target/m5/<run>/results.json`; runtime data and credentials are deleted, while sanitized identifiers/hashes/results remain. Logs/reports are local ignored artifacts, not hosted-CI or public releases. Desktop rendering, native authentication/refresh/callback tests, frame timing, package launch and physical VR are separate checks and cannot be inferred from this harness's PASS.

## Recovery after verifier interruption

If the verifier process is absent and its project containers are all stopped, run `python scripts/cleanup_m5.py --manifest target/m5-latest.json`. It verifies the run/project identity, exact resource labels, stopped state, image identities and resolved generated temporary directory before removing only that fixture. It records `INTERRUPTED_CLEANED`, never a successful verification. It refuses running containers; use the stop sentinel while a verifier is active. A process termination can prevent the normal lifetime/finally cleanup, so inspect the manifest after an interruption rather than trusting an old READY label.
