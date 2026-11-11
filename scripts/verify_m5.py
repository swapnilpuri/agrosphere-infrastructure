"""Owned M5 generated desktop fixture. Never reads the developer's .env or users.

Creates a fresh Compose project, scoped generated subjects, a native public PKCE
client, and two estates. Only the new project's manifest-owned resources are
removed. --hold-seconds keeps it available for an actual Unreal/browser demo.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import uuid
from urllib.parse import urlparse

from platform_support import ROOT, request, admin_token
from dev_identity import login
from configure_identity import configure


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main(hold_seconds=0, web_origin="http://localhost:54200"):
    if not 0 <= hold_seconds <= 14400:
        raise ValueError("Hold duration must be between 0 and 14400 seconds")
    origin = urlparse(web_origin)
    if origin.scheme != "http" or origin.hostname not in ("localhost", "127.0.0.1") or not origin.port or not 1024 <= origin.port <= 65535 or any((origin.username, origin.password, origin.path, origin.query, origin.fragment)):
        raise ValueError("Web origin must be an explicit loopback HTTP origin with port 1024–65535")
    run = uuid.uuid4().hex
    project = "agrosphere-m5-" + run[:12]
    target = ROOT / "target" / "m5" / run
    target.mkdir(parents=True, exist_ok=False)
    result_path = target / "results.json"
    latest = ROOT / "target" / "m5-latest.json"
    record = {"runId": run, "project": project, "status": "PREPARING", "ownerAcceptance": "OPEN",
              "scope": "SIMULATED newly owned M5 fixture", "checks": [], "cleanup": "NOT_RUN"}
    oidc_port, gateway_port = free_port(), free_port()
    while gateway_port == oidc_port:
        gateway_port = free_port()
    keys = ["POSTGRES_ADMIN_PASSWORD", "ESTATE_DB_PASSWORD", "SPATIAL_DB_PASSWORD", "OPERATIONS_DB_PASSWORD",
            "OPERATIONS_APP_DB_PASSWORD", "TELEMETRY_DB_PASSWORD", "ANALYTICS_DB_PASSWORD", "AI_DB_PASSWORD",
            "KEYCLOAK_DB_PASSWORD", "KEYCLOAK_ADMIN_PASSWORD", "RABBITMQ_PASSWORD"]
    config = {key: secrets.token_urlsafe(28) for key in keys}
    config.update(COMPOSE_PROJECT_NAME=project, OIDC_PUBLIC_URL=f"http://127.0.0.1:{oidc_port}",
                  ESTATE_IMAGE=project + "-estate", SPATIAL_IMAGE=project + "-spatial", GATEWAY_IMAGE=project + "-gateway",
                  GATEWAY_RATE_LIMIT="1000", TRACING_SAMPLE_PROBABILITY="0", CORS_ALLOWED_ORIGINS=web_origin)
    gateway = f"http://127.0.0.1:{gateway_port}"
    images = [project + "-" + service for service in ("estate", "spatial", "gateway", "jaeger", "otel-collector")]
    ownership_established = False
    started = time.monotonic()
    private_dir = Path(tempfile.mkdtemp(prefix=project + "-"))
    private_file = private_dir / "generated-users.json"
    stop_file = private_dir / "stop"
    record.update(gateway=gateway, issuer=config["OIDC_PUBLIC_URL"] + "/realms/agrosphere",
                  privateFixtureFile=str(private_file), stopFile=str(stop_file), evidencePath=str(result_path), webOrigin=web_origin)

    def persist():
        text = json.dumps(record, indent=2) + "\n"
        result_path.write_text(text, encoding="utf-8")
        latest.write_text(text, encoding="utf-8")

    def passed(label):
        record["checks"].append(label)
        print("PASS: " + label, flush=True)
        persist()

    def docker(*args, check=True):
        completed = subprocess.run(["docker", *args], capture_output=True, text=True)
        if check and completed.returncode:
            raise RuntimeError("Docker " + args[0] + " failed (output suppressed to protect generated credentials)")
        return completed

    env = {**os.environ, **config}
    empty = private_dir / "empty.env"
    empty.write_text("", encoding="utf-8")
    realm = json.loads((ROOT / "keycloak/agrosphere-realm.json").read_text(encoding="utf-8"))
    realm.update(ssoSessionIdleTimeout=1800, ssoSessionMaxLifespan=1800, accessTokenLifespan=300)
    native_client = {"clientId": "agrosphere-immersive", "name": "M5 owned desktop fixture", "enabled": True,
                     "publicClient": True, "standardFlowEnabled": True, "directAccessGrantsEnabled": False,
                     "implicitFlowEnabled": False, "serviceAccountsEnabled": False,
                     "redirectUris": ["http://127.0.0.1:49152/oauth/callback"], "webOrigins": [],
                     "defaultClientScopes": ["agrosphere-api"], "optionalClientScopes": [],
                     "attributes": {"pkce.code.challenge.method": "S256", "client.session.idle.timeout": "1800",
                                    "client.session.max.lifespan": "1800"}}
    assert not any(c["clientId"] == "agrosphere-immersive" for c in realm["clients"])
    realm["clients"].append(native_client)
    realm_file = private_dir / "agrosphere-realm.json"
    realm_file.write_text(json.dumps(realm), encoding="utf-8")
    override = private_dir / "override.yaml"
    realm_mount = json.dumps(realm_file.as_posix() + ":/opt/keycloak/data/import/agrosphere-realm.json:ro")
    override.write_text("services:\n" + "".join(f"  {name}:\n    ports: !override []\n" for name in ("postgres", "rabbitmq"))
                        + f"  jaeger:\n    image: {project}-jaeger\n    ports: !override []\n"
                        + f"  otel-collector:\n    image: {project}-otel-collector\n    ports: !override []\n"
                        + f"  keycloak:\n    ports: !override [\"127.0.0.1:{oidc_port}:8080\"]\n    volumes: !override [{realm_mount}]\n"
                        + f"  gateway:\n    ports: !override [\"127.0.0.1:{gateway_port}:8080\"]\n", encoding="utf-8")
    command = ["docker", "compose", "--project-name", project, "--env-file", str(empty), "-f", str(ROOT / "compose.yaml"),
               "-f", str(override), "--profile", "apps"]

    def compose(*args, check=True, environment=None, input_text=None):
        completed = subprocess.run([*command, *args], cwd=ROOT, env={**env, **(environment or {})}, input=input_text,
                                   capture_output=True, text=True)
        if check and completed.returncode:
            if args[0] == "build":
                # Independent public-source build logs do not contain fixture environment values.
                (target / "build-failure.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
            raise RuntimeError("Owned M5 Compose " + args[0] + " failed; inspect sanitized result or build log")
        return completed

    try:
        persist()
        for resource, arguments in (("containers", ("ps", "-aq")), ("volumes", ("volume", "ls", "-q")), ("networks", ("network", "ls", "-q"))):
            assert not docker(*arguments, "--filter", "label=com.docker.compose.project=" + project).stdout.strip(), "Random project collision: " + resource
        ownership_established = True
        compose("config", "--quiet")
        print("Building independent M5 Estate, Spatial, Gateway and existing observability images...", flush=True)
        compose("build", "estate", "spatial", "gateway", "jaeger", "otel-collector")
        record["images"] = {image: docker("image", "inspect", "--format", "{{.Id}}", image).stdout.strip() for image in images}
        print("Starting owned fixture " + project, flush=True)
        compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "300", "gateway")
        container_ids = compose("ps", "-a", "-q").stdout.split()
        assert container_ids
        for container in container_ids:
            assert docker("inspect", "--format", '{{index .Config.Labels "com.docker.compose.project"}}', container).stdout.strip() == project
        record["containers"] = container_ids
        passed("new project health and exact Compose ownership labels")
        configure(config)
        realm_url = config["OIDC_PUBLIC_URL"] + "/admin/realms/agrosphere"
        # Change only this new fixture's Web client, never the public realm file.
        kc = admin_token(config)
        web_clients, _ = request(realm_url + "/clients?clientId=agrosphere-web", token=kc)
        web_endpoint = realm_url + "/clients/" + web_clients[0]["id"]
        web_client, _ = request(web_endpoint, token=kc)
        web_client.update(redirectUris=[web_origin + "/*"], webOrigins=[web_origin])
        request(web_endpoint, "PUT", web_client, kc, expected=204)

        def user(name, role):
            kc = admin_token(config)
            person = {"username": "m5-" + name + "-" + run[:8], "password": secrets.token_urlsafe(28)}
            request(realm_url + "/users", "POST", {"username": person["username"], "enabled": True, "emailVerified": True,
                    "firstName": "SIMULATED", "lastName": name, "email": person["username"] + "@example.invalid",
                    "credentials": [{"type": "password", "value": person["password"], "temporary": False}]}, kc, expected=201)
            matches, _ = request(realm_url + "/users?exact=true&username=" + person["username"], token=kc)
            person["id"] = matches[0]["id"]
            if role:
                definition, _ = request(realm_url + "/roles/" + role, token=kc)
                request(realm_url + "/users/" + person["id"] + "/role-mappings/realm", "POST", [definition], kc, expected=204)
            return person

        admin, viewer, outsider, no_role = user("admin", "PLATFORM_ADMIN"), user("viewer", "VIEWER"), user("outsider", "VIEWER"), user("no-role", None)
        admin_access = login(config, admin)

        def call(path, method="GET", body=None, token=admin_access, expected=200):
            return request(gateway + "/api/v1" + path, method, body, token, expected=expected)[0]

        estate = call("/estates", "POST", {"estateCode": "M5_" + run[:8], "name": "SIMULATED M5 desktop estate",
                      "countryCode": "MW", "timezone": "Africa/Blantyre", "status": "ACTIVE"}, expected=201)
        foreign = call("/estates", "POST", {"estateCode": "M5_FOREIGN_" + run[:8], "name": "SIMULATED denied estate",
                       "countryCode": "MW", "timezone": "Africa/Blantyre", "status": "ACTIVE"}, expected=201)
        division = call("/estates/" + estate["id"] + "/divisions", "POST", {"estateId": estate["id"], "divisionCode": "M5_D1",
                        "name": "SIMULATED M5 division", "status": "ACTIVE"}, expected=201)
        foreign_division = call("/estates/" + foreign["id"] + "/divisions", "POST", {"estateId": foreign["id"], "divisionCode": "M5_D2",
                                "name": "SIMULATED foreign division", "status": "ACTIVE"}, expected=201)

        def block(scope, div, index):
            return call("/divisions/" + div["id"] + "/blocks", "POST", {"estateId": scope["id"], "divisionId": div["id"],
                        "blockCode": f"M5_B{index:02d}", "name": f"SIMULATED block {index:02d}", "cropType": "RUBBER",
                        "plantedAreaHectares": 1, "plantedTreeCount": 100, "tappableTreeCount": 80, "status": "ACTIVE"}, expected=201)

        blocks = [block(estate, division, i + 1) for i in range(12)]
        foreign_block = block(foreign, foreign_division, 99)
        def assign_owned_scope(person, estate_id):
            # Keycloak user PUT is a representation update; preserve profile fields.
            # A sparse attributes-only PUT can clear required profile fields.
            kc = admin_token(config)
            endpoint = realm_url + "/users/" + person["id"]
            current, _ = request(endpoint, token=kc)
            current["attributes"] = {**current.get("attributes", {}), "estate_ids": [estate_id]}
            request(endpoint, "PUT", current, kc, expected=204)
            checked, _ = request(endpoint, token=kc)
            assert checked.get("firstName") == "SIMULATED" and checked.get("lastName"), "Owned fixture profile not preserved"
            assert checked.get("email") and checked.get("emailVerified"), "Owned fixture verified profile not preserved"

        assign_owned_scope(viewer, estate["id"])
        assign_owned_scope(outsider, foreign["id"])
        assign_owned_scope(no_role, estate["id"])

        def await_reference(scope):
            # Spatial imports are authorized only after its own event consumer sees references.
            # Query only the Spatial-owned database with the Spatial role, not cross-service SQL.
            for _ in range(120):
                query = "SELECT count(*) FROM reference_entity WHERE estate_id='" + scope + "' AND entity_type='BLOCK'"
                count = compose("exec", "-T", "-e", "PGPASSWORD", "postgres", "psql", "-h", "127.0.0.1", "-U", "agrosphere_spatial",
                                "-d", "agrosphere_spatial", "-Atc", query, environment={"PGPASSWORD": config["SPATIAL_DB_PASSWORD"]}).stdout.strip()
                if int(count) >= (12 if scope == estate["id"] else 1):
                    return
                time.sleep(.5)
            raise AssertionError("Spatial-owned reference projection did not settle")

        await_reference(estate["id"])
        await_reference(foreign["id"])

        def geometry(b, index):
            x, y = 35.0 + (index % 4) * .0012, -15.0 + (index // 4) * .0012
            ring = [[x, y], [x + .001, y], [x + .001, y + .001], [x, y + .001], [x, y]]
            return call("/spatial/features", "POST", {"estateId": b["estateId"], "referenceEntityId": b["id"], "referenceEntityType": "BLOCK",
                        "featureCode": b["blockCode"], "geometry": {"type": "Polygon", "coordinates": [ring]}, "srid": 4326,
                        "status": "ACTIVE", "sourceType": "GENERATED", "sourceReference": "M5 owned fixture " + run,
                        "dataProvenance": "SIMULATED"}, expected=201)

        features = [geometry(b, i) for i, b in enumerate(blocks)]
        foreign_feature = geometry(foreign_block, 20)
        viewer_access, outsider_access, no_role_access = login(config, viewer), login(config, outsider), login(config, no_role)
        listing = call("/estates?page=0&size=100", token=viewer_access)
        assert [x["id"] for x in listing["content"]] == [estate["id"]], "Scoped estate listing mismatch"
        assert call("/estates/" + estate["id"], token=viewer_access)["id"] == estate["id"], "Estate detail identity mismatch"
        got_blocks = call("/estates/" + estate["id"] + "/blocks?page=0&size=100", token=viewer_access)
        got_features = call("/spatial/estates/" + estate["id"] + "/features?page=0&size=100", token=viewer_access)
        assert len(got_blocks["content"]) == len(got_features["content"]) == 12, "Expected exactly 12 authorized metadata/geometry blocks"
        persisted_blocks = {b["id"]: b for b in got_blocks["content"]}
        persisted_features = {f["referenceEntityId"]: f for f in got_features["content"]}
        record["postReadTimestampPrecisionChanges"] = []
        for b, feature in zip(blocks, features):
            current = call("/blocks/" + b["id"], token=viewer_access)
            assert current == persisted_blocks[b["id"]], "Block list/detail DTO mismatch"
            changed_fields = {key for key in b if b[key] != current.get(key)}
            assert changed_fields <= {"createdAt", "updatedAt"}, "Block creation/read field mismatch: " + ",".join(sorted(changed_fields))
            if changed_fields:
                # Estate creates Instants before persistence; PostgreSQL retains microseconds.
                from datetime import datetime
                for key in changed_fields:
                    assert abs((datetime.fromisoformat(b[key].replace("Z", "+00:00")) - datetime.fromisoformat(current[key].replace("Z", "+00:00"))).total_seconds()) <= .000002, "Creation/read timestamp exceeds storage precision"
                record["postReadTimestampPrecisionChanges"].append({"blockId": b["id"], "fields": sorted(changed_fields)})
            selected = call("/spatial/blocks/" + b["id"] + "/geometry", token=viewer_access)
            assert selected == persisted_features[b["id"]] == feature, "Spatial create/list/detail DTO mismatch"
            assert selected["referenceEntityId"] == b["id"] and selected["dataProvenance"] == "SIMULATED", "Spatial identity/provenance mismatch"
            assert all(len(p) == 2 for ring in selected["geometry"]["coordinates"] for p in ring), "Expected exactly 2D contract positions"
        passed("six existing read operations, 12 canonical UUID/geometry/provenance agreements")
        for path in ("/estates/" + foreign["id"], "/blocks/" + foreign_block["id"], "/spatial/blocks/" + foreign_block["id"] + "/geometry"):
            call(path, token=viewer_access, expected=403)
        call("/blocks/" + blocks[0]["id"], token=outsider_access, expected=403)
        call("/blocks/" + blocks[0]["id"], token=no_role_access, expected=403)
        call("/spatial/blocks/" + blocks[0]["id"] + "/geometry", token=no_role_access, expected=403)
        call("/estates", token=None, expected=401)
        call("/estates", token="invalid", expected=401)
        call("/estates", "POST", {"estateCode": "DENIED", "name": "DENIED", "countryCode": "MW", "timezone": "Africa/Blantyre", "status": "ACTIVE"}, token=viewer_access, expected=403)
        passed("server-side foreign estate/object, missing role, unsigned/missing token and read-only write denials")
        kc = admin_token(config)
        clients, _ = request(realm_url + "/clients?clientId=agrosphere-immersive", token=kc)
        actual, _ = request(realm_url + "/clients/" + clients[0]["id"], token=kc)
        assert actual["publicClient"] and actual["standardFlowEnabled"] and not actual["directAccessGrantsEnabled"]
        assert actual["redirectUris"] == native_client["redirectUris"] and actual["attributes"]["pkce.code.challenge.method"] == "S256"
        passed("owned native public client: exact loopback redirect, S256, no password grant")
        record.update(status="READY", estateId=estate["id"], deniedEstateId=foreign["id"], blockIds=[b["id"] for b in blocks],
                      geometrySha256=digest(got_features), blockMetadataSha256=digest(got_blocks), nativeClientId="agrosphere-immersive",
                      contractSha256={name: hashlib.sha256((ROOT / "tests/contracts" / f"{name}.openapi.json").read_bytes()).hexdigest() for name in ("estate", "spatial")})
        private_file.write_text(json.dumps({"ownership": project, "gateway": gateway, "issuer": record["issuer"],
                                          "viewer": viewer, "outsider": outsider, "noRole": no_role}, indent=2), encoding="utf-8")
        # Generated geometry remains only in the disposable directory and is deleted at teardown.
        (private_dir / "geometry.json").write_text(json.dumps(got_features), encoding="utf-8")
        persist()
        print("M5 fixture ready; nonsecret manifest: " + str(latest), flush=True)
        until = min(time.monotonic() + hold_seconds, started + 14400)
        while time.monotonic() < until and not stop_file.exists():
            time.sleep(.5)
        record["status"] = "PASS"
    except Exception as error:
        record["status"] = "FAIL"
        record["failure"] = {"type": type(error).__name__, "message": str(error)[:400] if isinstance(error, (AssertionError, RuntimeError)) else "See operation category; sensitive output suppressed"}
        raise
    finally:
        # A random newly generated name and exact labels are both required before removal.
        assert project == "agrosphere-m5-" + run[:12]
        containers = docker("ps", "-aq", "--filter", "label=com.docker.compose.project=" + project, check=False)
        labels_ok = ownership_established and containers.returncode == 0
        for container in containers.stdout.split():
            labels_ok = labels_ok and docker("inspect", "--format", '{{index .Config.Labels "com.docker.compose.project"}}', container, check=False).stdout.strip() == project
        if labels_ok:
            down = compose("down", "--volumes", "--remove-orphans", check=False)
            remaining = docker("ps", "-aq", "--filter", "label=com.docker.compose.project=" + project, check=False)
            volumes = docker("volume", "ls", "-q", "--filter", "label=com.docker.compose.project=" + project, check=False)
            networks = docker("network", "ls", "-q", "--filter", "label=com.docker.compose.project=" + project, check=False)
            clean = down.returncode == remaining.returncode == volumes.returncode == networks.returncode == 0 and not remaining.stdout.strip() and not volumes.stdout.strip() and not networks.stdout.strip()
            record["cleanup"] = "PASS" if clean else "FAILED"
            # Remove only tags created by this run, never global caches or base images.
            for image in images:
                docker("image", "rm", image, check=False)
        else:
            record["cleanup"] = "BLOCKED: Docker unavailable or ownership check failed"
        # Delete only known files in this new resolved temporary directory; no recursive deletion.
        expected_parent = Path(tempfile.gettempdir()).resolve()
        assert private_dir.resolve().parent == expected_parent and private_dir.name.startswith(project + "-")
        for filename in ("generated-users.json", "geometry.json", "empty.env", "agrosphere-realm.json", "override.yaml", "stop"):
            (private_dir / filename).unlink(missing_ok=True)
        private_dir.rmdir()
        record["privateFilesRemoved"] = True
        persist()
        print("Owned M5 cleanup: " + record["cleanup"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hold-seconds", type=int, default=0)
    parser.add_argument("--web-origin", default="http://localhost:54200")
    args = parser.parse_args()
    main(args.hold_seconds, args.web_origin)
