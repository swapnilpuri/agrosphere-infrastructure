"""Partial callback timing and replay against the actual owned native listener."""
import argparse
from datetime import datetime, timezone
import json
import socket
import time

from poc_close_native import context, command, read_state


def run(manifest, case):
    path, owner, private = context(manifest)
    start = time.monotonic()
    command(manifest, 'login')
    deadline = start + 30
    while time.monotonic() < deadline:
        state = read_state(private)
        if 'Sign in using your system browser' in state['status']:
            break
        time.sleep(.1)
    else:
        raise AssertionError('Owned native callback listener did not become ready')
    report = {'runId': owner['runId'], 'case': case, 'startedUtc': datetime.now(timezone.utc).isoformat(),
        'result': 'IN_PROGRESS', 'requestContains': 'Synthetic invalid code/state only'}
    evidence = path.parent / ('native-callback-' + case + '.json')
    evidence.write_text(json.dumps(report, indent=2) + '\n')
    updates = set()
    with socket.create_connection(('127.0.0.1', 49152), timeout=2) as connection:
        connection.settimeout(2)
        connection.sendall(b'GET /oauth/callback?code=SIMULATED&state=invalid HTTP/1.1\r\nHost: 127.0.0.1\r\n')
        partial_started = time.monotonic()
        end = partial_started + (2 if case == 'before-deadline' else 310)
        while time.monotonic() < end:
            context(manifest)
            state = read_state(private)
            updates.add((private / 'native-state.json').stat().st_mtime_ns)
            assert not state['sessionReady'] and state['features'] == 0 and not state['details']
            if case == 'after-deadline' and 'Login timed out' in state['status']:
                break
            time.sleep(.25)
        if case == 'after-deadline':
            assert 'Login timed out' in state['status']
        try:
            connection.sendall(b'\r\n')
            reply = connection.recv(4096)
            report['replyBytes'] = len(reply)
        except OSError:
            report['connectionClosedBeforeCompletion'] = True
        if case == 'before-deadline':
            end = time.monotonic() + 10
            while time.monotonic() < end:
                state = read_state(private)
                if 'Login callback rejected' in state['status']:
                    break
                time.sleep(.1)
            assert 'Login callback rejected' in state['status']
        report['partialSeconds'] = time.monotonic() - partial_started
    with socket.socket() as replay:
        replay.settimeout(2)
        assert replay.connect_ex(('127.0.0.1', 49152)) != 0, 'Completed callback listener still accepts replay'
    report.update(result='DIAGNOSTIC_PASS_RENDERED_OBSERVATION_REQUIRED', stateAfter=state,
        diagnosticUpdatesDuringPartial=len(updates), listenerReplayDenied=True,
        finishedUtc=datetime.now(timezone.utc).isoformat())
    evidence.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest')
    parser.add_argument('case', choices=['before-deadline','after-deadline'])
    arguments = parser.parse_args()
    run(arguments.manifest, arguments.case)
