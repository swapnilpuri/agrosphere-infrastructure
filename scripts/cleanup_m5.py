"""Recover only a stopped, manifest-owned M5 fixture after verifier interruption."""
import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--manifest', type=Path, required=True)
args = parser.parse_args()
manifest_path = args.manifest.resolve(strict=True)
record = json.loads(manifest_path.read_text())
run, project = record['runId'], record['project']
assert re.fullmatch('[a-f0-9]{32}', run)
assert project == 'agrosphere-m5-' + run[:12]
private = Path(record['privateFixtureFile']).resolve().parent
assert private.parent == Path(tempfile.gettempdir()).resolve()
assert private.name.startswith(project + '-')
evidence = Path(record['evidencePath']).resolve()
assert evidence == manifest_path.parent / 'm5' / run / 'results.json'

def docker(*parts):
    result = subprocess.run(['docker', *parts], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Owned cleanup Docker operation failed: ' + parts[0])
    return result.stdout.strip()

selector = 'label=com.docker.compose.project=' + project
containers = docker('ps', '-aq', '--filter', selector).split()
for item in containers:
    info = json.loads(docker('inspect', item))[0]
    assert info['Config']['Labels']['com.docker.compose.project'] == project
    assert not info['State']['Running'], 'Stop the active verifier through its stop sentinel instead.'
volumes = docker('volume', 'ls', '-q', '--filter', selector).split()
networks = docker('network', 'ls', '-q', '--filter', selector).split()
for kind, items in [('volume', volumes), ('network', networks)]:
    for item in items:
        info = json.loads(docker(kind, 'inspect', item))[0]
        assert info['Labels']['com.docker.compose.project'] == project
# All ownership checks precede removal; no recursive filesystem operation or prune.
for item in containers:
    docker('rm', '-v', item)
for item in networks:
    docker('network', 'rm', item)
for item in volumes:
    docker('volume', 'rm', item)
for tag, expected in record.get('images', {}).items():
    assert tag in {project + '-' + x for x in ('estate', 'spatial', 'gateway', 'jaeger', 'otel-collector')}
    found = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', tag], capture_output=True, text=True)
    if found.returncode == 0:
        assert found.stdout.strip() == expected
        docker('image', 'rm', tag)
known = {'generated-users.json', 'geometry.json', 'empty.env', 'agrosphere-realm.json', 'override.yaml', 'stop'}
if private.exists():
    assert all(item.is_file() and not item.is_symlink() and item.name in known for item in private.iterdir())
    for name in known:
        (private / name).unlink(missing_ok=True)
    private.rmdir()
assert not docker('ps', '-aq', '--filter', selector)
assert not docker('volume', 'ls', '-q', '--filter', selector)
assert not docker('network', 'ls', '-q', '--filter', selector)
record.update(status='INTERRUPTED_CLEANED', cleanup='PASS', privateFilesRemoved=True,
              interruption='Verifier process was absent after interruption; stopped owned resources recovered by exact labels and manifest.')
text = json.dumps(record, indent=2) + '\n'
evidence.write_text(text)
manifest_path.write_text(text)
print('PASS: interrupted owned M5 fixture cleanup; verification status remains interrupted')
