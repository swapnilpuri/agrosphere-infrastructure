"""Offline configuration and pinned contracts; no sibling source dependencies."""
import hashlib
import json
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
compose=yaml.safe_load((ROOT/'compose.yaml').read_text());services=compose['services']
required={'postgres','rabbitmq','rabbitmq-init','keycloak','gateway','estate','spatial','otel-collector','jaeger'}
assert required<=services.keys()
for name in required-{'rabbitmq-init'}:assert services[name].get('healthcheck'),name
for name,service in services.items():
    for port in service.get('ports',[]):assert port.startswith('127.0.0.1:'),(name,port)
    for dependency,condition in service.get('depends_on',{}).items():
        assert dependency in services
        assert condition['condition'] in {'service_healthy','service_completed_successfully'}
for name in ['estate','spatial']:assert not services[name].get('ports')
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
print('PASS: isolated platform configuration, health dependencies, loopback exposure, trusted identity, pinned contracts and workflows')
