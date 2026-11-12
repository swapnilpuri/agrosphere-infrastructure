"""Exact ownership and recovery for the approved generated POC-CLOSE fixture.

No developer environment/configuration discovery. A process finally block is not
an unattended expiry guarantee; supervision/recovery remains explicit.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
LABEL = 'agrosphere.poc-close.run'


def process_identity(pid):
    """Windows process creation identity; access uncertainty is never absence."""
    if os.name != 'nt':
        raise RuntimeError('This approved fixture targets Windows process identities')
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return None
        raise PermissionError('Cannot establish operator process identity')
    try:
        exit_code = wintypes.DWORD()
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            raise PermissionError('Cannot establish operator running state')
        if exit_code.value != 259:
            return None
        values = [wintypes.FILETIME() for _ in range(4)]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(v) for v in values)):
            raise PermissionError('Cannot establish operator creation time')
        return (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime
    finally:
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def walk_error(error):
    raise error


def execute(arguments, *, check=True, input_text=None, env=None, timeout=300, owner=None, cwd=ROOT):
    if owner is None:
        result = subprocess.run(arguments, input=input_text, env=env, cwd=cwd,
                                capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=timeout)
    else:
        process = subprocess.Popen(arguments, stdin=subprocess.PIPE if input_text is not None else None,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cwd,
            text=True, encoding='utf-8', errors='replace', creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        identity = process_identity(process.pid)
        entry = {'pid': process.pid, 'started': identity, 'operation': arguments[0] + ' ' + arguments[1], 'completed': False}
        owner.record.setdefault('cliProcesses', []).append(entry)
        owner.persist()
        end = time.monotonic() + timeout
        writer = None
        if input_text is not None:
            stream = process.stdin
            stream.reconfigure(newline='')
            process.stdin = None
            def write_input():
                try:
                    stream.write(input_text)
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    try:
                        stream.close()
                    except (BrokenPipeError, OSError):
                        pass
            writer = threading.Thread(target=write_input, daemon=True)
            writer.start()
        try:
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=min(30, max(.01, end - time.monotonic())))
                    if writer:
                        writer.join(timeout=5)
                        assert not writer.is_alive(), 'Owned input writer did not stop'
                    entry['completed'] = True
                    owner.persist()
                    result = subprocess.CompletedProcess(arguments, process.returncode, stdout, stderr)
                    break
                except subprocess.TimeoutExpired:
                    owner.check_lifetime()
                    if time.monotonic() >= end:
                        raise
        except BaseException:
            if identity is not None and process_identity(process.pid) == identity:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=15)
            process.communicate(timeout=15)
            if writer:
                writer.join(timeout=5)
            entry['completed'] = process.poll() is not None
            owner.persist()
            raise
    if check and result.returncode:
        # Neither Docker inspection, environment values nor failed SQL are logged.
        raise RuntimeError('Owned command failed: ' + arguments[0] + ' ' + arguments[1])
    return result


class Owner:
    def __init__(self, manifest=None):
        if manifest:
            self.path = Path(manifest).resolve(strict=True)
            self.record = json.loads(self.path.read_text(encoding='utf-8'))
            self.run = self.record['runId']
            assert re.fullmatch('[a-f0-9]{32}', self.run)
            assert self.path == ROOT / 'target/poc-close' / self.run / 'owner.json'
            self.project = 'agrosphere-poc-close-' + self.run
            assert self.record['project'] == self.project
            self.private = Path(self.record['privateDirectory']).resolve()
            assert self.private.parent == Path(tempfile.gettempdir()).resolve()
            assert self.private.name.startswith(self.project + '-')
            operator = self.record['operatorProcess']
            assert process_identity(operator['pid']) != operator['started'], 'Active verifier must stop through its sentinel'
            self.recovery = True
        else:
            self.run = uuid.uuid4().hex
            self.project = 'agrosphere-poc-close-' + self.run
            self.path = ROOT / 'target/poc-close' / self.run / 'owner.json'
            self.path.parent.mkdir(parents=True, exist_ok=False)
            self.private = Path(tempfile.mkdtemp(prefix=self.project + '-')).resolve()
            (self.private / '.poc-close-owner').write_text(self.run)
            self.record = {'runId': self.run, 'project': self.project,
                           'privateDirectory': str(self.private), 'status': 'PREPARING',
                           'createdUtc': datetime.now(timezone.utc).isoformat(),
                           'runtimeStartedUtc': None, 'expiresUtc': None,
                           'images': {}, 'inputs': {}, 'resources': {}, 'phases': [], 'copyInventory': [],
                           'cleanup': 'NOT_RUN', 'ownerAcceptance': 'OPEN',
                           'supervision': 'Active session; <=5min checks. No unattended deletion guarantee.'}
            self.record['operatorProcess'] = {'pid': os.getpid(), 'started': process_identity(os.getpid())}
            self.recovery = False
            self.persist()
            for kind in ('container', 'volume', 'network'):
                assert not self.ids(kind), 'Random owner collision'
        self.started = time.monotonic()

    def persist(self):
        temporary = self.path.with_suffix('.writing')
        temporary.write_text(json.dumps(self.record, indent=2) + '\n', encoding='utf-8')
        temporary.replace(self.path)

    def ids(self, kind):
        command = ['docker', 'ps', '-aq'] if kind == 'container' else ['docker', kind, 'ls', '-q']
        return execute([*command, '--filter', 'label=' + LABEL + '=' + self.run], timeout=15).stdout.split()

    def verify(self, kind, identity):
        info = json.loads(execute(['docker', *([] if kind == 'container' else [kind]), 'inspect', identity], timeout=15).stdout)[0]
        labels = info['Config'].get('Labels', {}) if kind == 'container' else info.get('Labels', {})
        assert labels.get(LABEL) == self.run, 'Uncertain resource owner'
        assert labels.get('com.docker.compose.project') == self.project, 'Uncertain project owner'
        return info

    def snapshot(self):
        result = {}
        for kind in ('container', 'volume', 'network'):
            result[kind] = self.ids(kind)
            for identity in result[kind]:
                self.verify(kind, identity)
        self.record['resources'] = result
        self.persist()

    def check_lifetime(self, *, teardown=False):
        if self.recovery or teardown:
            return
        if self.record['expiresUtc']:
            expiry = datetime.fromisoformat(self.record['expiresUtc'])
            remaining = (expiry - datetime.now(timezone.utc)).total_seconds()
            assert remaining > 900, '105-minute admission limit reached; tear down'
        if self.record.get('runtimeStartedUtc') and time.monotonic() - getattr(self, '_last_ownership_check', 0) >= 240:
            self.snapshot()
            self._last_ownership_check = time.monotonic()
            self.record['lastOwnershipCheckUtc'] = datetime.now(timezone.utc).isoformat()
        self.record['lastSupervisedUtc'] = datetime.now(timezone.utc).isoformat()
        self.persist()

    def start_runtime(self):
        assert not self.record['runtimeStartedUtc']
        now = datetime.now(timezone.utc)
        self.record.update(runtimeStartedUtc=now.isoformat(), expiresUtc=(now + timedelta(hours=2)).isoformat(), status='RUNNING')
        self.persist()

    def phase(self, name, result='PASS', **safe_fields):
        self.check_lifetime()
        self.snapshot()
        self.record['phases'].append({'name': name, 'result': result,
                                     'utc': datetime.now(timezone.utc).isoformat(), **safe_fields})
        self.persist()
        print(result + ': ' + name, flush=True)

    def inventory_copies(self):
        """Record copies at an explicit engineering boundary, never during cleanup."""
        known = []
        for parent, directories, files in os.walk(self.private, onerror=walk_error):
            for name in directories + files:
                item = Path(parent) / name
                assert not item.is_symlink() and not item.is_junction()
                known.append(item.relative_to(self.private).as_posix())
        self.record['copyInventory'] = sorted(known)
        self.persist()

    def launch_native(self):
        executable = ROOT.parent / 'agrosphere-immersive/target/POC-CLOSE-Windows-r3/Windows/AgroSphere/Binaries/Win64/AgroSphere.exe'
        assert executable.is_file()
        user = self.private / 'native-user'
        user.mkdir(exist_ok=False)
        command = [str(executable), '-windowed', '-ForceRes', '-ResX=1920', '-ResY=1080',
                   '-AgroGateway=' + self.record['gateway'], '-AgroIssuer=' + self.record['issuer'],
                   '-AgroFixtureManifest=' + str(self.path), '-UserDir=' + str(user),
                   '-abslog=' + str(self.private / 'native.log'), '-NoSplash']
        process = subprocess.Popen(command, cwd=executable.parents[3], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.record.setdefault('clientProcesses', []).append({'pid': process.pid, 'started': process_identity(process.pid),
            'executable': str(executable), 'sha256': sha(executable), 'kind': 'native-owned-rendered-client'})
        self.native_process = process
        self.inventory_copies()
        self.persist()

    def browser_environment(self):
        directory = self.private / 'playwright-temp'
        directory.mkdir(exist_ok=True)
        self.inventory_copies()
        return {'TEMP': str(directory), 'TMP': str(directory), 'TMPDIR': str(directory)}

    def run_browser(self, command, **kwargs):
        """Track the exact Node parent and stop its owned tree before timeout exit."""
        assert command[:2] == ['node', 'node_modules/@playwright/test/cli.js']
        timeout = kwargs.pop('timeout', 180)
        supplied = kwargs.pop('env')
        environment = dict(getattr(self, 'environment', {}))
        # Do not copy service credentials or arbitrary application environment.
        environment = {k: v for k, v in environment.items() if k not in getattr(self, 'config', {})}
        environment.update({k: v for k, v in supplied.items() if k in (
            'ANALYTICS_LIVE_FIXTURE', 'M4_LIVE_FIXTURE', 'ENVIRONMENT_LIVE_FIXTURE', 'POC_CLOSE_OWNER', 'AGRO_NO_PREVIEW', 'AGRO_TEST_PORT')})
        environment.update(self.browser_environment())
        executable = Path(shutil.which('node') or '').resolve(strict=True)
        process = subprocess.Popen(command, cwd=kwargs['cwd'], env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        identity = process_identity(process.pid)
        self.record.setdefault('clientProcesses', []).append({'pid': process.pid, 'started': identity,
            'executable': str(executable), 'sha256': sha(executable), 'kind': 'owned-playwright-parent'})
        self.persist()
        try:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=min(30, max(.01, deadline - time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    self.check_lifetime()
                    if time.monotonic() >= deadline:
                        raise
        except subprocess.TimeoutExpired:
            if process_identity(process.pid) == identity:
                execute(['taskkill', '/PID', str(process.pid), '/T', '/F'])
            process.communicate(timeout=15)
            self.inventory_copies()
            raise RuntimeError('Owned browser timeout; exact parent tree stopped') from None
        self.inventory_copies()
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)

    def stop_clients(self):
        for child in self.record.get('cliProcesses', []):
            if not child.get('completed') and child.get('started') is not None:
                if process_identity(child['pid']) == child['started']:
                    execute(['taskkill', '/PID', str(child['pid']), '/T', '/F'], timeout=15)
                child['completed'] = True
        for client in self.record.get('clientProcesses', []):
            identity = process_identity(client['pid'])
            if identity is not None and identity == client['started']:
                assert sha(client['executable']) == client['sha256']
                execute(['taskkill', '/PID', str(client['pid']), '/T', '/F'])
            elif identity is not None:
                self.record.setdefault('excludedReusedPids', []).append(client['pid'])
        browser_file = self.private / 'native-browsers.json' if hasattr(self, 'private') else None
        if browser_file and browser_file.exists():
            assert browser_file.stat().st_size <= 16384
            browser_data = json.loads(browser_file.read_text(encoding='utf-8-sig'))
            assert browser_data['runId'] == self.run
            assert len(browser_data['processes']) <= 16
            for browser in browser_data['processes']:
                assert Path(browser['executable']).resolve() == Path(self.record['browserExecutable']).resolve()
                identity = process_identity(browser['pid'])
                if identity is not None and identity == int(browser['started']):
                    assert sha(browser['executable']) == self.record['browserExecutableSha256']
                    execute(['taskkill', '/PID', str(browser['pid']), '/T', '/F'])
        self.record['clientProcessesStopped'] = True
        self.persist()

    def preflight(self):
        engine = execute(['docker', 'info', '--format', '{{json .}}'], timeout=30)
        info = json.loads(engine.stdout)
        self.record['engineResources'] = {key: info.get(key) for key in ('ServerVersion', 'NCPU', 'MemTotal', 'OSType', 'Architecture')}
        references = ['postgis/postgis:17-3.6', 'rabbitmq:4.3.6-management',
                      'quay.io/keycloak/keycloak:26.5.7', 'eclipse-mosquitto:2.0.22',
                      'python:3.12-alpine', 'maven:3.9.12-eclipse-temurin-25',
                      'eclipse-temurin:25-jre', 'python:3.12-slim']
        for ref in references:
            result = execute(['docker', 'image', 'inspect', ref, '--format', '{{json .}}'])
            info = json.loads(result.stdout)
            self.record['inputs'][ref] = {'id': info['Id'], 'digests': info.get('RepoDigests', [])}
        self.record['publicSourceSha256'] = {}
        for repo in ['estate-service', 'spatial-service', 'operations-service', 'api-gateway', 'telemetry-service', 'analytics-service', 'ai-service']:
            directory = ROOT.parent / ('agrosphere-' + repo)
            # Public tracked source/build inputs only; exclude configuration and evidence.
            files = execute(['git', '--no-optional-locks', '-C', str(directory), 'ls-files']).stdout.splitlines()
            selected = [f for f in files if f.startswith(('src/', 'migrations/')) or f in ('Dockerfile', 'pom.xml', 'pyproject.toml', 'VERSION')]
            self.record['publicSourceSha256'][repo] = {f: sha(directory / f) for f in selected if (directory / f).is_file()}
        self.phase('available local base images and public source identities')

    def docker(self, *parts, input_text=None, check=True):
        self.check_lifetime(teardown=parts[0] in ('rm', 'stop'))
        args = list(parts)
        if args[0] in ('create', 'run'):
            takes_value = {'--name', '--label', '--network', '--env-file', '--mount', '--entrypoint', '--user', '-e', '--env', '-v', '--volume', '-w', '--workdir'}
            index = 1
            network_seen = False
            while index < len(args) and args[index].startswith('-'):
                option = args[index]
                if option == '--network':
                    network_seen = True
                    network = args[index + 1]
                    if network.startswith('container:'):
                        self.verify('container', network.removeprefix('container:'))
                    else:
                        assert network == 'none', 'Unowned runtime network'
                elif option.startswith('--network='):
                    network_seen = True
                    network = option.split('=', 1)[1]
                    if network.startswith('container:'):
                        self.verify('container', network.removeprefix('container:'))
                    else:
                        assert network == 'none', 'Unowned runtime network'
                index += 2 if option in takes_value else 1
            assert index < len(args), 'Missing declared image'
            reference = args[index]
            identity = self.record['images'].get(reference) or self.record['inputs'].get(reference, {}).get('id')
            assert identity, 'Image is not in the exact owned preflight inventory'
            args[index] = identity
            if not network_seen:
                args[1:1] = ['--network=none']
            args[1:1] = ['--pull=never', '--label', LABEL + '=' + self.run,
                         '--label', 'com.docker.compose.project=' + self.project]
        if args[0] in ('start', 'stop', 'restart', 'rm'):
            for identity in args[1:]:
                if not identity.startswith('-'):
                    self.verify('container', identity)
        if args[0] == 'build':
            assert '-t' in args
            tag = args[args.index('-t') + 1]
            assert tag.startswith(self.project + '-'), 'Image tag is not newly owned'
            prior = execute(['docker', 'image', 'inspect', tag], check=False)
            assert prior.returncode != 0 or tag in self.record['images'], 'Pre-existing image tag'
            directory = Path(args[-1]).resolve(strict=True)
            recipe = (directory / 'Dockerfile').read_text()
            pinned = []
            def pin_from(match):
                prefix, reference = match.group(1), match.group(2)
                info = self.record['inputs'].get(reference)
                assert info and info.get('digests'), 'Unreviewed base image'
                digest = info['digests'][0]
                pinned.append(digest)
                return prefix + digest
            recipe = re.sub(r'(?m)^(FROM\s+)(\S+)', pin_from, recipe)
            self.record.setdefault('buildRecipes', {})[tag] = {'declaredDockerfileSha256': sha(directory / 'Dockerfile'),
                'pinnedDockerfileSha256': hashlib.sha256(recipe.encode()).hexdigest(), 'fromDigests': pinned}
            self.persist()
            args[1:1] = ['--file', '-']
            input_text = recipe
            # Owner's explicit build-dependency supplement permits restoration
            # from the unchanged declared inputs; base-image pulls stay disabled.
            args[1:1] = ['--pull=false', '--label', LABEL + '=' + self.run]
        if args[:2] == ['image', 'rm']:
            for tag in args[2:]:
                assert tag in self.record['images'] and tag.startswith(self.project + '-')
                found = execute(['docker', 'image', 'inspect', '--format', '{{.Id}}', tag], check=False)
                assert found.returncode != 0 or found.stdout.strip() == self.record['images'][tag]
        result = execute(['docker', *args], input_text=input_text, check=False if args[0] == 'build' else check, owner=self)
        if args[0] == 'build':
            # Build receives public source only, before fixture credentials exist.
            tag = args[args.index('-t') + 1]
            safe_name = tag.removeprefix(self.project + '-')
            assert re.fullmatch('[a-z0-9-]+', safe_name)
            (self.path.parent / (safe_name + '-build.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
            if check and result.returncode:
                raise RuntimeError('Owned independent image build failed; inspect public build log')
        if args[0] == 'build' and result.returncode == 0:
            tag = args[args.index('-t') + 1]
            self.record['images'][tag] = execute(['docker', 'image', 'inspect', '--format', '{{.Id}}', tag]).stdout.strip()
        if args[0] in ('create', 'run', 'build', 'rm'):
            self.snapshot()
        return result

    def cleanup(self):
        # Verify every resource before the first deletion, including an interrupted
        # operation that created a labelled resource before its ID was persisted.
        self.stop_clients()
        self.snapshot()
        # Copy and image ownership must also be checked before deleting any target.
        if self.private.exists():
            assert not self.private.is_symlink() and not self.private.is_junction(), 'Uncertain private root'
            assert self.private.parent == Path(tempfile.gettempdir()).resolve()
            assert self.private.name.startswith(self.project + '-')
            assert (self.private / '.poc-close-owner').read_text() == self.run
            known = set(self.record.get('copyInventory', [])) | {'.poc-close-owner', 'stop'}
            for parent, directories, files in os.walk(self.private, onerror=walk_error):
                for name in directories + files:
                    item = Path(parent) / name
                    assert not item.is_symlink() and not item.is_junction(), 'Unknown linked copy'
                    assert item.relative_to(self.private).as_posix() in known, 'Uninventoried generated copy; review before deletion'
        removable_images = []
        for tag, identity in self.record['images'].items():
            found = execute(['docker', 'image', 'inspect', '--format', '{{.Id}}', tag], check=False)
            if found.returncode == 0:
                assert found.stdout.strip() == identity and tag.startswith(self.project + '-')
                removable_images.append(tag)
        self.record['status'] = 'CLEANING'
        self.persist()
        for identity in self.ids('container'):
            self.verify('container', identity)
            execute(['docker', 'rm', '-f', '-v', identity])
        for kind in ('network', 'volume'):
            for identity in self.ids(kind):
                self.verify(kind, identity)
                execute(['docker', kind, 'rm', identity])
        for tag in removable_images:
            execute(['docker', 'image', 'rm', tag])
        if self.private.exists():
            # Only this resolved, marked, newly created run root is recursive.
            shutil.rmtree(self.private)
        self.snapshot()
        assert all(not ids for ids in self.record['resources'].values())
        assert not self.private.exists()
        self.record.update(cleanup='PASS', privateCopiesRemoved=True,
                           status='INTERRUPTED_CLEANED' if self.recovery else 'CLEANED')
        self.persist()
