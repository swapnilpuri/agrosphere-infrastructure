"""TLM-02 owned publisher + real generated Web/Keycloak platform acceptance."""
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from platform_support import ROOT, admin_token, request
from verify_tapping import free_port
from telemetry_simulator import GeneratedPublisher, digest, instant, wire_time
from verify_telemetry import main as verify_telemetry


def acceptance(config, compose, call, estate, block, admin, base, bearer, directory,
               mqtt, channel, run, topic, path, broker_api):
    reference = instant(call(path, bearer=bearer)['generatedAt'])
    plan = {'runId': run, 'dataProvenance': 'SIMULATED', 'channelManifest': 'manifest.json',
            'channelSha256': digest((directory / 'manifest.json').read_bytes()), 'brokerContainerId': mqtt,
            'publisherConfigSha256': digest((directory / 'mosquitto_pub').read_bytes()),
            'referenceAt': wire_time(reference), 'start': wire_time(reference - timedelta(seconds=150)),
            'cadenceSeconds': 30, 'sampleCount': 6, 'seed': 'TLM02_FIXED_V1'}
    plan_file = directory / 'publisher-plan.json'
    plan_file.write_text(json.dumps(plan), encoding='utf-8')
    fingerprint = digest(plan_file.read_bytes())
    publisher = GeneratedPublisher(plan_file, fingerprint)
    first = publisher.publish()
    # A separate process restarts the identical plan, without saved in-memory identity state.
    restart = subprocess.run([sys.executable, str(ROOT / 'scripts/telemetry_simulator.py'),
                              '--plan', str(plan_file), '--sha256', fingerprint],
                             cwd=ROOT, capture_output=True, text=True, timeout=240)
    if restart.returncode:
        raise RuntimeError('Owned deterministic publisher restart failed')
    second = json.loads(restart.stdout)
    assert first['transportPublished'] == second['transportPublished'] == 18
    metrics_code = '''import json,sys,urllib.request
value=json.load(sys.stdin)
assert value['metric'] in ['accepted','duplicate','rejected','unknown']
url='http://gateway:8084/actuator/metrics/telemetry.ingress.'+value['metric']
request=urllib.request.Request(url,headers={'Authorization':'Bearer '+value['token']})
with urllib.request.urlopen(request,timeout=10) as response:
 print(json.dumps(json.load(response)['measurements']))
'''

    def metric(name):
        response = compose('run', '--rm', '--no-deps', '-T', 'rabbitmq-init', 'python', '-c', metrics_code,
                           input_text=json.dumps({'metric': name, 'token': bearer}), check=False)
        if response.returncode:
            raise RuntimeError('Generated private telemetry metric unavailable')
        return json.loads(response.stdout)[0]['value']

    for _ in range(30):
        if metric('accepted') == 18 and metric('duplicate') == 18:
            break
        time.sleep(.5)
    else:
        raise AssertionError('Transport acknowledgements did not become committed/duplicate domain results')
    assert metric('unknown') == metric('rejected') == 0

    def sql(statement):
        response = compose('exec', '-T', '-e', 'PGPASSWORD', 'postgres', 'psql', '-h', '127.0.0.1',
                           '-U', 'agrosphere_telemetry', '-d', 'agrosphere_telemetry', '-v', 'ON_ERROR_STOP=1', '-At',
                           environment={'PGPASSWORD': config['TELEMETRY_DB_PASSWORD']}, input_text=statement, check=False)
        if response.returncode:
            raise RuntimeError('Generated telemetry readback failed')
        return response.stdout.strip()

    assert sql('SELECT count(*) FROM telemetry_observation') == '18'
    assert sql('SELECT count(DISTINCT observation_id) FROM telemetry_observation') == '18'
    for _ in range(20):
        if sql('SELECT count(*) FROM outbox_event WHERE published_at IS NOT NULL') == '18':
            break
        time.sleep(.5)
    else:
        raise AssertionError('Generated publisher events not confirmed')
    events = broker_api('queues/%2F/agrosphere.tlm.verify/get', 'POST',
                        {'count': 100, 'ackmode': 'ack_requeue_false', 'encoding': 'auto'})
    assert len(events) == 18
    from jsonschema import Draft202012Validator, FormatChecker
    schema = json.loads((ROOT / 'tests/telemetry-contracts/TelemetryObservationRecorded.schema.json').read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    identities = set()
    for message in events:
        event = json.loads(message['payload']); validator.validate(event)
        assert event['aggregateId'] == event['payload']['observationId']
        identities.add(event['aggregateId'])
    assert identities == {x['observationId'] for x in publisher.messages}
    latest = call(path, bearer=bearer)
    assert latest['coverage'] == 'COMPLETE' and len(latest['readings']) == 3
    assert latest['estateId'] == estate and latest['blockId'] == block
    # Only this generated block receives synthetic Spatial geometry through the authoritative API.
    call('/spatial/features', 'POST', {'estateId': estate, 'referenceEntityId': block,
         'referenceEntityType': 'BLOCK', 'featureCode': 'TLM02_GENERATED_BLOCK',
         'geometry': {'type': 'MultiPolygon', 'coordinates': [[[[80, 6], [80.02, 6], [80.02, 6.01], [80, 6.01], [80, 6]]]]},
         'srid': 4326, 'status': 'ACTIVE', 'sourceType': 'GENERATED',
         'sourceReference': 'TLM-02 deterministic disposable geometry; not a survey', 'dataProvenance': 'SIMULATED'},
         bearer=bearer, status=201)
    expected = {r['kind']: r['value'] for r in latest['readings']}
    origin = config['CORS_ALLOWED_ORIGINS']
    realm = config['OIDC_PUBLIC_URL'] + '/admin/realms/agrosphere'
    kc = admin_token(config)
    clients, _ = request(realm + '/clients?clientId=agrosphere-web', token=kc)
    client = clients[0]
    client.update(redirectUris=[origin + '/*'], webOrigins=[origin])
    request(realm + '/clients/' + client['id'], 'PUT', client, token=kc, expected=204)
    fixture = {'runId': run, 'gateway': base.removesuffix('/api/v1'), 'oidc': config['OIDC_PUBLIC_URL'],
               'webOrigin': origin,
               'username': admin['username'], 'password': admin['password'], 'estateId': estate, 'blockId': block,
               'expected': {'temperature': expected['AIR_TEMPERATURE'], 'moisture': expected['SOIL_MOISTURE'],
                            'rainfall': expected['INTERVAL_RAINFALL']}}
    fixture_file = directory / 'browser-fixture.json'
    fixture_file.write_text(json.dumps(fixture), encoding='utf-8')
    web = ROOT.parent / 'agrosphere-web'
    assert (web / 'dist/web/browser/index.html').is_file(), 'Build the independent Web artifact first'
    result = subprocess.run(['node', 'node_modules/@playwright/test/cli.js', 'test', '--project=telemetry-live'],
                            cwd=web, env={**os.environ, 'TELEMETRY_LIVE_FIXTURE': str(fixture_file), 'AGRO_NO_PREVIEW': '1'},
                            capture_output=True, text=True, timeout=180)
    # Trace is disabled; fixture credentials never appear in the log or command arguments.
    log = ROOT / 'target/telemetry-overlay-browser.log'
    output = result.stdout + result.stderr
    for secret in [admin['password'], bearer, *[v for k, v in config.items() if 'PASSWORD' in k]]:
        output = output.replace(secret, '[REDACTED]')
    log.write_text(output, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('Owned real telemetry Web verification failed; inspect sanitized test result')
    print('PASS: 18 deterministic observations + process restart -> 18 duplicates, no second effect; all kinds/events and real Web/PKCE/Spatial overlay.', flush=True)
    return {'deterministicPublisher': True, 'sampleCount': 6, 'observationCount': 18, 'confirmedEventCount': 18,
            'duplicateCount': 18, 'processRestartSamePlan': True, 'realGeneratedWeb': True,
            'planSha256': fingerprint, 'uiTraceDisabled': True, 'ownedWebListenerClosed': True}


if __name__ == '__main__':
    verify_telemetry(extra_telemetry=acceptance, evidence_path=ROOT / 'target/telemetry-overlay-platform.json',
                     platform_environment={'CORS_ALLOWED_ORIGINS': 'http://localhost:' + str(free_port())})
