"""Offline configuration and pinned contracts; no sibling source dependencies."""
import hashlib
import sys
import re
import json
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
compose=yaml.safe_load((ROOT/'compose.yaml').read_text());services=compose['services']
required={'postgres','rabbitmq','rabbitmq-init','keycloak','gateway','estate','spatial','otel-collector','jaeger','operations'}
assert required<=services.keys()
for name in required-{'rabbitmq-init'}:assert services[name].get('healthcheck'),name
for name,service in services.items():
    for port in service.get('ports',[]):assert port.startswith('127.0.0.1:'),(name,port)
    for dependency,condition in service.get('depends_on',{}).items():
        assert dependency in services
        assert condition['condition'] in {'service_healthy','service_completed_successfully'}
for name in ['estate','spatial','operations']:assert not services[name].get('ports')
assert services['estate']['environment']['DB_USER'] != services['spatial']['environment']['DB_USER']
realm=json.loads((ROOT/'keycloak/agrosphere-realm.json').read_text());assert not realm.get('users')
web=realm['clients'][0];assert web['publicClient'] and not web['directAccessGrantsEnabled']
assert web['attributes']['pkce.code.challenge.method']=='S256'
profile=json.loads(realm['components']['org.keycloak.userprofile.UserProfileProvider'][0]['config']['kcUserProfileConfig'][0])
assert next(a for a in profile['attributes'] if a['name']=='estate_ids')['permissions']['edit']==['admin']
mappers=realm['clientScopes'][0]['protocolMappers']
assert {'agrosphere-api','estate-service','spatial-service'}<={m['config'].get('included.custom.audience') for m in mappers}
manifest=json.loads((ROOT/'tests/contracts/manifest.json').read_text())
for name,digest in manifest['files'].items():assert hashlib.sha256((ROOT/'tests/contracts'/name).read_bytes()).hexdigest()==digest,name
for file in (ROOT/'.github/workflows').glob('*.yml'):
    workflow=yaml.load(file.read_text(),Loader=yaml.BaseLoader)
    assert workflow['permissions']['contents']=='read'
public=[c for c in realm['clients'] if c.get('publicClient')]
assert {c['clientId'] for c in public}=={'agrosphere-web','agrosphere-integration-tests'}
for client in public:
    assert client['attributes']['pkce.code.challenge.method']=='S256' and not client['directAccessGrantsEnabled']
assert {c['clientId'] for c in realm['clients'] if c.get('bearerOnly')}=={'agrosphere-api','estate-service','spatial-service','operations-service'}
example=dict(line.split('=',1) for line in (ROOT/'.env.example').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
passwords=[key for key in example if key.endswith('_PASSWORD')]
assert len(passwords)==11 and all('REPLACE' in example[key] for key in passwords)
operation_env=services['operations']['environment']
assert operation_env['DB_USER']=='agrosphere_operations_app'
assert operation_env['FLYWAY_USER']=='agrosphere_operations'
assert operation_env['DB_PASSWORD']!=operation_env['FLYWAY_PASSWORD']
assert 'OPERATIONS_APP_DB_PASSWORD' in services['postgres']['environment']
if '--local' in sys.argv:
    from platform_support import configuration
    local=configuration()
    values=[local.get(key,'') for key in passwords]
    assert all(len(value)>=16 and 'REPLACE' not in value for value in values),'Configure private local passwords; values are not printed'
    assert len(set(values))==len(values),'Use distinct local passwords'
    assert int(local.get('GATEWAY_RATE_LIMIT',120))>0
    assert 0<=float(local.get('TRACING_SAMPLE_PROBABILITY',1))<=1
    for key in ['GATEWAY_MAX_BODY_BYTES','ESTATE_MAX_BODY_BYTES','SPATIAL_MAX_BODY_BYTES']:
        assert 1<=int(local.get(key,2097152))<=16777216
    for key in ['GATEWAY_CONNECT_TIMEOUT','GATEWAY_READ_TIMEOUT']:
        assert re.fullmatch(r'[1-9][0-9]*(?:ms|s|m)',local.get(key,'2s'))
    print('PASS: private local environment is complete, distinct and within configured bounds; secrets omitted')
print('PASS: isolated platform configuration, health dependencies, loopback exposure, trusted identity, pinned contracts and workflows')

assert {"FIELD_WORKER","FIELD_SUPERVISOR","AUDITOR","PLANTATION_ADMIN"}<={r["name"] for r in realm["roles"]["realm"]}
assert "operations-service" in {m["config"].get("included.custom.audience") for m in mappers}

topology=json.loads((ROOT/'rabbitmq/definitions.json').read_text())
sink=next(q for q in topology['queues'] if q['name']=='agrosphere.dev.collections.v2')
assert sink['durable'] and not sink['auto_delete'] and sink['arguments']['x-max-length']==10000
assert {b['routing_key'] for b in topology['bindings'] if b['destination']==sink['name']}=={
    'agrosphere.'+name+'.v2' for name in ['LatexCollectionRecorded','DrcMeasurementRecorded','LatexCollectionAdjusted','LatexCollectionVoided']}
assert len([b for b in topology['bindings'] if b['destination']=='agrosphere.dev.operations.v1'])==6
print('PASS: separate durable bounded collection v2 sink; six tapping v1 bindings retained')

workforce=next(q for q in topology['queues'] if q['name']=='agrosphere.dev.workforce.v1')
assert workforce['durable'] and not workforce['auto_delete'] and workforce['arguments']['x-max-length']==10000
assert {b['routing_key'] for b in topology['bindings'] if b['destination']==workforce['name']}=={
    'agrosphere.'+name+'.v1' for name in ['WorkerRegistrationCreated','WorkerRegistrationChanged','WorkerAttendanceRecorded','WorkerAttendanceChanged']}
print('PASS: separate durable bounded workforce v1 sink; no deployment applied')

assert any(m["protocolMapper"]=="oidc-sub-mapper" and m["config"].get("access.token.claim")=="true" for m in mappers)
