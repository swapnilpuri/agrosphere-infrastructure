"""M4 generated-only connected acceptance, nested in the preserved ANL-01 drill.

Never reads existing private configuration or discovers/reuses a running stack.
All secrets/corpora stay in the parent's owned temporary directory and project.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import uuid
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from platform_support import ROOT
from verify_analytics import main as verify_analytics, docker
from dev_identity import login


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main(*, platform_runner=None, owner=None, extra_acceptance=None):
    docker = owner.docker if owner else globals()["docker"]
    evidence_root = owner.path.parent if owner else ROOT / "target"
    record = {"status": "NOT_RUN", "scope": "M4 newly owned SIMULATED disposable project", "ownerAcceptance": "OPEN"}

    def acceptance(**c):
        config, compose, directory, run = c["config"], c["compose"], c["directory"], c["run"]
        project = config["COMPOSE_PROJECT_NAME"]
        assert project.startswith("agrosphere-3a-check-") or owner and project == owner.project
        record.update(project=project, runId=run)
        gateway = compose("ps", "-q", "gateway").stdout.strip()
        assert docker("inspect", "-f", '{{index .Config.Labels "com.docker.compose.project"}}', gateway).stdout.strip() == project
        image, container, generator = project + "-ai", None, None
        runtime, rabbit = "m" + uuid.uuid4().hex, "m" + uuid.uuid4().hex
        db_password, rabbit_password = secrets.token_urlsafe(28), secrets.token_urlsafe(28)
        broker, publish = c["broker"], c["publish"]
        queue, diagnostics, quarantine = "agrosphere.ai.collection.v2", "agrosphere.ai.diagnostics", "agrosphere.ai.quarantine"

        def sql(statement, admin=False, as_runtime=False, check=True):
            user = "agrosphere_admin" if admin else runtime if as_runtime else "agrosphere_ai"
            password = config["POSTGRES_ADMIN_PASSWORD"] if admin else db_password if as_runtime else config["AI_DB_PASSWORD"]
            result = compose("exec", "-T", "-e", "PGPASSWORD", "postgres", "psql", "-h", "127.0.0.1", "-U", user,
                             "-d", "agrosphere_ai", "-At", "-v", "ON_ERROR_STOP=1", environment={"PGPASSWORD": password}, input_text=statement, check=False)
            if check and result.returncode:
                raise RuntimeError("Owned M4 SQL operation failed")
            return result.stdout.strip() if check else result

        def wait(action, expected, label):
            last_error = None
            for _ in range(120):
                try:
                    value = action()
                    if expected(value):
                        return value
                except Exception as error:
                    last_error = error
                time.sleep(.5)
            record['lastWaitFailure'] = {'label': label, 'exceptionType': type(last_error).__name__,
                                         'safeSummary': str(last_error) if isinstance(last_error, AssertionError) else 'See bounded operation status'}
            raise AssertionError("M4 did not settle: " + label)

        def publish_many(messages):
            # One owned admin-tool process; avoid repeated container-start latency and stale sessions.
            code = '''import json,os,sys,urllib.request,base64
messages=json.load(sys.stdin);auth=base64.b64encode(('agrosphere:'+os.environ['RABBITMQ_PASSWORD']).encode()).decode()
for m in messages:
 body={'properties':{'delivery_mode':2},'routing_key':m['routing_key'],'payload':m['payload'],'payload_encoding':'string'}
 req=urllib.request.Request('http://rabbitmq:15672/api/exchanges/%2F/agrosphere.domain/publish',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Basic '+auth})
 with urllib.request.urlopen(req,timeout=10) as response: assert json.load(response)['routed']
print(len(messages))
'''
            result = compose('run', '--rm', '--no-deps', '-T', 'rabbitmq-init', 'python', '-c', code, input_text=json.dumps(messages), check=False)
            if result.returncode:
                raise RuntimeError('Owned M4 batch publication failed')

        def ai_command(*args, check=True, input_text=None):
            result = docker("exec", "-i", container, *args, input_text=input_text, check=False)
            if check and result.returncode:
                raise RuntimeError("Owned M4 application command failed")
            return result

        try:
            print("Building independent M4 AI image...", flush=True)
            public_names = ['main.py', 'adapters/codec.py', 'adapters/store.py', 'adapters/runtime.py', 'adapters/consumer.py', 'domain/baselines.py', 'application/assistant.py', 'sql/m4.sql', 'contracts/RELEASE.json']
            public_root = ROOT.parent / 'agrosphere-ai-service/src/agrosphere_ai'
            source_hashes = {name: sha((public_root / name).read_bytes()) for name in public_names}
            docker("build", "-t", image, str(ROOT.parent / "agrosphere-ai-service"))
            start = datetime.now(ZoneInfo("Asia/Colombo")).date() - timedelta(days=63)
            generator = docker("create", "--name", project + "-m4-generator", "--label", "agrosphere.m4.run=" + run,
                               image, "python", "-m", "agrosphere_ai.adapters.cli", "generate", "--estate", c["estate"], "--block", c["block"],
                               "--timezone", "Asia/Colombo", "--start", start.isoformat(), "--seed", "M4_DEMO_V1", "--output", "/tmp/corpus.json").stdout.strip()
            docker("start", "-a", generator)
            corpus_path = directory / "m4-corpus.json"
            docker("cp", generator + ":/tmp/corpus.json", str(corpus_path))
            docker("rm", generator)
            generator = None
            corpus = json.loads(corpus_path.read_text())
            assert len(corpus["events"]) == 126
            sql("CREATE ROLE " + runtime + " LOGIN PASSWORD '" + db_password + "' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;", admin=True)
            sql("COMMENT ON DATABASE agrosphere_ai IS 'M4:" + run + "'; REVOKE TEMP ON DATABASE agrosphere_ai FROM PUBLIC; GRANT CONNECT ON DATABASE agrosphere_ai TO " + runtime + "; GRANT USAGE ON SCHEMA public TO " + runtime + ";")
            broker("exchanges/%2F/" + diagnostics, "PUT", {"type": "direct", "durable": True, "auto_delete": False, "internal": False, "arguments": {}}, expected=201)
            for name in (queue, quarantine):
                broker("queues/%2F/" + name, "PUT", {"durable": True, "auto_delete": False, "arguments": {"x-max-length": 1000}}, expected=201)
            broker("bindings/%2F/e/" + diagnostics + "/q/" + quarantine, "POST", {"routing_key": "quarantine", "arguments": {}}, expected=201)
            for name in ["LatexCollectionRecorded", "DrcMeasurementRecorded", "LatexCollectionAdjusted", "LatexCollectionVoided"]:
                broker("bindings/%2F/e/agrosphere.domain/q/" + queue, "POST", {"routing_key": "agrosphere." + name + ".v2", "arguments": {}}, expected=201)
            broker("users/" + rabbit, "PUT", {"password": rabbit_password, "tags": []}, expected=201)
            permissions = {"configure": "^$", "read": r"^agrosphere\.ai\.collection\.v2$", "write": r"^agrosphere\.ai\.diagnostics$"}
            broker("permissions/%2F/" + rabbit, "PUT", permissions, expected=201)
            broker("queues/%2F/" + quarantine, principal=rabbit, password=rabbit_password, expected=401)
            dsn = "postgresql://" + runtime + ":" + db_password + "@postgres:5432/agrosphere_ai"
            now = datetime.now(timezone.utc)
            manifest = {"runId": run, "project": project, "createdAt": now.isoformat(), "expiresAt": (owner.record['expiresUtc'] if owner else (now + timedelta(hours=3)).isoformat()),
                        "dsnSha256": sha(dsn.encode()), "dbMarker": "M4:" + run, "runtimeUser": runtime, "migrationUser": "agrosphere_ai",
                        "scopes": [{"estateId": c["estate"], "blockId": c["block"], "timezone": "Asia/Colombo"}],
                        "queue": queue, "diagnostics": diagnostics, "corpusSha256": sha(corpus_path.read_bytes())}
            owner_marker = directory / ".generated-m4-owner"
            owner_marker.write_text(run)
            manifest_path = directory / "m4-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            env = {"AI_BUSINESS_ENABLED": "true", "AI_CONSUMER_ENABLED": "true", "AI_DATABASE_URL": dsn,
                   "DATABASE_URL": "postgresql+psycopg://agrosphere_ai:" + config["AI_DB_PASSWORD"] + "@postgres:5432/agrosphere_ai",
                   "AI_GENERATED_MANIFEST": "/app/m4-manifest.json", "AI_GENERATED_MANIFEST_SHA256": sha(manifest_path.read_bytes()),
                   "AI_AMQP_URL": "amqp://" + rabbit + ":" + rabbit_password + "@rabbitmq:5672/%2F?heartbeat=10&blocked_connection_timeout=5",
                   "ESTATE_SERVICE_URL": "http://estate:8081", "ANALYTICS_SERVICE_URL": "http://localhost:8085",
                   "OIDC_ISSUER_URI": config["OIDC_PUBLIC_URL"] + "/realms/agrosphere", "OIDC_JWK_SET_URI": "http://keycloak:8080/realms/agrosphere/protocol/openid-connect/certs",
                   "OIDC_AUDIENCE": "agrosphere-api"}
            env_file = directory / "m4.env"
            env_file.write_text("".join(k + "=" + v + "\n" for k, v in env.items()), newline="\n")
            container = docker("create", "--name", project + "-ai", "--label", "agrosphere.m4.run=" + run,
                               "--network", "container:" + gateway, "--env-file", str(env_file), image).stdout.strip()
            for file, target in [(manifest_path, "m4-manifest.json"), (owner_marker, ".generated-m4-owner"), (corpus_path, "m4-corpus.json")]:
                docker("cp", str(file), container + ":/app/" + target)
            # Migration runs as the generated migration owner. It independently checks the manifest/DB marker.
            migration = docker("run", "--rm", "--label", "agrosphere.m4.run=" + run, "--network", "container:" + gateway,
                               "--env-file", str(env_file), "--mount", "type=bind,source=" + str(directory) + ",target=/fixture,readonly",
                               "-e", "AI_GENERATED_MANIFEST=/fixture/m4-manifest.json", image, "alembic", "upgrade", "head", check=False)
            if migration.returncode:
                safe = migration.stdout + migration.stderr
                for secret in [db_password, rabbit_password, dsn, *[v for k, v in config.items() if "PASSWORD" in k]]:
                    safe = safe.replace(secret, '[REDACTED]')
                record['migrationFailure'] = {'sanitized': safe[-6000:]}
                raise RuntimeError("Owned M4 migration failed")
            assert sql("SELECT version_num FROM alembic_version") == "0002"
            assert sql("SELECT count(*) FROM outbox_event") == "0"
            sql("GRANT SELECT,INSERT ON ai_source_revision,ai_availability,ai_conflict,ai_dataset,ai_model,ai_evaluation,ai_evaluation_source TO " + runtime + ";")
            for statement in ["CREATE TABLE denied(id int)", "CREATE TEMP TABLE denied(id int)", "TRUNCATE ai_source_revision", "DELETE FROM ai_model", "UPDATE ai_dataset SET corpus_hash='bad'"]:
                assert sql(statement, as_runtime=True, check=False).returncode != 0
            docker("start", container)
            imported = wait(lambda: ai_command("python", "-m", "agrosphere_ai.adapters.cli", "import-generated", "--corpus", "/app/m4-corpus.json", check=False), lambda r: r.returncode == 0, "generated import")
            dataset_id = json.loads(imported.stdout)["datasetId"]
            assert json.loads(ai_command("python", "-m", "agrosphere_ai.adapters.cli", "import-generated", "--corpus", "/app/m4-corpus.json").stdout)["datasetId"] == dataset_id
            evaluation_id = sql("SELECT evaluation_id FROM ai_evaluation")
            assert len(evaluation_id) == 64
            assert sql("SELECT count(*) FROM ai_model") == "4" and sql("SELECT count(*) FROM ai_evaluation_source") == "126"
            hash_code = "import json,hashlib; from importlib.resources import files; names=json.loads(input()); p=files('agrosphere_ai'); print(json.dumps({n:hashlib.sha256(p.joinpath(n).read_bytes()).hexdigest() for n in names}))"
            assert json.loads(ai_command('python', '-c', hash_code, input_text=json.dumps(public_names)).stdout) == source_hashes
            record['packagedSourceHashes'] = source_hashes
            # The seven actual Operations outbox envelopes are replayed unchanged after AI binds its private queue.
            publish_many([{'payload': m['payload'], 'routing_key': m['routing_key']} for m in c['source_messages']])
            publish_many([{'payload': json.dumps(e['event']), 'routing_key': 'agrosphere.' + e['event']['eventType'] + '.v2'} for e in corpus['events']])
            wait(lambda: sql("SELECT count(*) FROM ai_source_revision"), lambda n: n == "133", "source journal")
            publish_many([{'payload': json.dumps(e['event']), 'routing_key': 'agrosphere.' + e['event']['eventType'] + '.v2'} for e in reversed(corpus['events'])])
            wait(lambda: broker("queues/%2F/" + queue)["messages"], lambda n: n == 0, "reverse duplicate replay")
            assert sql("SELECT count(*) FROM ai_source_revision") == "133"
            # The parent workflow may outlive an access token; obtain fresh generated sessions, never relax expiry.
            original_call = c['call']
            active_token = login(config, c['admin'])
            active_tokens = [active_token]
            refreshed_at = time.monotonic()
            def call(*args, **kwargs):
                nonlocal active_token, refreshed_at
                if time.monotonic() - refreshed_at > 90:
                    active_token = login(config, c['admin']); active_tokens.append(active_token); refreshed_at = time.monotonic()
                kwargs.setdefault('bearer', active_token)
                return original_call(*args, **kwargs)
            c['call'] = call
            c['worker_token'] = login(config, c['worker'])
            target = start + timedelta(days=62)
            zone = ZoneInfo("Asia/Colombo")
            as_of = datetime.combine(target, datetime.min.time(), zone).astimezone(timezone.utc).isoformat()
            label = datetime.combine(target + timedelta(days=1), datetime.min.time(), zone).astimezone(timezone.utc).isoformat()
            path = "/ai/estates/" + c["estate"] + "/blocks/" + c["block"]
            params = {"datasetId": dataset_id, "mode": "GENERATED_POINT_IN_TIME", "asOf": as_of, "labelAsOf": label}
            url = path + "/production/baselines?" + urlencode(params)
            value = wait(lambda: c["call"](url), lambda v: len(v["targets"]) == 2, "Gateway forecast")
            assert value["targets"][0]["predictedKg"] == "68.000" and value["targets"][0]["actualKg"] == "82.000"
            assert all(r["anomalyStatus"] == "FLAGGED" for r in value["targets"])
            c["call"](url, bearer=c["worker_token"], status=403)
            body = {**params, "intent": "ANOMALY_EXPLANATION", "environmentFrom": None, "environmentTo": None}
            answer = c["call"](path + "/assistant", "POST", body)
            assert answer["provider"] == "DETERMINISTIC_EVIDENCE_V1" and answer["status"] == "PARTIAL"  # Parent's deliberate source conflict remains visible.
            model_id = value["targets"][0]["modelId"]
            assert c["call"](path + "/models/" + model_id + "?datasetId=" + dataset_id)["stage"] == "DEMO_ONLY"
            evaluation = c["call"](path + "/evaluations/" + evaluation_id + "?datasetId=" + dataset_id)
            assert len(evaluation["metrics"]) == 12
            record['evaluationMetrics'] = evaluation['metrics']
            record['anomalyCounts'] = evaluation['anomalyCounts']
            record['splitBoundaries'] = evaluation['splitBoundaries']
            record['sourceContracts'] = evaluation['sourceContracts']
            withheld = {**params, "asOf": datetime.combine(start + timedelta(days=3), datetime.min.time(), zone).astimezone(timezone.utc).isoformat()}
            del withheld["labelAsOf"]
            assert c["call"](path + "/production/baselines?" + urlencode(withheld))["targets"][0]["status"] == "INSUFFICIENT_HISTORY"
            live_code = "from agrosphere_ai.adapters.runtime import configured_runtime; from agrosphere_ai.domain.baselines import Scope; import json; r=configured_runtime(); s=r.guard.value['scopes'][0]; print(json.dumps({'datasetId':r.store.live_dataset(Scope(s['estateId'],s['blockId'])).dataset_id}))"
            live_id = json.loads(ai_command("python", "-c", live_code).stdout)["datasetId"]
            live = c["call"](path + "/production/baselines?" + urlencode({**params, "datasetId": live_id, "mode": "LIVE_FIRST_RECEIPT"}))
            assert live["targets"][0]["predictedKg"] is None
            docker("restart", container)
            assert wait(lambda: c["call"](url), lambda v: v == value, "restart frozen forecast") == value
            assert sql("SELECT evaluation_id FROM ai_evaluation") == evaluation_id
            # Force diagnostic confirmation failure; the owned private input must survive, then recover on restart.
            binding = broker("bindings/%2F/e/" + diagnostics + "/q/" + quarantine)[0]
            broker("bindings/%2F/e/" + diagnostics + "/q/" + quarantine + "/" + binding["properties_key"], "DELETE", expected=204)
            publish('{"secret":"SIMULATED-NOT-RETAINED"}', "agrosphere.LatexCollectionRecorded.v2")
            wait(lambda: broker("queues/%2F/" + queue)["messages"], lambda n: n >= 1, "retained unacked diagnostic failure")
            broker("bindings/%2F/e/" + diagnostics + "/q/" + quarantine, "POST", {"routing_key": "quarantine", "arguments": {}}, expected=201)
            docker("restart", container)
            wait(lambda: broker("queues/%2F/" + queue)["messages"], lambda n: n == 0, "explicit diagnostic recovery")
            assert sql("SELECT count(*) FROM ai_source_revision") == "133"
            # Immutable records reject even migration-owner UPDATE; transaction rollback preserves data.
            assert sql("UPDATE ai_model SET body='{}'::jsonb", check=False).returncode != 0
            assert sql("SELECT count(*) FROM ai_model") == "4"
            # Real duplicate concurrency and rollback under the runtime role; no existing-target state involved.
            concurrency_code = '''import json,sys,uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from agrosphere_ai.adapters.runtime import configured_runtime
from agrosphere_ai.adapters.codec import parse_event
r=configured_runtime();e=json.load(sys.stdin);e['eventId']=str(uuid.uuid4());e['aggregateId']=str(uuid.uuid4());e['payload']['collection']['id']=e['aggregateId'];raw=json.dumps(e).encode()
def ingest(_): return r.store.ingest(parse_event(raw,datetime.now(timezone.utc)))
with ThreadPoolExecutor(max_workers=4) as pool: outcomes=list(pool.map(ingest,range(8)))
assert outcomes.count('COMMITTED')==1 and outcomes.count('DUPLICATE')==7,outcomes
with r.store.connection() as c:
 before=c.execute('SELECT count(*) FROM ai_conflict').fetchone()[0]
 c.execute('SAVEPOINT rollback_probe');s=r.guard.value['scopes'][0]
 root=c.execute('SELECT event_id,body_hash FROM ai_source_revision LIMIT 1').fetchone()
 c.execute('INSERT INTO ai_conflict(estate_id,block_id,event_id,body_hash,source_at) VALUES (%s,%s,%s,%s,clock_timestamp()) ON CONFLICT DO NOTHING',(s['estateId'],s['blockId'],root[0],root[1]))
 c.execute('ROLLBACK TO SAVEPOINT rollback_probe')
 assert c.execute('SELECT count(*) FROM ai_conflict').fetchone()[0]==before
print('PASS: one concurrent effect and rollback')
'''
            ai_command('python', '-c', concurrency_code, input_text=json.dumps(corpus['events'][0]['event']))
            assert sql("SELECT count(*) FROM ai_source_revision") == '134'
            changed = json.loads(c['source_messages'][0]['payload'])
            changed['payload']['collection']['workerId'] = 'SIMULATED-M4-CONFLICT'
            publish(json.dumps(changed), c['source_messages'][0]['routing_key'])
            wait(lambda: sql('SELECT count(*) FROM ai_conflict'), lambda n: int(n) >= 1, 'trusted conflict')
            assert c['call'](url) == value and sql('SELECT evaluation_id FROM ai_evaluation') == evaluation_id
            assert sql('SELECT count(*) FROM ai_source_revision') == '135'
            commit_boundary_code = '''import json,sys,uuid,time
from datetime import datetime,timezone,timedelta
from agrosphere_ai.adapters.runtime import configured_runtime
from agrosphere_ai.adapters.codec import parse_event
from agrosphere_ai.adapters.reference_http import Unavailable
from agrosphere_ai.domain.baselines import snapshot
r=configured_runtime();e=json.load(sys.stdin);e['eventId']=str(uuid.uuid4());e['aggregateId']=str(uuid.uuid4());e['payload']['collection']['id']=e['aggregateId'];row=parse_event(json.dumps(e).encode(),datetime.now(timezone.utc))
original=r.store.confirm_available
def interrupt(*args): raise RuntimeError('simulated interruption after source commit')
r.store.confirm_available=interrupt
try:r.store.ingest(row)
except RuntimeError:pass
else:raise AssertionError('Interruption was not exercised')
try:r.store.live_dataset(row.scope)
except Unavailable:pass
else:raise AssertionError('Unconfirmed receipt was exposed')
time.sleep(.02);r.store.confirm_available=original
assert r.store.ingest(row)=='DUPLICATE'
ds=r.store.live_dataset(row.scope);stored=next(v for v in ds.revisions if v.event_id==row.event_id)
assert stored.available_at>stored.first_received_at
assert not any(v.event_id==row.event_id for v in snapshot(ds,stored.first_received_at+timedelta(microseconds=1)).rows)
assert any(v.event_id==row.event_id for v in snapshot(ds,stored.available_at+timedelta(microseconds=1)).rows)
print('PASS: conservative post-commit availability, interruption withholding and recovery')
'''
            ai_command('python', '-c', commit_boundary_code, input_text=json.dumps(corpus['events'][0]['event']))
            assert sql('SELECT count(*) FROM ai_availability') == '136'
            permission_code = '''import os,pika,psycopg
from agrosphere_ai.adapters.runtime import configured_runtime
r=configured_runtime()
try: psycopg.connect(r.guard.dsn.replace('/agrosphere_ai','/agrosphere_estate'),connect_timeout=3)
except psycopg.Error: pass
else: raise AssertionError('Cross-database connection allowed')
for operation in ['configure','domain-write','quarantine-read']:
 c=pika.BlockingConnection(pika.URLParameters(os.environ['AI_AMQP_URL']));ch=c.channel()
 try:
  if operation=='configure': ch.queue_declare(queue='agrosphere.ai.denied.'+r.guard.value['runId'])
  elif operation=='domain-write': ch.basic_publish(exchange='agrosphere.domain',routing_key='agrosphere.LatexCollectionRecorded.v2',body=b'{}');ch.confirm_delivery()
  else: ch.basic_get('agrosphere.ai.quarantine')
 except pika.exceptions.ChannelClosedByBroker as e: assert e.reply_code==403
 else: raise AssertionError('Broker privilege too broad')
 finally:
  if c.is_open:c.close()
print('PASS: database and broker privilege denials')
'''
            ai_command('python', '-c', permission_code)
            c['call'](url.replace(c['estate'], str(uuid.uuid4())), status=403)
            browser_fixture = {"runId": run, "webOrigin": config["CORS_ALLOWED_ORIGINS"], "gateway": c["base"].removesuffix("/api/v1"),
                               "oidc": config["OIDC_PUBLIC_URL"], "username": c["admin"]["username"], "password": c["admin"]["password"],
                               "estateId": c["estate"], "blockId": c["block"], "datasetId": dataset_id, "evaluationId": evaluation_id,
                               "asOf": as_of, "labelAsOf": label, 'workerUsername': c['worker']['username'], 'workerPassword': c['worker']['password']}
            browser = directory / "m4-browser.json"
            browser.write_text(json.dumps(browser_fixture))
            result = (owner.run_browser if owner else subprocess.run)(["node", "node_modules/@playwright/test/cli.js", "test", "--project=m4-live", *(['--output=' + str(owner.private / 'browser-m4-live')] if owner else []), *(['--reporter=list'] if owner else [])], cwd=ROOT.parent / "agrosphere-web",
                                    env={**os.environ, **(owner.browser_environment() if owner else {}), "M4_LIVE_FIXTURE": str(browser), "AGRO_NO_PREVIEW": "1"}, capture_output=True, text=True, timeout=180)
            output = result.stdout + result.stderr
            for secret in [db_password, rabbit_password, c["admin"]["password"], c['worker']['password'], c["admin_token"], *active_tokens, *[v for k, v in config.items() if "PASSWORD" in k]]:
                output = output.replace(secret, "[REDACTED]")
            (evidence_root / "m4-browser.log").write_text(output, encoding="utf-8")
            if owner:
                owner.inventory_copies()
            assert result.returncode == 0, "M4 browser failed; inspect sanitized log"
            assert {name: sha((public_root / name).read_bytes()) for name in public_names} == source_hashes, 'M4 product source changed during verification'
            record.update(status="PASS", sourceFacts=136, generatedDates=63, actualOperationsSourceEvents=7, reverseDuplicates=126,
                          datasetId=dataset_id, evaluationId=evaluation_id, meanWetKg="68.000", actualWetKg="82.000", flaggedTargets=2,
                          withheldGenerated=True, liveReceiptWithheld=True, immutableRegistry=True, explicitPauseRecovery=True,
                          restartStable=True, realGeneratedWeb=True, modelEvaluationRead=True, concurrencyOneEffect=True, transactionRollback=True,
                          trustedConflictFrozenRegistry=True, crossDatabaseDenied=True, privateBrokerDenials=True, crossEstateDenied=True,
                          postCommitAvailability=True, unconfirmedReceiptWithheld=True, confirmationRecovery=True,
                          provider="DETERMINISTIC_EVIDENCE_V1", providerSpendUsd="0")
            print("PASS: M4 Operations/broker/journal/Analytics/Gateway/PKCE/Web; forecasts, anomalies, registry, evidence, withholding and recovery.", flush=True)
            if extra_acceptance:
                extra_acceptance(**c, ai_container=container, ai_record=record, ai_dataset=dataset_id, ai_evaluation=evaluation_id)
        finally:
            for owned in (generator, container):
                if owned:
                    assert docker("inspect", "-f", '{{index .Config.Labels "agrosphere.m4.run"}}', owned).stdout.strip() == run
                    docker("rm", "-f", owned)
            docker("image", "rm", image, check=False)
            record["aiOwnedContainersRemoved"] = True

    try:
        (platform_runner or verify_analytics)(acceptance)
    except Exception:
        record["status"] = "FAILED"
        raise
    finally:
        project = record.get("project")
        if project and not owner:
            for kind in ["ps", "volume", "network"]:
                args = ["ps", "-aq"] if kind == "ps" else [kind, "ls", "-q"]
                assert not docker(*args, "--filter", "label=com.docker.compose.project=" + project).stdout.strip(), "Owned M4 project cleanup incomplete"
            record["projectResourcesRemoved"] = True
        (evidence_root / "m4-platform.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
