# TLM-02 finite generated publisher and Web drill

This implements the accepted Architecture `MQTT_POC_OVERLAY_REVIEW.md` scope; it is restricted to new owned disposable SIMULATED fixtures. Do not use developer `.env`, local broker files, existing accounts, stacks or data. Docker must already be available. The independent Web artifact must first pass `npm ci` and `npm run build`; the opt-in cross-repository drill coordinates independently built applications, not runtime source imports.

Run `python scripts/verify_telemetry_overlay.py` from Infrastructure. It reuses the new random project/empty-env-file tapping harness, retains its Keycloak/Gateway/Estate/Operations checks, adds its own authenticated MQTT and Telemetry containers, and builds one generated Spatial block through the owning API. The private fixture alone enables signed-JWT backend metrics for committed/duplicate ingress evidence; Gateway exposes no metrics route. Broker publisher/subscriber principals and exact topic ACLs are separate; transient protected client configuration supplies credentials without password command arguments.

The callback writes a hashed plan in its ownership-marked temporary directory. It fixes the seed and uses the generated server clock/window, six samples at synthetic 30-second observation intervals, all three accepted kinds/units, and deterministic UUIDv5 identities. These are fixture choices, not measured device facts. The finite publisher sends the historical sequence immediately; it is not a real-time daemon. Restarting the same plan must produce identical bodies and 18 duplicate domain results, not 18 additional effects. `sampleCount` defaults to six, accepts only integers 1–120 and caps the sequence at 360 observations. No random walk or real-device discovery.

The separately runnable publisher accepts only an explicit plan and its SHA-256:

```
python scripts/telemetry_simulator.py --plan <owned-plan-file> --sha256 <verified-sha256>
```

It verifies owner marker, in-root file paths, size bounds, immutable channel/ACL/broker/client-config hashes, canonical identities, admission clocks, exact running container ID/run label and loopback topology before publishing. A changed/unowned target fails without fallback. Transport publication is reported separately from domain acceptance. No durable plan or secret is provided for the developer stack; the drill removes its fixture files on exit.

The acceptance drill checks committed observation/outbox counts, all three latest values and exact event identity/schema matches, then drives real browser Code/PKCE through generated Keycloak, Gateway and Cesium. Browser traces are off; logs redact generated passwords/tokens. It starts only a new owned loopback Web listener with built public assets and transient generated configuration; an occupied port fails without fallback. Only the new fixture realm/Gateway receive its matching redirect/CORS origin. The listener closes in finally; no existing server/configuration is read or reused. The wrapper removes only its labelled containers and parent project, then asserts absence of its containers, networks and volumes. Failure still runs cleanup; uncertain ownership stops removal.

Results: ignored `target/telemetry-overlay-platform.json`, `target/tlm02-platform*.log` and `target/telemetry-overlay-browser.log`; Web screenshot in ignored `test-results/telemetry-generated-live.png`. Durable sanitized verification is indexed from Architecture's checkpoint. Run `python scripts/validate.py`, publisher unit tests and retained watchdog tests. CI runs both independent unit suites; full platform drill remains opt-in. Software WebGL cannot close physical-device performance, owner functional, field or production gates.
