"""ANL-01: generated-only real platform drill. Never discovers private configuration.

All provisioning uses verify_tapping's new project, admin and credentials. Raw
source envelopes stay in RAM/bounded owned queues; retained evidence is minimal.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import uuid
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from platform_support import ROOT, request, admin_token
from verify_tapping import main as verify_platform, free_port
from verify_collections import collections


def digest(value):
    return hashlib.sha256(value).hexdigest()


def docker(*args, input_text=None, check=True):
    value = subprocess.run(['docker', *args], input=input_text, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if check and value.returncode:
        raise RuntimeError('Owned Analytics Docker operation failed: ' + args[0])
    return value


def main(extra_acceptance=None):
    record = {'status': 'NOT_RUN', 'scope': 'SIMULATED owned disposable platform only'}

    def acceptance(**c):
        config, compose = c['config'], c['compose']
        project = config['COMPOSE_PROJECT_NAME']
        assert project.startswith('agrosphere-3a-check-')
        gateway = compose('ps', '-q', 'gateway').stdout.strip()
        for name in ['gateway', 'postgres', 'rabbitmq']:
            container = compose('ps', '-q', name).stdout.strip()
            assert docker('inspect', '-f', '{{index .Config.Labels "com.docker.compose.project"}}', container).stdout.strip() == project
        run = str(uuid.uuid4())
        record.update(project=project, runId=run)
        image = project + '-analytics'
        print('Building independent Analytics image...', flush=True)
        docker('build', '-t', image, str(ROOT.parent / 'agrosphere-analytics-service'))
        runtime, rabbit = 'a' + uuid.uuid4().hex, 'a' + uuid.uuid4().hex
        db_password, rabbit_password = secrets.token_urlsafe(28), secrets.token_urlsafe(28)
        container = None

        def sql(statement, admin=False, as_runtime=False, check=True):
            user = 'agrosphere_admin' if admin else runtime if as_runtime else 'agrosphere_analytics'
            password = config['POSTGRES_ADMIN_PASSWORD'] if admin else db_password if as_runtime else config['ANALYTICS_DB_PASSWORD']
            result = compose('exec', '-T', '-e', 'PGPASSWORD', 'postgres', 'psql', '-h', '127.0.0.1', '-U', user,
                             '-d', 'agrosphere_analytics', '-At', '-v', 'ON_ERROR_STOP=1',
                             environment={'PGPASSWORD': password}, input_text=statement, check=False)
            if check and result.returncode:
                raise RuntimeError('Owned Analytics SQL check failed')
            return result.stdout.strip() if check else result

        def broker(path, method='GET', body=None, principal=None, password=None, expected=200):
            code = '''import os,json,sys,base64,urllib.request,urllib.error
v=json.load(sys.stdin)
auth=(v.get('user') or 'agrosphere')+':'+(v.get('password') or os.environ['RABBITMQ_PASSWORD'])
r=urllib.request.Request('http://rabbitmq:15672/api/'+v['path'],data=None if v['body'] is None else json.dumps(v['body']).encode(),method=v['method'],headers={'Authorization':'Basic '+base64.b64encode(auth.encode()).decode(),'Content-Type':'application/json'})
try: response=urllib.request.urlopen(r,timeout=10)
except urllib.error.HTTPError as error: response=error
with response:
 assert response.status==v['expected'],response.status
 text=response.read();print(text.decode() if text else 'null')
'''
            result = compose('run', '--rm', '--no-deps', '-T', 'rabbitmq-init', 'python', '-c', code,
                             input_text=json.dumps({'path': path, 'method': method, 'body': body, 'user': principal,
                                                    'password': password, 'expected': expected}), check=False)
            if result.returncode:
                raise RuntimeError('Owned Analytics broker check failed: ' + method + ' ' + path)
            return json.loads(result.stdout)

        keys = ['agrosphere.' + name + '.v2' for name in ['LatexCollectionRecorded', 'DrcMeasurementRecorded', 'LatexCollectionAdjusted', 'LatexCollectionVoided']]
        queue = 'agrosphere.analytics.production.v2'
        quarantine = 'agrosphere.analytics.production.quarantine.v1'
        diagnostics = 'agrosphere.analytics.production.diagnostics'
        sink = 'agrosphere.analytics.production.verify'
        try:
            with tempfile.TemporaryDirectory(prefix='agrosphere-anl-platform-') as temporary:
                directory = Path(temporary).resolve()
                (directory / '.generated-analytics-owner').write_text(run)
                sql("CREATE ROLE " + runtime + " LOGIN PASSWORD '" + db_password + "' NOSUPERUSER NOCREATEDB NOCREATEROLE;", admin=True)
                sql("COMMENT ON DATABASE agrosphere_analytics IS 'ANL01:" + run + "'; REVOKE TEMP ON DATABASE agrosphere_analytics FROM PUBLIC; GRANT CONNECT ON DATABASE agrosphere_analytics TO " + runtime + "; GRANT USAGE ON SCHEMA public TO " + runtime + ";")
                broker('exchanges/%2F/' + diagnostics, 'PUT', {'type': 'direct', 'durable': True, 'auto_delete': False, 'internal': False, 'arguments': {}}, expected=201)
                for name, limit in [(queue, 10000), (quarantine, 1000), (sink, 1000)]:
                    broker('queues/%2F/' + name, 'PUT', {'durable': True, 'auto_delete': False, 'arguments': {'x-max-length': limit}}, expected=201)
                broker('bindings/%2F/e/' + diagnostics + '/q/' + quarantine, 'POST', {'routing_key': 'quarantine', 'arguments': {}}, expected=201)
                for name in [queue, sink]:
                    for key in keys:
                        broker('bindings/%2F/e/agrosphere.domain/q/' + name, 'POST', {'routing_key': key, 'arguments': {}}, expected=201)
                broker('users/' + rabbit, 'PUT', {'password': rabbit_password, 'tags': []}, expected=201)
                permissions = {'configure': '^$', 'read': r'^agrosphere\.analytics\.production\.v2$', 'write': r'^agrosphere\.analytics\.production\.diagnostics$'}
                broker('permissions/%2F/' + rabbit, 'PUT', permissions, expected=201)
                assert all(broker('permissions/%2F/' + rabbit)[k] == v for k, v in permissions.items())
                # Management API is unavailable to the consumer principal; AMQP consumption/publish is exercised below.
                broker('queues/%2F/' + quarantine, principal=rabbit, password=rabbit_password, expected=401)
                db_url = 'jdbc:postgresql://postgres:5432/agrosphere_analytics'
                now = datetime.now(timezone.utc)
                manifest = {'runId': run, 'projectId': project, 'createdAt': now.isoformat(), 'expiresAt': (now + timedelta(hours=2)).isoformat(),
                            'dbUrlSha256': digest(db_url.encode()), 'runtimeUser': runtime, 'migrationUser': 'agrosphere_analytics', 'rabbitUser': rabbit,
                            'scopes': [{'estateId': c['estate'], 'blockId': c['block']}]}
                manifest_file = directory / 'manifest.json'
                manifest_file.write_text(json.dumps(manifest), encoding='utf-8')
                environment = {'DB_URL': db_url, 'DB_USER': runtime, 'DB_PASSWORD': db_password, 'DB_MIGRATION_USER': 'agrosphere_analytics',
                               'DB_MIGRATION_PASSWORD': config['ANALYTICS_DB_PASSWORD'], 'RABBITMQ_HOST': 'rabbitmq', 'RABBITMQ_USER': rabbit,
                               'RABBITMQ_PASSWORD': rabbit_password, 'OIDC_ISSUER_URI': config['OIDC_PUBLIC_URL'] + '/realms/agrosphere',
                               'OIDC_JWK_SET_URI': 'http://keycloak:8080/realms/agrosphere/protocol/openid-connect/certs', 'OIDC_AUDIENCE': 'agrosphere-api',
                               'ANALYTICS_DEMO_ENABLED': 'true', 'ANALYTICS_FIXTURE_MANIFEST': '/fixture/manifest.json',
                               'ANALYTICS_FIXTURE_SHA256': digest(manifest_file.read_bytes()), 'ANALYTICS_ESTATE_URL': 'http://estate:8081',
                               'MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_INCLUDE': 'health,info,metrics', 'MANAGEMENT_OTLP_METRICS_EXPORT_ENABLED': 'false',
                               'MANAGEMENT_TRACING_SAMPLING_PROBABILITY': '0', 'DEBUG': 'false'}
                env_file = directory / 'analytics.env'
                env_file.write_text(''.join(k + '=' + v + '\n' for k, v in environment.items()), newline='\n')
                environment['ANALYTICS_FIXTURE_MANIFEST'] = '/app/manifest.json'
                env_file.write_text(''.join(k + '=' + v + '\n' for k, v in environment.items()), newline='\n')
                container = docker('create', '--name', project + '-analytics', '--label', 'agrosphere.anl.run=' + run,
                                   '--network', 'container:' + gateway, '--env-file', str(env_file), image).stdout.strip()
                docker('cp', str(manifest_file), container + ':/app/manifest.json')
                docker('cp', str(directory / '.generated-analytics-owner'), container + ':/app/.generated-analytics-owner')
                docker('start', container)
                for _ in range(90):
                    if sql("SELECT to_regclass('anl_daily')") == 'anl_daily':
                        break
                    time.sleep(1)
                else:
                    raise AssertionError('Owned Analytics migration did not complete')
                sql('GRANT SELECT,INSERT ON anl_receipt,anl_seen_version,anl_issue TO ' + runtime + '; GRANT SELECT,INSERT,UPDATE ON anl_collection,anl_scope,anl_daily TO ' + runtime + ';')
                assert sql('SELECT current_user', as_runtime=True) == runtime
                for statement in ['CREATE TABLE denied(id int)', 'CREATE TEMP TABLE denied(id int)', 'TRUNCATE anl_receipt', "UPDATE anl_receipt SET outcome='APPLIED'", 'DELETE FROM anl_seen_version', 'DELETE FROM anl_issue']:
                    assert sql(statement, as_runtime=True, check=False).returncode != 0
                day = datetime.now(ZoneInfo('Asia/Colombo')).date().isoformat()
                path = '/analytics/estates/' + c['estate'] + '/blocks/' + c['block'] + '/production/daily?from=' + day + '&to=' + day

                def history():
                    return c['call'](path)

                for _ in range(60):
                    try:
                        empty = history()
                        break
                    except Exception:
                        time.sleep(1)
                else:
                    raise AssertionError('Owned Analytics HTTP not ready')
                assert empty['days'][0]['availability'] == 'NONE' and empty['days'][0]['metrics'] is None
                c['call'](path, bearer=c['worker_token'], status=403)
                collections(**c)
                docker('restart', container)  # explicit owned recovery after the source broker outage

                def settled():
                    for _ in range(90):
                        try:
                            value = history()
                            if value['days'][0]['metrics'] and value['days'][0]['metrics']['totalWetLatexKg'] == '3.000':
                                return value
                        except Exception:
                            pass
                        time.sleep(1)
                    raise AssertionError('Generated source events did not materialize')

                value = settled()
                print('PASS: seven real source events materialized after broker/process restart', flush=True)
                metrics = value['days'][0]['metrics']
                assert metrics == {'activeCollectionCount': 2, 'pendingDrcCount': 1, 'calculatedCollectionCount': 1, 'voidedCollectionCount': 1,
                                   'totalWetLatexKg': '3.000', 'pendingWetLatexKg': '2.000', 'calculatedWetLatexKg': '1.000', 'knownDryRubberKg': '0.000', 'isComplete': False}
                assert value['missingSourceVersionCount'] == '0' and value['conflictCount'] == value['unsupportedCount'] == 0
                assert sql('SELECT count(*) FROM anl_receipt') == '7'
                messages = broker('queues/%2F/' + sink + '/get', 'POST', {'count': 100, 'ackmode': 'ack_requeue_false', 'encoding': 'auto'})
                assert len(messages) == 7

                def publish(body, key):
                    assert broker('exchanges/%2F/agrosphere.domain/publish', 'POST', {'properties': {'delivery_mode': 2}, 'routing_key': key, 'payload': body, 'payload_encoding': 'string'})['routed']

                def metric(name):
                    code = '''import json,sys,urllib.request
v=json.load(sys.stdin);r=urllib.request.Request('http://gateway:8085/actuator/metrics/analytics.ingress.'+v['metric'],headers={'Authorization':'Bearer '+v['token']})
with urllib.request.urlopen(r,timeout=10) as response: print(json.dumps(json.load(response)['measurements'][0]['value']))
'''
                    result = compose('run', '--rm', '--no-deps', '-T', 'rabbitmq-init', 'python', '-c', code,
                                     input_text=json.dumps({'metric': name, 'token': c['admin_token']}), check=False)
                    if result.returncode:
                        raise RuntimeError('Owned Analytics metric unavailable')
                    return json.loads(result.stdout)

                def wait_metric(name, minimum):
                    for _ in range(30):
                        if metric(name) >= minimum:
                            return
                        time.sleep(.5)
                    raise AssertionError('Owned Analytics metric did not settle: ' + name)

                before = metric('duplicates')
                for message in reversed(messages):
                    publish(message['payload'], message['routing_key'])
                wait_metric('duplicates', before + 7)
                assert history()['days'][0]['metrics'] == metrics and sql('SELECT count(*) FROM anl_receipt') == '7'
                print('PASS: exact totals and immutable receipt count', flush=True)
                # Change only a nonretained personal field: immutable full-envelope fingerprint must catch this.
                changed = json.loads(messages[0]['payload'])
                changed['payload']['collection']['workerId'] = 'SIMULATED-CONFLICT'
                publish(json.dumps(changed), messages[0]['routing_key'])
                publish('{"secret":"SIMULATED-POISON-MUST-NOT-BE-RETAINED"}', keys[0])
                # Schema-valid but outside the approved finite transport profile, built only in RAM.
                adjusted = next(message for message in messages if message['routing_key'].endswith('LatexCollectionAdjusted.v2'))
                large = json.loads(adjusted['payload'])
                original_time = large['timestamp']
                large['timestamp'] = original_time[:-1] + ('' if '.' in original_time else '.') + '0' * 262145 + 'Z'
                oversized = json.dumps(large)
                assert datetime.fromisoformat(large['timestamp']) == datetime.fromisoformat(original_time)
                schema_file = ROOT / 'tests/analytics-contracts/LatexCollectionAdjusted.schema.json'
                assert digest(schema_file.read_bytes()) == '985f6d66815682f06ad6e743cea517dcc8e96c99dd91f72f0234c86d7fb32fe1'
                from jsonschema import Draft202012Validator, FormatChecker
                validator = Draft202012Validator(json.loads(schema_file.read_text(encoding='utf-8'), parse_float=Decimal), format_checker=FormatChecker())
                validator.validate(json.loads(oversized, parse_float=Decimal))
                assert len(oversized.encode()) > 262144
                publish(oversized, adjusted['routing_key'])
                # Raw exponent is rejected before any decimal conversion/expansion, even for zero.
                exponent = '{"value":0e2147483647}'
                publish(exponent, keys[0])
                wait_metric('diagnostics', 4)
                poisoned = history()
                assert poisoned['projectionState'] == 'INCOMPLETE' and poisoned['conflictCount'] == 1
                assert poisoned['days'][0]['metrics'] == metrics
                diagnostic_messages = broker('queues/%2F/' + quarantine + '/get', 'POST', {'count': 100, 'ackmode': 'ack_requeue_false', 'encoding': 'auto'})
                assert len(diagnostic_messages) == 4
                reasons = {}
                for message in diagnostic_messages:
                    fields = json.loads(message['payload'])
                    reasons[fields['reason']] = reasons.get(fields['reason'], 0) + 1
                    assert set(fields) <= {'bodySha256', 'reason', 'eventId'} and len(fields['bodySha256']) == 64
                    assert 'SIMULATED-CONFLICT' not in message['payload'] and 'POISON-MUST' not in message['payload']
                    if fields['reason'] == 'ADMISSION_LIMIT':
                        assert set(fields) == {'bodySha256', 'reason'}
                        assert fields['bodySha256'] in {digest(oversized.encode()), digest(exponent.encode())}
                assert reasons == {'ADMISSION_LIMIT': 2, 'INVALID_ENVELOPE': 1, 'SOURCE_EVENT_HAS_ISSUE': 1}
                assert sql('SELECT count(*) FROM anl_receipt') == '7'
                before_pause = history()
                # Remove only the new private diagnostic binding: mandatory return must pause, never ACK poison.
                bindings = broker('bindings/%2F/e/' + diagnostics + '/q/' + quarantine)
                assert len(bindings) == 1
                broker('bindings/%2F/e/' + diagnostics + '/q/' + quarantine + '/' + bindings[0]['properties_key'], 'DELETE', expected=204)
                publish(oversized, adjusted['routing_key'])
                wait_metric('paused', 1)
                for _ in range(20):
                    if broker('queues/%2F/' + queue)['messages'] >= 1:
                        break
                    time.sleep(.5)
                else:
                    raise AssertionError('Paused diagnostic message was not retained')
                broker('bindings/%2F/e/' + diagnostics + '/q/' + quarantine, 'POST', {'routing_key': 'quarantine', 'arguments': {}}, expected=201)
                docker('restart', container)
                settled()
                wait_metric('diagnostics', 1)
                assert metric('paused') == 0
                assert sql('SELECT count(*) FROM anl_receipt') == '7'
                recovered = history()
                for field in ['days', 'sourceVersionSample', 'lastProcessedAt', 'latestSourceEventAt', 'missingSourceVersionCount', 'conflictCount', 'unsupportedCount']:
                    assert recovered[field] == before_pause[field], field
                recovered_diagnostics = broker('queues/%2F/' + quarantine + '/get', 'POST', {'count': 100, 'ackmode': 'ack_requeue_false', 'encoding': 'auto'})
                assert len(recovered_diagnostics) == 1
                assert json.loads(recovered_diagnostics[0]['payload']) == {'bodySha256': digest(oversized.encode()), 'reason': 'ADMISSION_LIMIT'}
                # Corrupt only this new fixture's cache, then rebuild through the guarded internal CLI.
                sql('UPDATE anl_daily SET wet_kg=9,pending_wet_kg=8,calculated_wet_kg=1')
                result = docker('exec', container, 'java', '-Dloader.main=com.agrosphere.analytics.OwnedRebuildMain', '-cp', '/app/app.jar', 'org.springframework.boot.loader.launch.PropertiesLauncher')
                assert 'owned Analytics daily materialization rebuilt' in result.stdout
                assert history()['days'][0]['metrics'] == metrics and sql('SELECT count(*) FROM anl_receipt') == '7'
                print('PASS: exact totals and immutable receipt count', flush=True)
                # Actual generated Code/PKCE/browser flow, served on a new loopback listener by Playwright.
                origin = config['CORS_ALLOWED_ORIGINS']
                kc = admin_token(config)
                clients, _ = request(c['realm'] + '/clients?clientId=agrosphere-web', token=kc)
                client = clients[0]
                client.update(redirectUris=[origin + '/*'], webOrigins=[origin])
                request(c['realm'] + '/clients/' + client['id'], 'PUT', client, token=kc, expected=204)
                browser = directory / 'browser-fixture.json'
                browser.write_text(json.dumps({'runId': run, 'webOrigin': origin, 'gateway': c['base'].removesuffix('/api/v1'),
                                               'oidc': config['OIDC_PUBLIC_URL'], 'username': c['admin']['username'], 'password': c['admin']['password'],
                                               'estateId': c['estate'], 'blockId': c['block'], 'day': day}), encoding='utf-8')
                result = subprocess.run(['node', 'node_modules/@playwright/test/cli.js', 'test', '--project=production-live'], cwd=ROOT.parent / 'agrosphere-web',
                                        env={**os.environ, 'ANALYTICS_LIVE_FIXTURE': str(browser), 'AGRO_NO_PREVIEW': '1'}, capture_output=True, text=True, timeout=180)
                output = result.stdout + result.stderr
                for secret in [db_password, rabbit_password, c['admin']['password'], c['admin_token'], *[v for k, v in config.items() if 'PASSWORD' in k]]:
                    output = output.replace(secret, '[REDACTED]')
                (ROOT / 'target/analytics-browser.log').write_text(output, encoding='utf-8')
                assert result.returncode == 0, 'Owned real Analytics Web check failed; inspect sanitized log'
                record.update(status='PASS', originalSourceEvents=7, duplicateReplay=7, receipts=7, highestRoots=3,
                              exactWetKg='3.000', exactKnownDryKg='0.000', conflictCount=1, malformedSanitized=True,
                              diagnosticFailurePaused=True, explicitRecovery=True, runtimeSqlDenials=True, privateBrokerPermissions=True,
                              cacheRebuild=True, realGeneratedWeb=True, ownerAcceptance='OPEN', manifestSha256=digest(manifest_file.read_bytes()))
                record.update(admissionProfile='APPROVED_FINITE_GENERATED', admissionDiagnostics=2, oversizedSchemaValidation=True,
                              exponentRejectedBeforeArithmetic=True, admissionPauseRecovery=True, admissionNoProjectionMutation=True)
                print('PASS: generated Operations -> broker -> materialized Analytics -> Gateway -> Web; duplicates, outage, diagnostics, restart, rebuild and exact oracle.', flush=True)
                if extra_acceptance:
                    extra_acceptance(**c, analytics_container=container, analytics_sql=sql,
                                     broker=broker, publish=publish, source_messages=messages,
                                     directory=directory, run=run)
        finally:
            if container:
                assert docker('inspect', '-f', '{{index .Config.Labels "agrosphere.anl.run"}}', container).stdout.strip() == run
                docker('rm', '-f', container)
                record['analyticsContainerRemoved'] = True

    try:
        verify_platform(acceptance, extra_environment={'CORS_ALLOWED_ORIGINS': 'http://localhost:' + str(free_port())})
    except Exception:
        record['status'] = 'FAILED'
        raise
    finally:
        project = record.get('project')
        if project:
            for kind in ['ps', 'volume', 'network']:
                args = ['ps', '-aq'] if kind == 'ps' else [kind, 'ls', '-q']
                assert not docker(*args, '--filter', 'label=com.docker.compose.project=' + project).stdout.strip(), 'Owned project cleanup incomplete'
            record['projectResourcesRemoved'] = True
        (ROOT / 'target/analytics-platform.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
