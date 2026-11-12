"""Bounded commands to the explicitly enabled, owned packaged client only."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import time

from poc_close_owner import ROOT, process_identity


def context(manifest):
    path = Path(manifest).resolve(strict=True)
    value = json.loads(path.read_text())
    run = value['runId']
    assert len(run) == 32 and all(c in '0123456789abcdef' for c in run)
    assert path == ROOT / 'target/poc-close' / run / 'owner.json'
    assert value['project'] == 'agrosphere-poc-close-' + run
    assert value['status'] == 'COMPONENTS_PASS_RENDERED_CHECKS_PENDING'
    assert datetime.fromisoformat(value['expiresUtc']) > datetime.now(timezone.utc)
    operator = value['operatorProcess']
    assert process_identity(operator['pid']) == operator['started']
    private = Path(value['privateDirectory']).resolve(strict=True)
    assert private.parent == Path(tempfile.gettempdir()).resolve()
    assert private.name.startswith(value['project'] + '-')
    assert not private.is_symlink() and not private.is_junction()
    assert (private / '.poc-close-owner').read_text() == run
    native = next(p for p in value['clientProcesses'] if p['kind'] == 'native-owned-rendered-client')
    assert process_identity(native['pid']) == native['started']
    return path, value, private


def read_state(private):
    return json.loads((private / 'native-state.json').read_text(encoding='utf-8-sig'))


def command(manifest, action, identity=None, seconds=None):
    path, owner, private = context(manifest)
    previous = read_state(private)
    sequence = max(int(previous['sequence']) + 1, time.time_ns() // 1000000)
    data = {'sequence': sequence, 'action': action}
    if identity:
        data['id'] = identity
    if seconds:
        data['seconds'] = seconds
    target = private / 'native-command.json'
    pending = target.with_suffix('.writing')
    pending.write_text(json.dumps(data))
    pending.replace(target)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        state = read_state(private)
        if state['sequence'] == sequence:
            break
        time.sleep(.25)
    else:
        raise RuntimeError('Owned native command was not acknowledged')
    destination = path.parent / 'native-commands.json'
    report = json.loads(destination.read_text()) if destination.exists() else {'runId': owner['runId'], 'commands': []}
    report['commands'].append({'utc': datetime.now(timezone.utc).isoformat(), 'command': data,
        'acknowledgedState': state, 'note': 'Command acknowledgement alone is not final asynchronous/rendered verification.'})
    destination.write_text(json.dumps(report, indent=2) + '\n')
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest')
    parser.add_argument('action', choices=['state', 'login', 'logout', 'refresh', 'load', 'select', 'focus', 'export', 'measure', 'rebase', 'origin-reset'])
    parser.add_argument('--id')
    parser.add_argument('--seconds', type=int, choices=[30, 600])
    args = parser.parse_args()
    if args.action == 'state':
        _, _, private = context(args.manifest)
        result = read_state(private)
    else:
        assert (args.action in ('load', 'select')) == bool(args.id)
        assert (args.action == 'measure') == bool(args.seconds)
        result = command(args.manifest, args.action, args.id, args.seconds)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
