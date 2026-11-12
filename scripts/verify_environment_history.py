"""ANL-02: new owned Telemetry/MQTT -> Analytics/Gateway/Web fixture, never private config."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import secrets
import subprocess
import time
import uuid
from platform_support import ROOT, admin_token, request
from verify_tapping import free_port
from verify_telemetry import main as verify_telemetry, docker
from telemetry_simulator import GeneratedPublisher, wire_time, instant

QUEUE = 'agrosphere.analytics.environment.v1'
DIAGNOSTICS = 'agrosphere.analytics.environment.diagnostics'
QUARANTINE = 'agrosphere.analytics.environment.quarantine.v1'
KEY = 'agrosphere.TelemetryObservationRecorded.v1'
SCHEMA_SHA = '78165fefbd980776ac44cb567e8fb213ac4fdd5ac979a4442e7e2d6d545647a6'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main(*, platform_runner=None, owner=None, extra_acceptance=None):
    docker = owner.docker if owner else globals()["docker"]
    evidence_root = owner.path.parent if owner else ROOT / "target"
    record = {'status': 'NOT_RUN', 'scope': 'ANL-02 SIMULATED newly owned disposable only', 'ownerAcceptance': 'OPEN'}

    def acceptance(config, compose, call, estate, block, admin, base, bearer, directory, mqtt, channel, run, topic, path, broker_api):
        project = config['COMPOSE_PROJECT_NAME']; assert project.startswith('agrosphere-3a-check-') or owner and project == owner.project
        record.update(project=project, runId=run)
        gateway = compose('ps', '-q', 'gateway').stdout.strip()
        assert docker('inspect', '-f', '{{index .Config.Labels "com.docker.compose.project"}}', gateway).stdout.strip() == project
        runtime, environment_user, base_user = ['e' + uuid.uuid4().hex for _ in range(3)]
        db_password, environment_password, base_password = [secrets.token_urlsafe(28) for _ in range(3)]
        image = project + '-environment-history'; container = None

        def sql(statement, admin_login=False, as_runtime=False, check=True):
            user = 'agrosphere_admin' if admin_login else runtime if as_runtime else 'agrosphere_analytics'
            password = config['POSTGRES_ADMIN_PASSWORD'] if admin_login else db_password if as_runtime else config['ANALYTICS_DB_PASSWORD']
            result = compose('exec', '-T', '-e', 'PGPASSWORD', 'postgres', 'psql', '-h', '127.0.0.1', '-U', user,
                             '-d', 'agrosphere_analytics', '-At', '-v', 'ON_ERROR_STOP=1', environment={'PGPASSWORD': password}, input_text=statement, check=False)
            if check and result.returncode: raise RuntimeError('Owned environmental SQL check failed')
            return result.stdout.strip() if check else result

        def broker(path, method='GET', body=None, user=None, password=None, expected=200):
            code = '''import os,json,sys,base64,urllib.request,urllib.error
v=json.load(sys.stdin);auth=(v.get('user') or 'agrosphere')+':'+(v.get('password') or os.environ['RABBITMQ_PASSWORD'])
r=urllib.request.Request('http://rabbitmq:15672/api/'+v['path'],method=v['method'],data=None if v['body'] is None else json.dumps(v['body']).encode(),headers={'Authorization':'Basic '+base64.b64encode(auth.encode()).decode(),'Content-Type':'application/json'})
try: response=urllib.request.urlopen(r,timeout=10)
except urllib.error.HTTPError as error: response=error
with response:
 assert response.status==v['expected'],response.status
 raw=response.read();print(raw.decode() if raw else 'null')
'''
            result = compose('run', '--rm', '--no-deps', '-T', 'rabbitmq-init', 'python', '-c', code,
                             input_text=json.dumps({'path': path, 'method': method, 'body': body, 'user': user, 'password': password, 'expected': expected}), check=False)
            if result.returncode: raise RuntimeError('Owned environmental broker operation failed: ' + method + ' ' + path)
            return json.loads(result.stdout)

        def metric(name):
            assert name in ['committed', 'duplicates', 'diagnostics', 'paused']
            code = '''import json,sys,urllib.request
v=json.load(sys.stdin);r=urllib.request.Request('http://gateway:8085/actuator/metrics/analytics.environment.'+v['name'],headers={'Authorization':'Bearer '+v['token']})
with urllib.request.urlopen(r,timeout=10) as response: print(json.dumps(json.load(response)['measurements'][0]['value']))
'''
            result = compose('run', '--rm', '--no-deps', '-T', 'rabbitmq-init', 'python', '-c', code, input_text=json.dumps({'name': name, 'token': bearer}), check=False)
            if result.returncode: raise RuntimeError('Owned environmental private metric unavailable')
            return json.loads(result.stdout)

        def wait_for(action, predicate, label, attempts=60):
            for _ in range(attempts):
                try:
                    result = action()
                    if predicate(result): return result
                except Exception:
                    pass
                time.sleep(.5)
            raise AssertionError('Owned environmental check did not settle: ' + label)

        try:
            print('Building independent ANL-02 Analytics image...', flush=True)
            docker('build', '-t', image, str(ROOT.parent / 'agrosphere-analytics-service'))
            sql("CREATE ROLE " + runtime + " LOGIN PASSWORD '" + db_password + "' NOSUPERUSER NOCREATEDB NOCREATEROLE;", admin_login=True)
            sql("COMMENT ON DATABASE agrosphere_analytics IS 'ANL01:" + run + "'; REVOKE TEMP ON DATABASE agrosphere_analytics FROM PUBLIC; GRANT CONNECT ON DATABASE agrosphere_analytics TO " + runtime + "; GRANT USAGE ON SCHEMA public TO " + runtime + ";")
            for name, secret in [(base_user, base_password), (environment_user, environment_password)]:
                broker('users/' + name, 'PUT', {'password': secret, 'tags': []}, expected=201)
            broker('permissions/%2F/' + base_user, 'PUT', {'configure': '^$', 'read': '^$', 'write': '^$'}, expected=201)
            permissions = {'configure': '^$', 'read': r'^agrosphere\.analytics\.environment\.v1$', 'write': r'^agrosphere\.analytics\.environment\.diagnostics$'}
            broker('permissions/%2F/' + environment_user, 'PUT', permissions, expected=201)
            assert all(broker('permissions/%2F/' + environment_user)[k] == v for k, v in permissions.items())
            broker('exchanges/%2F/' + DIAGNOSTICS, 'PUT', {'type': 'direct', 'durable': True, 'auto_delete': False, 'internal': False, 'arguments': {}}, expected=201)
            for name, limit in [(QUEUE, 10000), (QUARANTINE, 1000)]:
                broker('queues/%2F/' + name, 'PUT', {'durable': True, 'auto_delete': False, 'arguments': {'x-max-length': limit, 'x-overflow': 'reject-publish'}}, expected=201)
            broker('bindings/%2F/e/agrosphere.domain/q/' + QUEUE, 'POST', {'routing_key': KEY, 'arguments': {}}, expected=201)
            broker('bindings/%2F/e/' + DIAGNOSTICS + '/q/' + QUARANTINE, 'POST', {'routing_key': 'quarantine', 'arguments': {}}, expected=201)
            broker('queues/%2F/' + QUARANTINE, user=environment_user, password=environment_password, expected=401)
            reference = instant(call(path, bearer=bearer)['generatedAt']).replace(microsecond=0)
            start, end = wire_time(reference - timedelta(seconds=150)), wire_time(reference + timedelta(seconds=1))
            db_url = 'jdbc:postgresql://postgres:5432/agrosphere_analytics'; now = datetime.now(timezone.utc)
            manifest = {'runId': run, 'projectId': project, 'createdAt': now.isoformat(), 'expiresAt': (owner.record['expiresUtc'] if owner else (now + timedelta(hours=2)).isoformat()),
                        'dbUrlSha256': digest(db_url.encode()), 'runtimeUser': runtime, 'migrationUser': 'agrosphere_analytics', 'rabbitUser': base_user,
                        'environmentRabbitUser': environment_user, 'environmentQueue': QUEUE, 'environmentSchemaSha256': SCHEMA_SHA,
                        'environmentWindowFrom': start, 'environmentWindowTo': end, 'scopes': [{'estateId': estate, 'blockId': block}]}
            manifest_file = directory / 'analytics-manifest.json'; manifest_file.write_text(json.dumps(manifest), encoding='utf-8')
            marker = directory / '.generated-analytics-owner'; marker.write_text(run)
            environment = {'DB_URL': db_url, 'DB_USER': runtime, 'DB_PASSWORD': db_password, 'DB_MIGRATION_USER': 'agrosphere_analytics',
                'DB_MIGRATION_PASSWORD': config['ANALYTICS_DB_PASSWORD'], 'RABBITMQ_HOST': 'rabbitmq', 'RABBITMQ_USER': base_user, 'RABBITMQ_PASSWORD': base_password,
                'ANALYTICS_ENVIRONMENT_RABBIT_USER': environment_user, 'ANALYTICS_ENVIRONMENT_RABBIT_PASSWORD': environment_password,
                'OIDC_ISSUER_URI': config['OIDC_PUBLIC_URL'] + '/realms/agrosphere', 'OIDC_JWK_SET_URI': 'http://keycloak:8080/realms/agrosphere/protocol/openid-connect/certs',
                'OIDC_AUDIENCE': 'agrosphere-api', 'ANALYTICS_DEMO_ENABLED': 'true', 'ANALYTICS_ENVIRONMENT_ENABLED': 'true', 'ANALYTICS_INGESTION_ENABLED': 'false',
                'ANALYTICS_FIXTURE_MANIFEST': '/app/analytics-manifest.json', 'ANALYTICS_FIXTURE_SHA256': digest(manifest_file.read_bytes()), 'ANALYTICS_ESTATE_URL': 'http://estate:8081',
                'MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_INCLUDE': 'health,info,metrics', 'MANAGEMENT_OTLP_METRICS_EXPORT_ENABLED': 'false', 'MANAGEMENT_TRACING_ENABLED': 'false',
                'DEBUG': 'false', 'LOGGING_LEVEL_ROOT': 'WARN', 'LOGGING_LEVEL_ORG_SPRINGFRAMEWORK_JDBC': 'WARN', 'LOGGING_LEVEL_ORG_SPRINGFRAMEWORK_WEB': 'WARN'}
            env_file = directory / 'analytics.env'; env_file.write_text(''.join(k + '=' + v + '\n' for k, v in environment.items()), newline='\n')
            container = docker('create', '--name', project + '-environment-history', '--label', 'agrosphere.anl02.run=' + run,
                               '--network', 'container:' + gateway, '--env-file', str(env_file), image).stdout.strip()
            docker('cp', str(manifest_file), container + ':/app/analytics-manifest.json'); docker('cp', str(marker), container + ':/app/.generated-analytics-owner'); docker('start', container)
            wait_for(lambda: sql("SELECT to_regclass('anl_environment_observation')"), lambda x: x == 'anl_environment_observation', 'V3 migration', 180)
            sql('GRANT SELECT,INSERT ON anl_environment_receipt,anl_environment_observation,anl_environment_issue TO ' + runtime + '; GRANT SELECT,INSERT,UPDATE ON anl_environment_scope TO ' + runtime + ';')
            if owner:
                sql('GRANT SELECT ON anl_daily,anl_scope,anl_collection,anl_receipt,anl_seen_version,anl_issue TO ' + runtime + ';')
            assert sql('SELECT current_user', as_runtime=True) == runtime
            for statement in ['CREATE TABLE denied(id int)', 'CREATE TEMP TABLE denied(id int)', 'TRUNCATE anl_environment_receipt', "UPDATE anl_environment_observation SET value_text='1'", 'DELETE FROM anl_environment_receipt', 'DELETE FROM anl_environment_issue']:
                assert sql(statement, as_runtime=True, check=False).returncode != 0
            from urllib.parse import urlencode
            route = '/analytics/estates/' + estate + '/blocks/' + block + '/environment/observations'
            history = lambda: call(route + '?' + urlencode({'from': start, 'to': end}), bearer=bearer)
            empty = wait_for(history, lambda x: x['availability'] == 'NONE', 'empty API')
            assert empty['totalMatchingCount'] == '0'
            call(route + '?' + urlencode({'from': start, 'to': end}), bearer='invalid-generated-token', status=401)
            plan = {'runId': run, 'dataProvenance': 'SIMULATED', 'channelManifest': 'manifest.json', 'channelSha256': digest((directory / 'manifest.json').read_bytes()),
                    'brokerContainerId': mqtt, 'publisherConfigSha256': digest((directory / 'mosquitto_pub').read_bytes()), 'referenceAt': wire_time(reference),
                    'start': start, 'cadenceSeconds': 30, 'sampleCount': 6, 'seed': 'ANL02_FIXED_V1'}
            plan_file = directory / 'environment-publisher-plan.json'; plan_file.write_text(json.dumps(plan), encoding='utf-8')
            if owner and len(channel['devices']) == 2:
                from poc_close_mqtt import publish as publish_two_devices
                publish_two_devices(owner, directory, mqtt, plan, channel)
            else:
                GeneratedPublisher(plan_file, digest(plan_file.read_bytes()), execute=(lambda command, body=None: owner.docker(*command[1:], input_text=body).stdout) if owner else None).publish()
            # Genuine negative temperature and measured soil zero through the unchanged actual MQTT producer.
            for kind, unit, value in [('AIR_TEMPERATURE', 'CELSIUS', '-2.125000'), ('SOIL_MOISTURE', 'PERCENT', '0')]:
                is_soil = owner and len(channel['devices']) == 2 and kind == 'SOIL_MOISTURE'
                selected_device = channel['devices'][1 if is_soil else 0]
                body = {'schemaVersion': 1, 'observationId': str(uuid.uuid4()), 'deviceId': selected_device['deviceId'], 'estateId': estate, 'blockId': block,
                        'kind': kind, 'unit': unit, 'value': value, 'observedAt': wire_time(reference - timedelta(seconds=5)), 'dataProvenance': 'SIMULATED'}
                selected_topic = f"agrosphere/v1/estates/{estate}/devices/{selected_device['deviceId']}/observations"
                docker('exec', '-i', '-e', 'XDG_CONFIG_HOME=' + ('/tmp/soil' if is_soil else '/tmp'), mqtt, 'mosquitto_pub', '-h', '127.0.0.1', '-t', selected_topic, '-q', '1', '-s', input_text=json.dumps(body))
            value = wait_for(history, lambda x: x['totalMatchingCount'] == '20', '20 materialized source facts', 180)
            assert value['returnedKindCounts'] == {'AIR_TEMPERATURE': 7, 'SOIL_MOISTURE': 7, 'INTERVAL_RAINFALL': 6}
            assert not value['truncated'] and value['projectionState'] == 'OBSERVED_ONLY'
            assert any(row['value'] == '-2.125' for row in value['observations']) and any(row['value'] == '0' and row['kind'] == 'SOIL_MOISTURE' for row in value['observations'])
            assert any(row.get('intervalStart', start) < start for row in value['observations'])
            assert sql('SELECT count(*) FROM anl_environment_receipt') == '20'
            messages = broker('queues/%2F/agrosphere.tlm.verify/get', 'POST', {'count': 100, 'ackmode': 'ack_requeue_false', 'encoding': 'auto'})
            assert len(messages) == 20
            from jsonschema import Draft202012Validator, FormatChecker
            schema_file = ROOT / 'tests/telemetry-contracts/TelemetryObservationRecorded.schema.json'
            assert digest(schema_file.read_bytes()) == '43f652fbbe98c6be3e545307a0fc6c50b2ebce0834c986dfe87d5c3bc5a4a2d2'
            validator = Draft202012Validator(json.loads(schema_file.read_text()), format_checker=FormatChecker())
            for message in messages: validator.validate(json.loads(message['payload']))
            emitted = {json.loads(message['payload'])['payload']['observationId']: json.loads(message['payload']) for message in messages}
            for row in value['observations']:
                event = emitted[row['observationId']]
                for key in ['deviceId', 'kind', 'unit', 'value', 'observedAt', 'receivedAt']:
                    # Time spelling may be normalized to the same exact millisecond; value text is preserved.
                    assert (instant(row[key]) == instant(event['payload'][key])) if key.endswith('At') else (row[key] == event['payload'][key]), key
                assert row['sourceEventId'] == event['eventId']
            def publish(body):
                assert broker('exchanges/%2F/agrosphere.domain/publish', 'POST', {'properties': {'delivery_mode': 2}, 'routing_key': KEY, 'payload': body, 'payload_encoding': 'string'})['routed']
            for message in reversed(messages): publish(message['payload'])
            wait_for(lambda: metric('duplicates'), lambda x: x >= 20, 'reversed duplicates')
            assert history()['observations'] == value['observations']
            changed = json.loads(messages[0]['payload']); changed['correlationId'] = str(uuid.uuid4()); publish(json.dumps(changed))
            publish('{"secret":"SIMULATED-POISON-MUST-NOT-BE-RETAINED"}')
            oversized = messages[0]['payload'] + ' ' * 262145; validator.validate(json.loads(oversized)); publish(oversized)
            publish('{"value":0e2147483647}')
            wait_for(lambda: metric('diagnostics'), lambda x: x >= 4, 'sanitized diagnostics')
            conflicted = history(); assert conflicted['conflictCount'] == 1 and conflicted['projectionState'] == 'INCOMPLETE' and conflicted['observations'] == value['observations']
            narrowed = call(route + '?' + urlencode({'from': wire_time(reference + timedelta(seconds=10)), 'to': wire_time(reference + timedelta(seconds=20))}), bearer=bearer)
            assert narrowed['availability'] == 'NONE' and narrowed['conflictCount'] == 1 and narrowed['projectionState'] == 'INCOMPLETE'
            diagnosed = broker('queues/%2F/' + QUARANTINE + '/get', 'POST', {'count': 100, 'ackmode': 'ack_requeue_false', 'encoding': 'auto'})
            assert len(diagnosed) == 4
            for message in diagnosed:
                fields = json.loads(message['payload']); assert set(fields) <= {'bodySha256', 'reason', 'eventId'} and len(fields['bodySha256']) == 64
                assert 'POISON-MUST' not in message['payload']
                if fields['reason'] == 'ADMISSION_LIMIT': assert set(fields) == {'bodySha256', 'reason'}
            assert sorted(json.loads(m['payload'])['reason'] for m in diagnosed) == ['ADMISSION_LIMIT', 'ADMISSION_LIMIT', 'INVALID_ENVELOPE', 'SOURCE_EVENT_HAS_ISSUE']
            bindings = broker('bindings/%2F/e/' + DIAGNOSTICS + '/q/' + QUARANTINE); assert len(bindings) == 1
            broker('bindings/%2F/e/' + DIAGNOSTICS + '/q/' + QUARANTINE + '/' + bindings[0]['properties_key'], 'DELETE', expected=204)
            publish(oversized); wait_for(lambda: metric('paused'), lambda x: x == 1, 'confirm failure pause')
            wait_for(lambda: broker('queues/%2F/' + QUEUE), lambda x: x['messages'] >= 1, 'unacknowledged retention')
            broker('bindings/%2F/e/' + DIAGNOSTICS + '/q/' + QUARANTINE, 'POST', {'routing_key': 'quarantine', 'arguments': {}}, expected=201)
            docker('restart', container); recovered = wait_for(history, lambda x: x['totalMatchingCount'] == '20', 'restart')
            wait_for(lambda: metric('diagnostics'), lambda x: x >= 1, 'explicit recovery')
            for key in ['observations', 'totalMatchingCount', 'lastProcessedAt', 'latestSourceEventAt', 'conflictCount']: assert recovered[key] == conflicted[key], key
            assert sql('SELECT count(*) FROM anl_environment_receipt') == '20'
            rebuilt = docker('exec', container, 'java', '-Dloader.main=com.agrosphere.analytics.OwnedEnvironmentalRebuildMain', '-cp', '/app/app.jar', 'org.springframework.boot.loader.launch.PropertiesLauncher')
            assert 'owned environmental history rebuilt' in rebuilt.stdout
            origin = config['CORS_ALLOWED_ORIGINS']; kc = admin_token(config)
            clients, _ = request(config['OIDC_PUBLIC_URL'] + '/admin/realms/agrosphere/clients?clientId=agrosphere-web', token=kc)
            client = clients[0]; client.update(redirectUris=[origin + '/*'], webOrigins=[origin])
            request(config['OIDC_PUBLIC_URL'] + '/admin/realms/agrosphere/clients/' + client['id'], 'PUT', client, token=kc, expected=204)
            browser = directory / 'environment-browser-fixture.json'
            browser.write_text(json.dumps({'runId': run, 'webOrigin': origin, 'gateway': base.removesuffix('/api/v1'), 'oidc': config['OIDC_PUBLIC_URL'],
                'username': admin['username'], 'password': admin['password'], 'estateId': estate, 'blockId': block, 'from': start, 'to': end}), encoding='utf-8')
            result = (owner.run_browser if owner else subprocess.run)(['node', 'node_modules/@playwright/test/cli.js', 'test', '--project=environment-live', *(['--output=' + str(owner.private / 'browser-environment-live')] if owner else []), *(['--reporter=list'] if owner else [])], cwd=ROOT.parent / 'agrosphere-web',
                env={**os.environ, **(owner.browser_environment() if owner else {}), 'ENVIRONMENT_LIVE_FIXTURE': str(browser), 'AGRO_NO_PREVIEW': '1'}, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
            output = result.stdout + result.stderr
            for secret in [db_password, environment_password, base_password, admin['password'], bearer, kc, *[v for k, v in config.items() if 'PASSWORD' in k]]: output = output.replace(secret, '[REDACTED]')
            (evidence_root / 'environment-browser.log').write_text(output, encoding='utf-8')
            if owner:
                owner.inventory_copies()
            assert result.returncode == 0, 'Generated environmental Web check failed; inspect sanitized log'
            record.update(status='PASS', actualTelemetrySourceEvents=20, exactMatchingCount='20', reversedDuplicateReplay=20, immutableReceiptCount=20,
                negativeTemperatureAndMeasuredZero=True, rainIntervalBeforeWindow=True, scopedConflictOutsideQuery=True, sanitizedDiagnostics=4,
                admissionConfirmationPauseRecovery=True, processRestartStable=True, immutableFactRebuild=True, runtimeSqlDenials=True,
                privateBrokerPermissions=True, actualKeycloakGatewayWeb=True, manifestSha256=digest(manifest_file.read_bytes()))
            print('PASS: generated MQTT/Telemetry -> immutable Analytics -> Gateway/Web, exact evidence/duplicates/conflict/diagnostics/pause/restart/rebuild.', flush=True)
            if extra_acceptance:
                extra_acceptance(config=config, compose=compose, call=call, estate=estate, block=block, admin=admin, base=base, bearer=bearer,
                    directory=directory, run=run, mqtt=mqtt, environment_record=record, environment_container=container, environment_sql=sql, environment_from=start, environment_to=end)
            return {'environmentHistory': True, 'environmentalSourceEvents': 20, 'environmentalMaterializedCount': 20, 'realEnvironmentalWeb': True}
        finally:
            if container:
                assert docker('inspect', '-f', '{{index .Config.Labels "agrosphere.anl02.run"}}', container).stdout.strip() == run
                docker('rm', '--force', '--volumes', container); assert docker('inspect', container, check=False).returncode != 0
                record['analyticsContainerRemoved'] = True
    try:
        (platform_runner or verify_telemetry)(extra_telemetry=acceptance, evidence_path=evidence_root / 'environment-telemetry-platform.json', platform_environment={'CORS_ALLOWED_ORIGINS': 'http://localhost:' + str(free_port())})
    except Exception:
        record['status'] = 'FAILED'; raise
    finally:
        project = record.get('project')
        if project and not owner:
            for kind in ['ps', 'volume', 'network']:
                args = ['ps', '-aq'] if kind == 'ps' else [kind, 'ls', '-q']
                assert not docker(*args, '--filter', 'label=com.docker.compose.project=' + project).stdout.strip(), 'Owned cleanup incomplete'
            record['ownedProjectResourcesAbsent'] = True
        (evidence_root / 'environment-platform.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__': main()
