"""One new base platform shared by the approved POC-CLOSE scenario."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import yaml

from poc_close_owner import Owner, ROOT, LABEL, execute
from verify_tapping import free_port, exercise
from poc_close_faults import FaultAdapter


class Override(list):
    pass


class Dumper(yaml.SafeDumper):
    pass


Dumper.add_representer(Override, lambda dumper, value: dumper.represent_sequence('!override', value))


class Platform(Owner):
    def prepare(self):
        self.preflight()
        for service in ('estate', 'spatial', 'operations', 'gateway', 'telemetry', 'analytics', 'ai'):
            repo = 'api-gateway' if service == 'gateway' else service + '-service'
            self.docker('build', '-t', self.project + '-' + service, str(ROOT.parent / ('agrosphere-' + repo)))
            self.phase('independent declared-dependency image: ' + service)
        ports = [free_port() for _ in range(5)]
        assert len(set(ports)) == 5
        self.oidc_port, self.gateway_port, self.web_port, self.identity_backend, self.gateway_backend = ports
        keys = ['POSTGRES_ADMIN_PASSWORD', 'ESTATE_DB_PASSWORD', 'SPATIAL_DB_PASSWORD', 'OPERATIONS_DB_PASSWORD',
                'OPERATIONS_APP_DB_PASSWORD', 'TELEMETRY_DB_PASSWORD', 'ANALYTICS_DB_PASSWORD', 'AI_DB_PASSWORD',
                'KEYCLOAK_DB_PASSWORD', 'KEYCLOAK_ADMIN_PASSWORD', 'RABBITMQ_PASSWORD']
        self.config = {key: secrets.token_urlsafe(28) for key in keys}
        self.config.update(COMPOSE_PROJECT_NAME=self.project, OIDC_PUBLIC_URL=f'http://127.0.0.1:{self.oidc_port}',
                           CORS_ALLOWED_ORIGINS=f'http://localhost:{self.web_port}', GATEWAY_RATE_LIMIT='1000',
                           TRACING_SAMPLE_PROBABILITY='0')
        for service in ('estate', 'spatial', 'operations', 'gateway'):
            self.config[service.upper() + '_IMAGE'] = self.project + '-' + service
        system_keys = ('PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC', 'USERPROFILE',
                       'APPDATA', 'LOCALAPPDATA', 'PROGRAMDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)',
                       'PROGRAMW6432', 'COMMONPROGRAMFILES', 'COMMONPROGRAMFILES(X86)', 'HOMEDRIVE', 'HOMEPATH')
        self.environment = {k: os.environ[k] for k in system_keys if k in os.environ}
        self.environment.update(self.config)
        self.override = self.private / 'override.yaml'
        empty = self.private / 'empty.env'
        empty.write_text('')
        realm = json.loads((ROOT / 'keycloak/agrosphere-realm.json').read_text())
        realm.update(ssoSessionIdleTimeout=1800, ssoSessionMaxLifespan=1800, accessTokenLifespan=300)
        realm['clients'].append({'clientId': 'agrosphere-immersive', 'name': 'Owned POC-CLOSE desktop',
            'enabled': True, 'publicClient': True, 'standardFlowEnabled': True,
            'directAccessGrantsEnabled': False, 'implicitFlowEnabled': False, 'serviceAccountsEnabled': False,
            'redirectUris': ['http://127.0.0.1:49152/oauth/callback'], 'webOrigins': [],
            'defaultClientScopes': ['agrosphere-api'], 'optionalClientScopes': [],
            'attributes': {'pkce.code.challenge.method': 'S256'}})
        realm_file = self.private / 'realm.json'
        realm_file.write_text(json.dumps(realm))
        (self.private / 'faults.json').write_text('[]')
        public = yaml.safe_load((ROOT / 'compose.yaml').read_text())
        # Compose itself supplies its reserved project label; custom overrides
        # may set only our independent full-run label.
        labels = {LABEL: self.run}
        self.spec = {'services': {name: {'labels': labels, 'pull_policy': 'never'} for name in public['services']},
                     'volumes': {name: {'labels': labels} for name in public['volumes']},
                     'networks': {'default': {'labels': labels}}}
        for name in ('postgres', 'rabbitmq', 'mosquitto', 'jaeger', 'otel-collector'):
            self.spec['services'][name]['ports'] = Override([])
        for service, ref in [('postgres', 'postgis/postgis:17-3.6'), ('rabbitmq', 'rabbitmq:4.3.6-management'),
                             ('keycloak', 'quay.io/keycloak/keycloak:26.5.7'), ('rabbitmq-init', 'python:3.12-alpine')]:
            self.spec['services'][service]['image'] = self.record['inputs'][ref]['id']
        for name in ('jaeger', 'otel-collector'):
            info = json.loads(execute(['docker', 'image', 'inspect', f'agrosphere-{name}:0.2.0']).stdout)[0]
            self.record['inputs'][name] = {'id': info['Id'], 'digests': info.get('RepoDigests', [])}
            self.spec['services'][name]['image'] = info['Id']
        for service in ('estate', 'spatial', 'operations', 'gateway'):
            self.spec['services'][service]['image'] = self.record['images'][self.project + '-' + service]
        self.spec['services']['keycloak'].update(ports=Override([f'127.0.0.1:{self.identity_backend}:8080']),
            volumes=Override([realm_file.as_posix() + ':/opt/keycloak/data/import/agrosphere-realm.json:ro']))
        self.spec['services']['gateway']['ports'] = Override([f'127.0.0.1:{self.gateway_backend}:8080'])
        self.write_override()
        self.inventory_copies()
        self.command = ['docker', 'compose', '--project-name', self.project, '--env-file', str(empty),
                        '-f', str(ROOT / 'compose.yaml'), '-f', str(self.override), '--profile', 'apps']
        self.record.update(gateway=f'http://127.0.0.1:{self.gateway_port}',
                           issuer=f'http://127.0.0.1:{self.oidc_port}/realms/agrosphere',
                           webOrigin=self.config['CORS_ALLOWED_ORIGINS'], stopFile=str(self.private / 'stop'))
        browsers = [Path(os.environ['PROGRAMFILES(X86)']) / 'Microsoft/Edge/Application/msedge.exe',
                    Path(os.environ['PROGRAMFILES']) / 'Google/Chrome/Application/chrome.exe']
        installed = next((path for path in browsers if path.is_file()), None)
        if installed:
            from poc_close_owner import sha
            self.record.update(browserExecutable=str(installed), browserExecutableSha256=sha(installed))
        self.persist()
        self.compose('config', '--quiet')
        self.phase('exact labelled topology, local image identities, native registration and cleanup preflight')

    def write_override(self):
        self.override.write_text(yaml.dump(self.spec, Dumper=Dumper, sort_keys=False))

    def compose(self, *parts, check=True, environment=None, input_text=None):
        self.check_lifetime()
        args = list(parts)
        if args[0] in ('up', 'run') and '--pull' not in args:
            args[1:1] = ['--pull', 'never']
        try:
            result = execute([*self.command, *args], check=False, input_text=input_text,
                             env={**self.environment, **(environment or {})}, owner=self)
        except subprocess.TimeoutExpired as error:
            if args[0] in ('config', 'up'):
                safe = (error.stdout or b'') + (error.stderr or b'') if isinstance(error.stdout or error.stderr, bytes) else (error.stdout or '') + (error.stderr or '')
                if isinstance(safe, bytes):
                    safe = safe.decode('utf-8', errors='replace')
                for key, value in self.config.items():
                    if 'PASSWORD' in key:
                        safe = safe.replace(value, '[REDACTED]')
                self.record['composeTimeout'] = {'operation': args[0], 'safeSummary': safe[-6000:]}
                self.persist()
            raise
        if check and result.returncode:
            if args[0] in ('config', 'up'):
                safe = result.stderr
                for key, value in self.config.items():
                    if 'PASSWORD' in key:
                        safe = safe.replace(value, '[REDACTED]')
                self.record['composeFailure'] = {'operation': args[0], 'safeSummary': safe[-4000:]}
                self.persist()
            raise RuntimeError('Owned Compose operation failed: ' + args[0])
        if args[0] in ('up', 'run', 'stop', 'start', 'restart'):
            self.snapshot()
        return result

    def enable_alerts(self, subjects, privacy):
        self.spec['services']['operations']['environment'] = {
            'OPERATIONS_ALERTS_GENERATEDTESTMODE': 'false' if privacy else 'true',
            'OPERATIONS_ALERTS_PRIVACYGENERATEDTESTMODE': 'true' if privacy else 'false',
            'OPERATIONS_ALERTS_GENERATEDSUBJECTS': ','.join(subjects)}
        self.write_override()
        self.compose('up', '-d', '--no-deps', '--no-build', '--wait', '--wait-timeout', '90', 'operations')

    def platform_runner(self, extra_acceptance=None, extra_environment=None):
        # Nested legacy helpers must join this context rather than allocating one.
        if extra_environment:
            assert set(extra_environment) <= {'CORS_ALLOWED_ORIGINS'}
        assert self.record['runtimeStartedUtc'] is None
        self.start_runtime()
        self.adapters = [FaultAdapter(port=self.gateway_port, upstream_port=self.gateway_backend, scope='gateway', private=self.private),
                         FaultAdapter(port=self.oidc_port, upstream_port=self.identity_backend, scope='identity', private=self.private)]
        for adapter in self.adapters:
            adapter.start()
        self.compose('up', '-d', '--no-build', '--wait', '--wait-timeout', '240', 'operations', 'gateway')
        self.phase('base services healthy in one owned project')
        exercise(self.config, self.compose, extra_acceptance, self.override, self.project, self.gateway_port, owner=self)

    def cleanup(self):
        for adapter in getattr(self, 'adapters', []):
            adapter.close()
        self.record['faultAdaptersStopped'] = True
        super().cleanup()
