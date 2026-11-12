"""Agreed 20-user indexed metadata workload against this owned Gateway only."""
from concurrent.futures import ThreadPoolExecutor, wait
import json
import math
import time
import urllib.error
import urllib.request

from platform_support import request, admin_token
from dev_identity import login


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * p) - 1))] if ordered else None


def measure(owner, context, profile='story'):
    assert profile in ('story', 'maximum')
    users = []
    for number in range(20):
        person = context['user']('load-' + profile + '-' + str(number), 'VIEWER')
        token = admin_token(owner.config)
        endpoint = context['realm'] + '/users/' + person['id']
        value, _ = request(endpoint, token=token)
        value['attributes'] = {**value.get('attributes', {}), 'estate_ids': [context['estate']]}
        request(endpoint, 'PUT', value, token, expected=204)
        users.append(person)
    starts = time.monotonic() + 2

    def worker(person):
        bearer = login(owner.config, person)
        refreshed = time.monotonic()
        values, cold, statuses = [], [], {}
        refreshes, errors, completed = 0, [], []
        for tick in range(330):
            target = starts + tick
            time.sleep(max(0, target - time.monotonic()))
            if time.monotonic() - refreshed > 120:
                bearer = login(owner.config, person)
                refreshed = time.monotonic()
                refreshes += 1
            route = '/blocks/' + context['block'] if tick % 2 == 0 else '/estates/' + context['estate'] + '/blocks?page=0&size=100'
            req = urllib.request.Request(owner.record['gateway'] + '/api/v1' + route,
                                          headers={'Authorization': 'Bearer ' + bearer})
            begin = time.perf_counter()
            try:
                try:
                    response = urllib.request.urlopen(req, timeout=15)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    response.read(2 * 1024 * 1024 + 1)
                    code = response.status
            except OSError as error:
                errors.append(type(error).__name__)
                code = 0
            elapsed = (time.perf_counter() - begin) * 1000
            if tick == 0:
                cold.append(elapsed)
            if tick >= 30:
                values.append(elapsed)
                statuses[str(code)] = statuses.get(str(code), 0) + 1
                completed.append({'tick': tick - 30, 'route': 'block' if tick % 2 == 0 else 'list',
                                  'elapsedMs': elapsed, 'status': code, 'latenessMs': max(0, (begin - target) * 1000)})
        return {'samples': values, 'cold': cold, 'statuses': statuses, 'refreshes': refreshes, 'errors': errors, 'requests': completed}

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = [pool.submit(worker, person) for person in users]
        pending = set(futures)
        while pending:
            _, pending = wait(pending, timeout=30)
            owner.check_lifetime()
            if pending:
                print('IN PROGRESS: agreed 20-user metadata sampling', flush=True)
        results = [future.result() for future in futures]
    samples = [value for result in results for value in result['samples']]
    statuses = {}
    for result in results:
        for key, count in result['statuses'].items():
            statuses[key] = statuses.get(key, 0) + count
    report = {'scope': 'SIMULATED owned local 20-user query workload', 'project': owner.project, 'profile': profile,
              'concurrentUsers': 20, 'requestsPerSecondPerUser': 1, 'warmupSeconds': 30, 'samplingSeconds': 300,
              'p50Ms': percentile(samples, .5), 'p95Ms': percentile(samples, .95), 'maxMs': max(samples),
              'samples': len(samples), 'statuses': statuses, 'coldFirstRequestsMs': [v for r in results for v in r['cold']],
              'signedSessionRenewals': sum(r['refreshes'] for r in results), 'result': 'NOT_EVALUATED',
              'requestsByGeneratedUser': [r['requests'] for r in results]}
    report['result'] = 'PASS' if len(samples) == 6000 and statuses == {'200': 6000} and report['p95Ms'] < 500 else 'FAILED'
    (owner.path.parent / ('m1-query-load-' + profile + '.json')).write_text(json.dumps(report, indent=2) + '\n')
    owner.phase(profile + ' 20-user five-minute indexed metadata query measurement', report['result'],
                samples=len(samples), p95Ms=report['p95Ms'], maxMs=report['maxMs'])
    return report
