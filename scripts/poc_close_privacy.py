"""Connected generated policy records, distinct from the live story chronology.

Only the two newly created policy roots/ack rows receive synthetic age. Source
incident observations, revision timestamps, outbox envelopes and host clock stay
unchanged. Uses the established PrivacyAlertServiceIT fixture technique.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid

from dev_identity import login


def verify(c, call, manager_a, manager_b):
    owner = c['poc_owner']
    c['admin_token'] = login(c['config'], c['admin'])
    manager_token = login(c['config'], manager_a)
    clients_file = owner.private / 'generated-clients.json'
    clients = json.loads(clients_file.read_text())
    clients.update(managerA=manager_a, managerB=manager_b)
    clients_file.write_text(json.dumps(clients))
    report = {'runId': owner.run, 'scope': 'Two separate SIMULATED policy-aging records in the owned Operations DB',
        'managerA': manager_a['id'], 'managerB': manager_b['id'], 'records': []}

    def sql(statement):
        result = c['compose']('exec', '-T', '-e', 'PGPASSWORD', 'postgres', 'psql', '-h', '127.0.0.1',
            '-U', 'agrosphere_operations', '-d', 'agrosphere_operations', '-At', '-v', 'ON_ERROR_STOP=1',
            environment={'PGPASSWORD': c['config']['OPERATIONS_DB_PASSWORD']}, input_text=statement)
        return result.stdout.strip()

    def source_hash(identity):
        return sql("SELECT md5(row_to_json(i)::text) FROM crop_health_incident i WHERE id='" + identity + "'")

    observed = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(timespec='microseconds')
    for days in (31, 366):
        source, _ = call('/incidents', 'POST', {'estateId': c['estate'], 'blockId': c['block'],
            'dataProvenance': 'SIMULATED', 'observedAt': observed, 'category': 'TREE_DAMAGE', 'severity': 'HIGH',
            'summary': 'SIMULATED separate policy-aging fixture', 'details': 'SIMULATED policy verification only',
            'backdateReason': 'SIMULATED historical policy record; actual live ingestion timestamp retained'}, status=201)
        page, _ = call('/alerts?estateId=' + c['estate'])
        alert = next(a for a in page['content'] if a['incidentId'] == source['id'])
        aid = str(uuid.UUID(alert['id']))
        route = '/alerts/' + aid
        if days == 31:
            call(route + '/read', 'POST', {'attentionVersion': 1}, token=manager_token)
        else:
            call(route + '/acknowledgements', 'POST', {'attentionVersion': 1, 'expectedAlertVersion': 1}, token=manager_token)
        call('/incidents/' + source['id'] + '/resolve', 'POST', {'expectedVersion': 0,
            'reason': 'SIMULATED separate policy closure', 'resolutionNote': 'SIMULATED policy verification',
            'resolvedAt': datetime.now(timezone.utc).isoformat(timespec='microseconds')})
        before = source_hash(source['id'])
        # Transactional, exact-root synthetic age; trigger restoration rolls back
        # with the transaction on every SQL error. Runtime role receives no DDL.
        statement = f"""BEGIN;
SET LOCAL lock_timeout='5s';
ALTER TABLE privacy_alert DISABLE TRIGGER privacy_root_guard;
UPDATE privacy_alert SET inactive_since=now()-interval '{days} days',
 body=jsonb_set(jsonb_set(jsonb_set(body,
 '{{raisedAt}}',to_jsonb(to_char((now()-interval '{days+1} days') AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'))),
 '{{attentionAt}}',to_jsonb(to_char((now()-interval '{days+1} days') AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'))),
 '{{updatedAt}}',to_jsonb(to_char((now()-interval '{days} days') AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')))
 WHERE id='{aid}';
ALTER TABLE privacy_alert ENABLE TRIGGER privacy_root_guard;
ALTER TABLE privacy_ack DISABLE TRIGGER privacy_ack_immutable;
UPDATE privacy_ack SET acknowledged_at=now()-interval '{days} days 1 hour' WHERE alert_id='{aid}';
ALTER TABLE privacy_ack ENABLE TRIGGER privacy_ack_immutable;
COMMIT;
"""
        sql(statement)
        assert source_hash(source['id']) == before
        expired, _ = call(route, token=manager_token)
        if days == 31:
            assert expired['readState'] == 'EXPIRED' and not expired['unreadForMe'] and expired['readAt'] is None
            call(route + '/read', 'POST', {'attentionVersion': 1}, token=manager_token, status=410)
        else:
            assert expired['acknowledged'] and expired['acknowledgementState'] == 'REDACTED' and expired['acknowledgedAt'] is None
            history, _ = call(route + '/history', token=manager_token)
            assert history['retentionState'] == 'EXPIRED' and history['totalElements'] == 0
        sql('SELECT privacy_cleanup(100);')
        assert sql("SELECT count(*) FROM privacy_read WHERE alert_id='" + aid + "'") == '0'
        assert sql("SELECT count(*) FROM privacy_command WHERE alert_id='" + aid + "'") == '0'
        if days == 366:
            for table in ('privacy_ack', 'privacy_evidence'):
                assert sql("SELECT count(*) FROM " + table + " WHERE alert_id='" + aid + "'") == '0'
        call('/incidents/' + source['id'] + '/reopen', 'POST', {'expectedVersion': 1, 'reason': 'SIMULATED policy no-resurrection check'})
        reopened, _ = call(route, token=manager_token)
        assert reopened['attentionVersion'] == 2 and reopened['readState'] == 'UNREAD' and reopened['readAt'] is None
        history, _ = call(route + '/history', token=manager_token)
        if days == 366:
            assert history['retentionState'] == 'PARTIAL' and history['totalElements'] == 1
        report['records'].append({'incidentId': source['id'], 'alertId': aid, 'syntheticInactiveDays': days,
            'sqlSha256': hashlib.sha256(statement.encode()).hexdigest(), 'sourceUnchangedDuringAging': True,
            'expiredReadState': expired['readState'], 'expiredAcknowledgementState': expired['acknowledgementState'],
            'reopenedReadState': reopened['readState'], 'reopenedHistoryState': history['retentionState'],
            'oldPersonalCopiesAbsent': True, 'noReadResurrection': True})
    report['result'] = 'PASS'
    (owner.path.parent / 'privacy-policy.json').write_text(json.dumps(report, indent=2) + '\n')
    owner.inventory_copies()
    owner.phase('distinct managers, expired/redacted/partial policy records and no read resurrection')
