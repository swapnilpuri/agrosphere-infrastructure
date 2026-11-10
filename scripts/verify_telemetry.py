"""Generated-only TLM-01 real platform drill. Never reads developer configuration.

Reuses the disposable 3A harness, preserving its real Keycloak/PKCE/Estate/Gateway
and tapping acceptance. Two additional owned containers share that Gateway's
network namespace; existing stacks and broker/password files are untouched.
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
from datetime import datetime, timedelta, timezone

from platform_support import ROOT
from dev_identity import login
from verify_tapping import main as verify_platform

EVIDENCE = ROOT / 'target/telemetry-platform.json'


def docker(*args, input_text=None, check=True):
    result = subprocess.run(['docker', *args], input=input_text, capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError('Generated telemetry Docker operation failed: ' + args[0])
    return result


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(extra_telemetry=None, evidence_path=None, platform_environment=None):
    owned = []
    record = {'status': 'NOT_RUN', 'scope': 'SIMULATED owned disposable platform only'}

    def acceptance_inner(config, compose, call, estate, block, admin, base, **unused):
        project = config['COMPOSE_PROJECT_NAME']
        assert project.startswith('agrosphere-3a-check-')
        record['project'] = project
        gateway = compose('ps', '-q', 'gateway').stdout.strip()
        assert gateway and docker('inspect', '-f', '{{index .Config.Labels "com.docker.compose.project"}}', gateway).stdout.strip() == project
        image = project + '-telemetry'
        docker('build', '-t', image, str(ROOT.parent / 'agrosphere-telemetry-service'))
        run = str(uuid.uuid4())
        record['run'] = run
        principal, subscriber = 'p' + uuid.uuid4().hex, 's' + uuid.uuid4().hex
        publisher_password, subscriber_password = secrets.token_urlsafe(28), secrets.token_urlsafe(28)
        runtime, runtime_password = 'tlm' + uuid.uuid4().hex, secrets.token_urlsafe(28)
        device = str(uuid.uuid4())
        topic = f'agrosphere/v1/estates/{estate}/devices/{device}/observations'
        now = datetime.now(timezone.utc).replace(microsecond=0)
        timestamp = lambda value: value.isoformat().replace('+00:00', 'Z')
        start, end = timestamp(now - timedelta(hours=1)), timestamp(now + timedelta(hours=1))
        with tempfile.TemporaryDirectory(prefix='agrosphere-tlm-platform-') as temporary:
            directory = Path(temporary).resolve()
            assert directory.name.startswith('agrosphere-tlm-platform-')
            (directory / '.generated-telemetry-owner').write_text(run)
            broker_config = ('listener 1883\nallow_anonymous false\npassword_file /tmp/passwords\nacl_file /tmp/acl\n'
                             'persistence true\npersistence_location /mosquitto/data/\nlog_type error\n'
                             'max_inflight_messages 10\nmax_queued_messages 100\nmessage_size_limit 4096\n'
                             'max_packet_size 8192\nuse_username_as_clientid true\n')
            acl = f'user {principal}\ntopic write {topic}\nuser {subscriber}\ntopic read {topic}\n'
            (directory / 'broker.conf').write_text(broker_config, newline='\n')
            (directory / 'acl').write_text(acl, newline='\n')
            (directory / 'passwords').write_text(f'{principal}:{publisher_password}\n{subscriber}:{subscriber_password}\n', newline='\n')
            (directory / 'subscriber.password').write_text(subscriber_password)
            # Mosquitto clients load authentication from protected config, never CLI passwords.
            (directory / 'mosquitto_pub').write_text(f'-u {principal}\n-P {publisher_password}\n', newline='\n')
            bearer = login(config, admin)
            call('/estates/' + estate, bearer=bearer)
            call('/blocks/' + block, bearer=bearer)
            (directory / 'estate.token').write_text(bearer)
            manifest = {'runId': run, 'host': '127.0.0.1', 'port': 1883, 'clientId': subscriber,
                        'subscriberUser': subscriber, 'passwordFile': 'subscriber.password',
                        'estateTokenFile': 'estate.token', 'aclFile': 'acl', 'aclSha256': digest(directory / 'acl'),
                        'brokerConfigFile': 'broker.conf', 'brokerConfigSha256': digest(directory / 'broker.conf'),
                        'windowStart': start, 'windowEnd': end,
                        'devices': [{'deviceId': device, 'estateId': estate, 'blockId': block, 'publisherPrincipal': principal}]}
            (directory / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            uid = str(os.getuid()) if hasattr(os, 'getuid') else '10001:10001'

            def create(name, image_name, *arguments):
                container = docker('create', '--name', project + '-' + name,
                                   '--label', 'agrosphere.tlm.run=' + run,
                                   '--network', 'container:' + gateway, *arguments, image_name).stdout.strip()
                assert container
                owned.append(container)
                return container

            mqtt = docker('create', '--name', project + '-mqtt', '--label', 'agrosphere.tlm.run=' + run,
                          '--network', 'container:' + gateway, '--entrypoint', 'sh', 'eclipse-mosquitto:2.0.22', '-c',
                          '(test -f /tmp/passwords-hashed || (mosquitto_passwd -U /tmp/passwords && touch /tmp/passwords-hashed)) && chmod 644 /tmp/passwords && exec mosquitto -c /tmp/config').stdout.strip()
            owned.append(mqtt)
            for filename, target in [('broker.conf', '/tmp/config'), ('acl', '/tmp/acl'),
                                     ('passwords', '/tmp/passwords'), ('mosquitto_pub', '/tmp/mosquitto_pub')]:
                docker('cp', str(directory / filename), mqtt + ':' + target)
            docker('start', mqtt)

            def sql(statement, admin_login=False):
                result = compose('exec', '-T', '-e', 'PGPASSWORD', 'postgres', 'psql', '-h', '127.0.0.1',
                                 '-U', 'agrosphere_admin' if admin_login else 'agrosphere_telemetry',
                                 '-d', 'agrosphere_telemetry', '-v', 'ON_ERROR_STOP=1', '-At',
                                 input_text=statement, check=False,
                                 environment={'PGPASSWORD': config['POSTGRES_ADMIN_PASSWORD' if admin_login else 'TELEMETRY_DB_PASSWORD']})
                if result.returncode:
                    raise RuntimeError('Generated telemetry SQL failed')
                return result.stdout.strip()

            sql(f"CREATE ROLE {runtime} LOGIN PASSWORD '{runtime_password}' NOSUPERUSER NOCREATEDB NOCREATEROLE;"
                f"GRANT CONNECT ON DATABASE agrosphere_telemetry TO {runtime};GRANT USAGE ON SCHEMA public TO {runtime};", True)
            env = {'DB_URL': 'jdbc:postgresql://postgres:5432/agrosphere_telemetry', 'DB_USER': runtime,
                   'DB_PASSWORD': runtime_password, 'DB_MIGRATION_USER': 'agrosphere_telemetry',
                   'DB_MIGRATION_PASSWORD': config['TELEMETRY_DB_PASSWORD'],
                   'OIDC_ISSUER_URI': config['OIDC_PUBLIC_URL'] + '/realms/agrosphere', 'OIDC_AUDIENCE': 'agrosphere-api',
                   'OIDC_JWK_SET_URI': 'http://keycloak:8080/realms/agrosphere/protocol/openid-connect/certs',
                   'RABBITMQ_HOST': 'rabbitmq', 'RABBITMQ_USER': 'agrosphere', 'RABBITMQ_PASSWORD': config['RABBITMQ_PASSWORD'],
                   'TELEMETRY_DEMO_ENABLED': 'false', 'TELEMETRY_ESTATE_URL': 'http://estate:8081',
                   'MANAGEMENT_TRACING_ENABLED': 'false'}
            if extra_telemetry:
                # Private, signed-JWT-only backend instrumentation in this new fixture.
                # Gateway exposes no /actuator/metrics route and browser gets no metrics token.
                env['MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_INCLUDE'] = 'health,info,metrics'

            def application(enabled):
                env['TELEMETRY_DEMO_ENABLED'] = 'true' if enabled else 'false'
                env['TELEMETRY_MQTT_ENABLED'] = 'true' if enabled else 'false'
                env['TELEMETRY_OUTBOX_ENABLED'] = 'true' if enabled else 'false'
                env['TELEMETRY_FIXTURE_MANIFEST'] = '/fixture/manifest.json'
                env['TELEMETRY_FIXTURE_SHA256'] = digest(directory / 'manifest.json')
                (directory / 'app.env').write_text(''.join(f'{key}={value}\n' for key, value in env.items()), newline='\n')
                container = create('telemetry', image, '--user', uid, '--env-file', str(directory / 'app.env'),
                                   '--mount', f'type=bind,source={directory},target=/fixture,readonly')
                docker('start', container)
                return container

            telemetry = application(False)
            for _ in range(90):
                if sql("SELECT to_regclass('telemetry_device')") == 'telemetry_device':
                    break
                time.sleep(1)
            else:
                raise RuntimeError('Disposable Telemetry migration did not finish')
            docker('stop', telemetry)
            docker('rm', '--volumes', telemetry)
            owned.remove(telemetry)
            sql(f"GRANT SELECT ON telemetry_device,telemetry_observation,outbox_event TO {runtime};"
                f"GRANT INSERT ON telemetry_observation,outbox_event TO {runtime};"
                f"GRANT UPDATE(attempts,published_at,next_attempt_at) ON outbox_event TO {runtime};"
                f"INSERT INTO telemetry_device VALUES('{device}','{estate}','{block}','{principal}',true,'{run}','{start}','{end}');")
            # Durable bounded sink, with no credentials in CLI or emitted results.
            broker_code = '''import json,os,sys,urllib.request,base64
operation=json.load(sys.stdin)
auth=base64.b64encode(('agrosphere:'+os.environ['RABBITMQ_PASSWORD']).encode()).decode()
req=urllib.request.Request('http://rabbitmq:15672/api/'+operation['path'],method=operation['method'],data=json.dumps(operation['body']).encode(),headers={'Authorization':'Basic '+auth,'Content-Type':'application/json'})
with urllib.request.urlopen(req,timeout=10) as response:
 raw=response.read();print(raw.decode() if raw else 'null')
'''
            def broker_api(path, method, body):
                result = compose('run', '--rm', '--no-deps', '-T', 'rabbitmq-init', 'python', '-c', broker_code,
                                 input_text=json.dumps({'path': path, 'method': method, 'body': body}), check=False)
                if result.returncode:
                    raise RuntimeError('Generated telemetry sink operation failed')
                return json.loads(result.stdout)
            broker_api('queues/%2F/agrosphere.tlm.verify', 'PUT', {'durable': True, 'arguments': {'x-max-length': 10000}})
            broker_api('bindings/%2F/e/agrosphere.domain/q/agrosphere.tlm.verify', 'POST',
                       {'routing_key': 'agrosphere.TelemetryObservationRecorded.v1', 'arguments': {}})
            telemetry = application(True)
            path = f'/telemetry/estates/{estate}/blocks/{block}/latest'
            for _ in range(90):
                try:
                    assert call(path, bearer=bearer)['coverage'] == 'NONE'
                    break
                except Exception:
                    time.sleep(1)
            else:
                raise RuntimeError('Disposable Telemetry did not become query-ready')
            if extra_telemetry:
                outcome = extra_telemetry(config=config, compose=compose, call=call, estate=estate, block=block,
                                          admin=admin, base=base, bearer=bearer, directory=directory, mqtt=mqtt,
                                          channel=manifest, run=run, topic=topic, path=path, broker_api=broker_api)
                record.update(status='PASS', run=run, realKeycloakGatewayEstate=True, **outcome)
                print('PASS: generated TLM-02 publisher/Web acceptance and retained platform checks.', flush=True)
                return
            observation = {'schemaVersion': 1, 'observationId': str(uuid.uuid4()), 'deviceId': device,
                           'estateId': estate, 'blockId': block, 'kind': 'AIR_TEMPERATURE', 'unit': 'CELSIUS',
                           'value': '27.5', 'observedAt': timestamp(datetime.now(timezone.utc).replace(microsecond=0)),
                           'dataProvenance': 'SIMULATED'}
            for _ in range(2):
                docker('exec', '-i', '-e', 'XDG_CONFIG_HOME=/tmp', mqtt, 'mosquitto_pub', '-h', '127.0.0.1',
                       '-t', topic, '-q', '1', '-s', input_text=json.dumps(observation))
            for _ in range(30):
                value = call(path, bearer=bearer)
                if value['coverage'] == 'PARTIAL':
                    break
                time.sleep(.5)
            assert value['readings'][0]['observationId'] == observation['observationId']
            assert value['readings'][0]['value'] == '27.5' and value['dataProvenance'] == 'SIMULATED'
            assert sql('SELECT count(*) FROM telemetry_observation') == '1'
            for _ in range(20):
                if sql('SELECT count(*) FROM outbox_event WHERE published_at IS NOT NULL') == '1':
                    break
                time.sleep(.5)
            else:
                raise AssertionError('Telemetry event not confirmed')
            events = broker_api('queues/%2F/agrosphere.tlm.verify/get', 'POST',
                                {'count': 10, 'ackmode': 'ack_requeue_false', 'encoding': 'auto'})
            assert len(events) == 1
            event = json.loads(events[0]['payload'])
            from jsonschema import Draft202012Validator, FormatChecker
            schema = json.loads((ROOT / 'tests/telemetry-contracts/TelemetryObservationRecorded.schema.json').read_text())
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(event)
            assert event['aggregateId'] == observation['observationId'] and event['payload']['receivedAt'] == event['timestamp']
            assert event['estateId'] == estate and event['blockId'] == block
            record.update(status='PASS', run=run, observationCount=1, confirmedEventCount=1,
                          realKeycloakGatewayEstate=True, duplicateNoSecondEffect=True)
            print('PASS: generated real Keycloak/Gateway/Estate + authenticated MQTT -> Telemetry DB/API/event; duplicate no-op.', flush=True)

    def cleanup_extra():
        for container in reversed(owned):
            inspected = docker('inspect', '-f', '{{index .Config.Labels "agrosphere.tlm.run"}}', container, check=False)
            if inspected.returncode == 0:
                assert inspected.stdout.strip() == record['run']
                docker('rm', '--force', '--volumes', container)
            assert docker('inspect', container, check=False).returncode != 0
    def acceptance(**kwargs):
        try:
            acceptance_inner(**kwargs)
        finally:
            cleanup_extra()

    try:
        verify_platform(extra_acceptance=acceptance, extra_environment=platform_environment)
    except Exception:
        record['status'] = 'FAIL'
        raise
    finally:
        cleanup_extra()
        project = record.get('project')
        if project:
            assert not docker('ps', '-aq', '--filter', 'label=com.docker.compose.project=' + project).stdout.strip()
            assert not docker('volume', 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + project).stdout.strip()
            assert not docker('network', 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + project).stdout.strip()
            record['ownedProjectResourcesAbsent'] = True
        record['ownedExtraContainersRemoved'] = len(owned)
        destination = Path(evidence_path or EVIDENCE).resolve()
        assert destination.parent == (ROOT / 'target').resolve()
        destination.parent.mkdir(exist_ok=True)
        destination.write_text(json.dumps(record, indent=2) + '\n')


if __name__ == '__main__':
    main()
