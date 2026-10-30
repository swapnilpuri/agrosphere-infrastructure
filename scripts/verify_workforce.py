"""WA-1 + retained 3A/3B acceptance in a new generated-credential Compose project only."""
import json
import time
import uuid
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from platform_support import request, admin_token
from dev_identity import login
from verify_tapping import main
from verify_collections import collections


def workforce(**c):
    collections(**c)
    compose, config = c['compose'], c['config']
    def call(path, method='GET', body=None, token=None, key=None, status=200):
        headers = {'Authorization': 'Bearer ' + (token or c['admin_token']), 'Content-Type': 'application/json'}
        if method != 'GET': headers['Idempotency-Key'] = key or str(uuid.uuid4())
        req = urllib.request.Request(c['base'] + path, data=None if body is None else json.dumps(body).encode(), method=method, headers=headers)
        try: response = urllib.request.urlopen(req, timeout=25)
        except urllib.error.HTTPError as error: response = error
        with response:
            raw = response.read(); value = json.loads(raw) if raw else None
            assert response.status == status, (method, path, response.status, value)
            return value, raw, response.headers.get('Location')
    def sql(statement):
        return compose('exec','-T','-e','PGPASSWORD','postgres','psql','-h','127.0.0.1','-U','agrosphere_operations_app','-d','agrosphere_operations','-At','-v','ON_ERROR_STOP=1',environment={'PGPASSWORD':config['OPERATIONS_APP_DB_PASSWORD']},input_text=statement).stdout.strip()
    def scoped(name, role, estate):
        user = c['user'](name, role); management = admin_token(config)
        url = c['realm'] + '/users/' + user['id']; value, _ = request(url, token=management)
        value['attributes'] = {**value.get('attributes', {}), 'estate_ids': [estate]}
        request(url, 'PUT', value, management, expected=204)
        return login(config, user)
    # Country and timezone are synthetic fixture choices, not actual plantation facts.
    estate = c['call']('/estates', 'POST', {'estateCode':'SIMWA1','name':'SIMULATED WA verification','countryCode':'GA','timezone':'Africa/Libreville','status':'ACTIVE'},status=201)['id']
    today = datetime.now(ZoneInfo('Africa/Libreville')).date()
    supervisor = scoped('wa-supervisor', 'FIELD_SUPERVISOR', estate)
    auditor = scoped('wa-auditor', 'AUDITOR', estate)
    viewer = scoped('wa-viewer', 'VIEWER', estate)
    foreign = scoped('wa-foreign-manager', 'ESTATE_MANAGER', c['estate'])
    body = {'estateId':estate,'workerCode':'sim-wa-1','displayName':'SIMULATED Worker','activeFrom':(today-timedelta(days=2)).isoformat(),'dataProvenance':'SIMULATED'}
    key = str(uuid.uuid4()); worker, original, location = call('/workers','POST',body,key=key,status=201)
    wid = worker['id']; assert worker['workerCode'] == 'SIM-WA-1' and worker['version'] == 0
    for token in [viewer, foreign, c['worker_token']]: call('/workers/'+wid,token=token,status=403)
    call('/workers','POST',{**body,'workerCode':'SIM-REAL','dataProvenance':'REAL'},status=403)
    call('/workers/'+wid+'/history',token=supervisor,status=403)
    root = '/attendance/days'
    call(root,'POST',{'workerRegistrationId':wid,'attendanceDate':(today-timedelta(days=1)).isoformat(),'status':'PRESENT','backdateReason':'SIMULATED'},token=supervisor,status=403)
    day, _, _ = call(root,'POST',{'workerRegistrationId':wid,'attendanceDate':today.isoformat(),'status':'PRESENT'},token=supervisor,status=201)
    did = day['id']; assert day['estateTimezone'] == 'Africa/Libreville'
    roster, _, _ = call('/attendance/roster?estateId='+estate+'&date='+today.isoformat()+'&provenance=SIMULATED',token=supervisor)
    assert (roster['eligibleCount'], roster['markedCount'], roster['unmarkedCount']) == (1,1,0)
    call(root+'/'+did+'/corrections','POST',{'version':0,'status':'ABSENT','reason':'SIMULATED correction'})
    call(root+'/'+did+'/void','POST',{'version':1,'reason':'SIMULATED void'})
    roster, _, _ = call('/attendance/roster?estateId='+estate+'&date='+today.isoformat()+'&provenance=SIMULATED',token=auditor)
    assert (roster['markedCount'],roster['unmarkedCount'],roster['voidedCount']) == (0,1,1)
    call(root+'/'+did+'/re-record','POST',{'version':2,'status':'EXCUSED','reason':'SIMULATED re-record'})
    call('/workers/'+wid,'PATCH',{'version':0,'displayName':'SIMULATED Updated','reason':'SIMULATED profile'})
    call('/workers/'+wid+'/close-period','POST',{'version':1,'activePeriodId':worker['activePeriods'][0]['id'],'activeTo':today.isoformat(),'reason':'SIMULATED conflicting closure'},status=409)
    call('/workers/'+wid+'/close-period','POST',{'version':1,'activePeriodId':worker['activePeriods'][0]['id'],'activeTo':(today+timedelta(days=1)).isoformat(),'reason':'SIMULATED closure'})
    history, _, _ = call('/workers/'+wid+'/history',token=auditor); assert history['totalElements'] == 3
    history, _, _ = call(root+'/'+did+'/history',token=auditor); assert history['totalElements'] == 4
    _, replay, replay_location = call('/workers','POST',body,key=key,status=201)
    assert replay == original and location == replay_location
    # Reopen an ended synthetic period without changing existing worker identifiers.
    ended, _, _ = call('/workers','POST',{**body,'workerCode':'SIM-WA-ENDED'},status=201)
    call('/workers/'+ended['id']+'/close-period','POST',{'version':0,'activePeriodId':ended['activePeriods'][0]['id'],'activeTo':today.isoformat(),'reason':'SIMULATED ended'})
    reopened, _, _ = call('/workers/'+ended['id']+'/open-period','POST',{'version':1,'activeFrom':today.isoformat(),'reason':'SIMULATED reopened'})
    assert len(reopened['activePeriods']) == 2
    compose('stop','rabbitmq')
    outage, _, _ = call('/workers','POST',{**body,'workerCode':'SIM-WA-OUTAGE'},status=201)
    identity = sql("SELECT event_id::text||'|'||md5(payload::text) FROM outbox_event WHERE aggregate_id='"+outage['id']+"';")
    assert identity and sql("SELECT count(*) FROM outbox_event WHERE aggregate_id='"+outage['id']+"' AND published_at IS NOT NULL;") == '0'
    compose('start','rabbitmq')
    for _ in range(90):
        if sql('SELECT count(*) FROM outbox_event WHERE published_at IS NULL;') == '0': break
        time.sleep(1)
    assert sql('SELECT count(*) FROM outbox_event WHERE published_at IS NULL;') == '0'
    assert identity == sql("SELECT event_id::text||'|'||md5(payload::text) FROM outbox_event WHERE aggregate_id='"+outage['id']+"';")
    code = """import os,json,urllib.request,base64
url='http://rabbitmq:15672/api/queues/%2F/agrosphere.dev.workforce.v1'
headers={'Authorization':'Basic '+base64.b64encode(('agrosphere:'+os.environ['RABBITMQ_PASSWORD']).encode()).decode(),'Content-Type':'application/json'}
q=json.load(urllib.request.urlopen(urllib.request.Request(url,headers=headers)));assert q['durable'] and q['arguments']['x-max-length']==10000
r=urllib.request.Request(url+'/get',data=json.dumps({'count':100,'ackmode':'ack_requeue_false','encoding':'auto','truncate':50000}).encode(),headers=headers,method='POST')
messages=json.load(urllib.request.urlopen(r));events=[json.loads(m['payload']) for m in messages]
assert {'WorkerRegistrationCreated','WorkerRegistrationChanged','WorkerAttendanceRecorded','WorkerAttendanceChanged'} == {e['eventType'] for e in events}
for e in events:
 assert e['eventVersion']==1 and e['dataProvenance']=='SIMULATED'
 assert not {'displayName','workerCode','workerCodeSnapshot','reason','recordedBy','actor','blockId'} & set(e['payload']['snapshot'])
print('PASS: all four minimal workforce v1 families received from durable bounded sink')
"""
    print(compose('run','--rm','--no-deps','-T','rabbitmq-init','python','-c',code).stdout.strip(),flush=True)
    print('PASS: WA-1 real Keycloak/Gateway/Estate, role scope, SIMULATED gate, lifecycle/history/coverage, original receipt replay and broker outage recovery; retained 3A/3B passed.',flush=True)


if __name__ == '__main__': main(workforce)
