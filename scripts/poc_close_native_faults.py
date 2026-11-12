"""Rendered-client cases through the live fixture's bounded fault adapter."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import socket
import time

from poc_close_native import context, command, read_state


def run(manifest, case, plan_only=False):
    path, owner, private = context(manifest)
    canonical = owner['canonical']
    renderer = owner['rendererFixtures']
    target_estate = canonical['estateId']
    source = json.loads((private / 'canonical-geometry.json').read_text())
    rules = []
    route = '/api/v1/spatial/estates/' + target_estate + '/features'
    expected = 'clear'
    state_before = read_state(private)
    assert state_before['sessionReady'] or case in ('callback-occupied', 'oversize-identity')

    def await_state(predicate, seconds=20):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            context(manifest)
            value = read_state(private)
            if predicate(value):
                return value
            time.sleep(.1)
        raise AssertionError('Native case did not reach its expected state')

    if case in ('empty', 'no-geometry'):
        target_estate = renderer['emptyEstateId' if case == 'empty' else 'noGeometryEstateId']
    elif case == 'malformed-envelope':
        rules = [{'scope': 'gateway', 'method': 'GET', 'path': route, 'action': 'malformed'}]
    elif case == 'oversize-api':
        rules = [{'scope': 'gateway', 'method': 'GET', 'path': route, 'action': 'oversize'}]
    elif case == 'oversize-identity':
        rules = [{'scope': 'identity', 'method': 'GET', 'path': '/realms/agrosphere/protocol/openid-connect/certs', 'action': 'oversize'}]
        expected = 'identity-denied'
    elif case in ('wrong-provenance', 'wrong-srid', 'self-intersection', 'polar', 'antimeridian', 'feature-vertices', 'aggregate-vertices', 'aggregate-bytes', 'page-entries'):
        rows = copy.deepcopy(source)
        feature = rows[0]
        if case == 'wrong-provenance':
            feature['dataProvenance'] = 'REAL'
        elif case == 'wrong-srid':
            feature['srid'] = 3857
        elif case == 'self-intersection':
            feature['geometry'] = {'type': 'Polygon', 'coordinates': [[[35,-15],[35.001,-14.999],[35.001,-15],[35,-14.999],[35,-15]]]}
        elif case == 'polar':
            feature['geometry'] = {'type': 'Polygon', 'coordinates': [[[35,86],[35.001,86],[35.001,86.001],[35,86.001],[35,86]]]}
        elif case == 'antimeridian':
            feature['geometry'] = {'type': 'Polygon', 'coordinates': [[[179,-15],[-179,-15],[-179,-14.999],[179,-14.999],[179,-15]]]}
        elif case == 'feature-vertices':
            ring = [[35 + .0005 * math.cos(2 * math.pi * i / 10000), -15 + .0005 * math.sin(2 * math.pi * i / 10000)] for i in range(10000)]
            feature['geometry'] = {'type': 'Polygon', 'coordinates': [ring + [ring[0]]]}
        elif case == 'aggregate-vertices':
            target_estate = renderer['maximumEstateId']
            route = '/api/v1/spatial/estates/' + target_estate + '/features'
            rows = json.loads((private / 'maximum-geometry.json').read_text())
            ring = rows[0]['geometry']['coordinates'][0]
            ring.insert(1, [(ring[0][i] + ring[1][i]) / 2 for i in range(2)])
        elif case == 'page-entries':
            rows = [copy.deepcopy(feature) for _ in range(101)]
        elif case == 'aggregate-bytes':
            # Both pages remain below the transport bound. Their combined
            # serialized scene exceeds the documented10MiB ceiling.
            for row in rows:
                row['id'] = row['referenceEntityId']
                row['fixturePadding'] = ' ' * 620000
        body = json.dumps({'content': rows, 'page': 0, 'size': 100, 'totalElements': len(rows)}).encode()
        assert len(body) <= 10 * 1024 * 1024
        (private / 'native-fault-reply.json').write_bytes(body)
        rules = [{'scope': 'gateway', 'method': 'GET', 'path': route, 'action': 'fixture-reply', 'bodySha256': hashlib.sha256(body).hexdigest()}]
        if case == 'aggregate-bytes':
            rules.append({**rules[0], 'path': '/api/v1/estates/' + target_estate + '/blocks'})
    elif case == 'race-estate':
        rules = [{'scope': 'gateway', 'method': 'GET', 'path': route, 'action': 'delay'}]
        expected = 'empty-final-estate'
    elif case == 'race-selection':
        route = '/api/v1/blocks/' + canonical['blockIds'][0]
        rules = [{'scope': 'gateway', 'method': 'GET', 'path': route, 'action': 'delay'}]
        expected = 'latest-selection'
    elif case == 'race-logout':
        rules = [{'scope': 'gateway', 'method': 'GET', 'path': route, 'action': 'delay'}]
        expected = 'signed-out'
    elif case == 'gateway-unavailable':
        rules = [{'scope': 'gateway', 'method': 'GET', 'path': route, 'action': 'status', 'status': 503}]
    elif case != 'callback-occupied':
        raise ValueError('Unknown bounded native case')

    report = {'runId': owner['runId'], 'case': case, 'startedUtc': datetime.now(timezone.utc).isoformat(),
        'rules': rules, 'expected': expected, 'stateBefore': state_before, 'result': 'IN_PROGRESS'}
    evidence = path.parent / ('native-' + case + '.json')
    evidence.write_text(json.dumps(report, indent=2) + '\n')
    if plan_only:
        report['result'] = 'READY_FOR_ENGINEERING_REVIEW'
        evidence.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report))
        return
    try:
        (private / 'faults.json').write_text(json.dumps(rules))
        release = private / 'release'
        if release.exists():
            release.unlink()
        if case == 'callback-occupied':
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',49152))
                listener.listen(1)
                command(manifest, 'login')
                final = await_state(lambda state: 'callback port 49152 is occupied' in state['status'])
        elif expected == 'identity-denied':
            command(manifest, 'login')
            final = await_state(lambda state: not state['sessionReady'] and 'Identity service unavailable' in state['status'])
        elif case == 'race-selection':
            command(manifest, 'select', canonical['blockIds'][0])
            time.sleep(1)
            command(manifest, 'select', canonical['blockIds'][1])
            final = await_state(lambda state: state['selected'] == canonical['blockIds'][1])
            release.write_text('release')
            time.sleep(2)
            final = await_state(lambda state: state['selected'] == canonical['blockIds'][1])
        else:
            command(manifest, 'load', target_estate)
            if case.startswith('race-'):
                time.sleep(1)
                if case == 'race-estate':
                    command(manifest, 'load', renderer['emptyEstateId'])
                else:
                    command(manifest, 'logout')
                release.write_text('release')
                time.sleep(2)
            if expected == 'signed-out':
                final = await_state(lambda state: not state['sessionReady'] and state['features'] == 0 and not state['details'])
            else:
                final = await_state(lambda state: state['features'] == 0 and state['meshes'] == 0 and not state['details']
                    and state['loadEpoch'] > state_before['loadEpoch'] and 'Loading' not in state['message'])
                if expected == 'empty-final-estate':
                    assert final['estate'] == renderer['emptyEstateId']
        report.update(result='DIAGNOSTIC_PASS_RENDERED_OBSERVATION_REQUIRED', stateAfter=final,
            finishedUtc=datetime.now(timezone.utc).isoformat())
    except BaseException as error:
        report.update(result='FAIL', errorType=type(error).__name__, stateAfter=read_state(private))
        raise
    finally:
        (private / 'faults.json').write_text('[]')
        report['faultsRestored'] = True
        evidence.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('case','result','stateAfter','faultsRestored')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest')
    parser.add_argument('case', choices=['empty','no-geometry','malformed-envelope','oversize-api','oversize-identity','wrong-provenance','wrong-srid','self-intersection','polar','antimeridian','feature-vertices','aggregate-vertices','aggregate-bytes','page-entries','race-estate','race-selection','race-logout','gateway-unavailable','callback-occupied'])
    parser.add_argument('--plan-only', action='store_true')
    arguments = parser.parse_args()
    run(arguments.manifest, arguments.case, arguments.plan_only)
