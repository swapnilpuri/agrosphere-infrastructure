"""Approved POC-CLOSE: one owned generated context, explicit stop/recovery."""
import argparse
from datetime import datetime, timezone
import json
import sys
import time
import traceback
import uuid

from platform_support import request, admin_token
from dev_identity import login
from poc_close_owner import Owner
from poc_close_platform import Platform
import verify_analytics
import verify_m4
import verify_telemetry
import verify_environment_history
from poc_close_load import measure as measure_queries
from verify_alert_privacy import privacy_alerts
from poc_close_web import Web
from poc_close_render_fixtures import prepare as prepare_renderer_fixtures


def story(owner, context):
    call, estate, first = context['call'], context['estate'], context['block']
    first_block = call('/blocks/' + first)
    divisions = [first_block['divisionId'], call('/estates/' + estate + '/divisions', 'POST',
        {'estateId': estate, 'divisionCode': 'D2', 'name': 'SIMULATED second division', 'status': 'ACTIVE'}, status=201)['id']]
    blocks = [first_block]
    for index in range(2, 11):
        div = divisions[0 if index <= 5 else 1]
        blocks.append(call('/divisions/' + div + '/blocks', 'POST', {'estateId': estate, 'divisionId': div,
            'blockCode': f'B{index:02d}', 'name': f'SIMULATED connected block {index:02d}', 'cropType': 'RUBBER',
            'plantedAreaHectares': 1, 'plantedTreeCount': 100, 'tappableTreeCount': 80, 'status': 'ACTIVE'}, status=201))
    foreign = call('/estates', 'POST', {'estateCode': 'DENIED', 'name': 'SIMULATED negative estate',
        'countryCode': 'LK', 'timezone': 'Asia/Colombo', 'status': 'ACTIVE'}, status=201)
    foreign_div = call('/estates/' + foreign['id'] + '/divisions', 'POST', {'estateId': foreign['id'],
        'divisionCode': 'FD1', 'name': 'SIMULATED foreign division', 'status': 'ACTIVE'}, status=201)
    foreign_block = call('/divisions/' + foreign_div['id'] + '/blocks', 'POST', {'estateId': foreign['id'],
        'divisionId': foreign_div['id'], 'blockCode': 'FOREIGN', 'name': 'SIMULATED foreign block', 'cropType': 'RUBBER',
        'plantedAreaHectares': 1, 'plantedTreeCount': 100, 'tappableTreeCount': 80, 'status': 'ACTIVE'}, status=201)
    for _ in range(120):
        count = owner.compose('exec', '-T', '-e', 'PGPASSWORD', 'postgres', 'psql', '-h', '127.0.0.1',
            '-U', 'agrosphere_spatial', '-d', 'agrosphere_spatial', '-Atc',
            "SELECT count(*) FROM reference_entity WHERE estate_id='" + estate + "' AND entity_type='BLOCK'",
            environment={'PGPASSWORD': owner.config['SPATIAL_DB_PASSWORD']}).stdout.strip()
        if int(count) == 10:
            break
        time.sleep(.5)
    else:
        raise AssertionError('Canonical Spatial references did not settle')
    features = []
    for index, block in enumerate(blocks):
        x, y = 35 + (index % 5) * .0012, -15 + (index // 5) * .0012
        ring = [[x, y], [x + .001, y], [x + .001, y + .001], [x, y + .001], [x, y]]
        features.append(call('/spatial/features', 'POST', {'estateId': estate, 'referenceEntityId': block['id'],
            'referenceEntityType': 'BLOCK', 'featureCode': block['blockCode'], 'geometry': {'type': 'Polygon', 'coordinates': [ring]},
            'srid': 4326, 'status': 'ACTIVE', 'sourceType': 'GENERATED', 'sourceReference': 'POC-CLOSE ' + owner.run,
            'dataProvenance': 'SIMULATED'}, status=201))

    def scoped(name, role, estate_id):
        person = context['user'](name, role)
        token = admin_token(owner.config)
        endpoint = context['realm'] + '/users/' + person['id']
        representation, _ = request(endpoint, token=token)
        representation['attributes'] = {**representation.get('attributes', {}), 'estate_ids': [estate_id]}
        request(endpoint, 'PUT', representation, token, expected=204)
        return person

    viewer = scoped('poc-viewer', 'VIEWER', estate)
    outsider = scoped('poc-foreign', 'VIEWER', foreign['id'])
    viewer_token, outsider_token = login(owner.config, viewer), login(owner.config, outsider)
    assert [row['id'] for row in call('/estates?page=0&size=100', bearer=viewer_token)['content']] == [estate]
    call('/blocks/' + first, bearer=outsider_token, status=403)
    call('/blocks/' + foreign_block['id'], bearer=viewer_token, status=403)
    call('/blocks/' + first, bearer='', status=401)
    (owner.private / 'generated-clients.json').write_text(json.dumps({'viewer': viewer, 'outsider': outsider,
        'admin': context['admin'], 'worker': context['worker']}))
    (owner.private / 'canonical-geometry.json').write_text(json.dumps(features))
    owner.record['canonical'] = {'estateId': estate, 'blockId': first, 'blockIds': [b['id'] for b in blocks],
        'divisionIds': divisions, 'foreignEstateId': foreign['id'], 'foreignBlockId': foreign_block['id'],
        'dataProvenance': 'SIMULATED'}
    owner.inventory_copies()
    owner.phase('canonical ten-block geometry, signed scope and foreign-object denials', estateId=estate, blockId=first)


def connected(owner, hold_seconds, rendered_web=False):
    """Explicit callback chain keeps source DBs/UUIDs/projections in one project."""
    def base(extra_acceptance=None, extra_environment=None):
        def ready(**context):
            story(owner, context)
            extra_acceptance(**context)
        owner.platform_runner(ready, extra_environment)

    def analytics_runner(acceptance):
        verify_analytics.main(acceptance, platform_runner=base, owner=owner)

    def after_ai(**ai_context):
        owner.phase('Operations collection -> production projection -> AI journal/registry -> real PKCE Web')
        # privacy_alerts includes retained II/WA/collection checks. Collections are
        # already present; invoke its chain with the existing-effect guard below.
        privacy_context = dict(ai_context)
        privacy_context['collections_already_verified'] = True
        privacy_context['workforce_estate'] = ai_context['estate']
        privacy_context['workforce_foreign_estate'] = owner.record['canonical']['foreignEstateId']
        privacy_context['poc_owner'] = owner
        privacy_context['admin_token'] = login(owner.config, ai_context['admin'])
        privacy_context['worker_token'] = login(owner.config, ai_context['worker'])
        privacy_context['audit_token'] = login(owner.config, ai_context['auditor'])
        privacy_alerts(**privacy_context)
        owner.phase('generated workforce, manual incidents and private alert lifecycle')
        production = ai_context['analytics_container']
        # Same service-owned database/journal, new environmental-capable process.
        # Pausing production ingestion does not fabricate source availability.
        owner.docker('stop', production)
        before = ai_context['analytics_sql']('SELECT count(*) FROM anl_receipt')

        def telemetry_runner(extra_telemetry=None, evidence_path=None, platform_environment=None):
            def existing_platform(extra_acceptance=None, extra_environment=None):
                extra_acceptance(**ai_context)
            verify_telemetry.main(extra_telemetry, evidence_path, platform_environment,
                                  platform_runner=existing_platform, owner=owner)

        def final(**environment):
            assert environment['estate'] == ai_context['estate'] and environment['block'] == ai_context['block']
            assert environment['environment_sql']('SELECT count(*) FROM anl_receipt') == before
            owner.record['continuity'] = {'sameProject': owner.project, 'estateId': environment['estate'],
                'blockId': environment['block'], 'productionReceiptsPreserved': int(before),
                'aiDatasetId': ai_context['ai_dataset'], 'aiEvaluationId': ai_context['ai_evaluation'],
                'environmentWindow': {'from': environment['environment_from'], 'to': environment['environment_to']}}
            owner.phase('MQTT -> immutable environment history -> Gateway/Web with source continuity')
            owner.record['status'] = 'COMPONENTS_PASS_RENDERED_CHECKS_PENDING'
            owner.record['liveServices'] = {'ai': ai_context['ai_container'], 'environment': environment['environment_container']}
            if hold_seconds or rendered_web:
                prepare_renderer_fixtures(owner)
            web = Web(owner, owner.path.parents[4] / 'agrosphere-web/dist/web/browser')
            web.start()
            owner.web = web
            owner.record['nativeUserDirectory'] = str(owner.private / 'native-user')
            owner.inventory_copies()
            owner.persist()
            query_result = measure_queries(owner, ai_context)
            owner.record['queryPerformance'] = {k: query_result[k] for k in ('result', 'p95Ms', 'maxMs', 'samples')}
            owner.persist()
            if hold_seconds or rendered_web:
                maximum = owner.record['rendererFixtures']
                result = measure_queries(owner, {**ai_context, 'estate': maximum['maximumEstateId'],
                    'block': maximum['maximumBlockIds'][0]}, 'maximum')
                owner.record['maximumQueryPerformance'] = {k: result[k] for k in ('result', 'p95Ms', 'maxMs', 'samples')}
                owner.persist()
            if rendered_web:
                result = owner.run_browser(['node', 'node_modules/@playwright/test/cli.js', 'test',
                    '--project=poc-close-rendered', '--reporter=list', '--output=' + str(owner.private / 'browser-hardware')],
                    cwd=owner.path.parents[4] / 'agrosphere-web', env={'POC_CLOSE_OWNER': str(owner.path), 'AGRO_NO_PREVIEW': '1'}, timeout=2100)
                # Keep failure diagnostics private: browser errors may contain an
                # authorization callback URL. The public report has no URLs/tokens.
                (owner.private / 'hardware-browser.log').write_text(result.stdout + result.stderr)
                owner.record['hardwareWebExitCode'] = result.returncode
                owner.inventory_copies()
                owner.persist()
            if hold_seconds:
                owner.launch_native()
            end = time.monotonic() + hold_seconds
            try:
                while time.monotonic() < end and not (owner.private / 'stop').exists():
                    owner.check_lifetime()
                    time.sleep(min(5, max(0, end - time.monotonic())))
            finally:
                owner.stop_clients()
                owner.inventory_copies()

        verify_environment_history.main(platform_runner=telemetry_runner, owner=owner, extra_acceptance=final)

    verify_m4.main(platform_runner=analytics_runner, owner=owner, extra_acceptance=after_ai)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=['connected'], default='connected')
    parser.add_argument('--preflight-only', action='store_true')
    parser.add_argument('--hold-seconds', type=int, default=0)
    parser.add_argument('--rendered-web', action='store_true')
    parser.add_argument('--recover', type=str)
    args = parser.parse_args()
    assert 0 <= args.hold_seconds <= 5400
    if args.recover:
        Owner(args.recover).cleanup()
        print('PASS: exact owned interruption recovery; verification not certified')
        return
    owner = Platform()
    print('Owner manifest: ' + str(owner.path), flush=True)
    try:
        owner.prepare()
        if not args.preflight_only:
            connected(owner, args.hold_seconds, args.rendered_web)
            owner.record['executionResult'] = 'COMPONENT_CHECKS_PASS_FULL_SCOPE_PARTIAL'
        else:
            owner.record['executionResult'] = 'PREFLIGHT_PASS'
        owner.persist()
    except BaseException as error:
        owner.record['executionResult'] = 'FAILED'
        owner.record['failure'] = {'type': type(error).__name__,
            'frames': [{'file': frame.filename, 'line': frame.lineno, 'function': frame.name}
                       for frame in traceback.extract_tb(error.__traceback__)]}
        owner.persist()
        print('FAILED: inspect sanitized owner manifest; exception ' + type(error).__name__, flush=True)
        raise SystemExit(1) from None
    finally:
        try:
            if hasattr(owner, 'web'):
                owner.web.close()
            owner.cleanup()
        except BaseException as error:
            owner.record['cleanup'] = 'BLOCKED'
            owner.record['cleanupFailureType'] = type(error).__name__
            owner.persist()
            print('BLOCKED: exact owned cleanup requires inspection; no broad deletion attempted', flush=True)
            raise


if __name__ == '__main__':
    main()
