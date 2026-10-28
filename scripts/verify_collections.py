"""3B acceptance, using only verify_tapping's generated, disposable Compose project."""
import json
import time
import uuid
import urllib.request
import urllib.error
from datetime import datetime, timezone
from decimal import Decimal
from platform_support import request, admin_token
from dev_identity import login
from verify_tapping import main


def collections(**c):
    compose, config = c['compose'], c['config']
    correlation = str(uuid.uuid4())
    def call(path, method='GET', body=None, token=None, key=None, status=200):
        headers={'Authorization':'Bearer '+(token or c['admin_token']), 'Content-Type':'application/json', 'X-Correlation-ID':correlation}
        if key: headers['Idempotency-Key']=key
        req=urllib.request.Request(c['base']+'/tapping/collections'+path, data=None if body is None else json.dumps(body).encode(),method=method,headers=headers)
        try: response=urllib.request.urlopen(req,timeout=20)
        except urllib.error.HTTPError as error: response=error
        with response:
            raw=response.read(); value=json.loads(raw,parse_float=Decimal) if raw else None
            assert response.status==status, (method,path,response.status,value)
            return value,raw,response.headers.get('Location')
    def sql(statement):
        return compose('exec','-T','-e','PGPASSWORD','postgres','psql','-h','127.0.0.1','-U','agrosphere_operations_app','-d','agrosphere_operations','-At','-v','ON_ERROR_STOP=1',environment={'PGPASSWORD':config['OPERATIONS_APP_DB_PASSWORD']},input_text=statement).stdout.strip()
    records=c['call']('/tapping/records?estateId='+c['estate']+'&workerId='+c['worker']['id'])['content']
    record=next(r for r in records if r['assignmentId']==c['assignment'])['id']
    def body(ref,weight=125.5):
        return {'tappingRecordId':record,'collectionReference':ref,'collectedAt':datetime.now(timezone.utc).isoformat(timespec='microseconds'),'wetLatexKg':weight,'weightEvidence':{'method':'SCALE','sourceReference':'SIMULATED-ACCEPTANCE'},'dataProvenance':'SIMULATED'}
    first=body('LOT-A'); key=str(uuid.uuid4())
    created,raw,location=call('', 'POST',first,c['worker_token'],key,201)
    root=created['id']; assert created['wetLatexKg']==Decimal('125.5') and created['dryRubberKg'] is None
    measurement={'version':0,'measurement':{'drcPercent':32.4,'measuredAt':datetime.now(timezone.utc).isoformat(timespec='microseconds'),'method':'FIELD_TEST','sourceReference':'SIMULATED-DRC','dataProvenance':'SIMULATED'}}
    measured,_,_=call('/'+root+'/drc-measurements','POST',measurement,key=str(uuid.uuid4()))
    assert measured['dryRubberKg']==Decimal('40.662')
    corrected,_,_=call('/'+root+'/corrections','POST',{'version':1,'reason':'SIMULATED scale correction','wetLatexKg':100},key=str(uuid.uuid4()))
    assert corrected['dryRubberKg']==Decimal('32.400')
    _,replayed,replay_location=call('','POST',first,c['worker_token'],key,201)
    assert replayed==raw and replay_location==location
    second,_,_=call('','POST',body('LOT-B',1),c['worker_token'],str(uuid.uuid4()),201)
    day=created['collectionDate']; bounds='?from='+day+'&to='+day+'&dataProvenance=SIMULATED'
    summary,_,_=call('/summary'+bounds)
    row=summary['content'][0]; assert row['knownDryRubberKg']==Decimal('32.400') and row['pendingWetLatexKg']==1 and not row['isComplete']
    history,_,_=call('/'+root+'/history'); assert history['totalElements']==3
    # Another canonical subject in the same estate cannot read/replay this worker's lot.
    other=c['user']('other-worker','FIELD_WORKER')
    management_token=admin_token(config)
    url=c['realm']+'/users/'+other['id']; value,_=request(url,token=management_token)
    value['attributes']={**value.get('attributes',{}),'estate_ids':[c['estate']]};request(url,'PUT',value,management_token,expected=204)
    other_token=login(config,other)
    call('/'+root,token=other_token,status=403)
    own,_,_=call('',token=other_token);assert own['totalElements']==0
    foreign_estate=c['call']('/estates','POST',{'estateCode':'VERIFY3B2','name':'SIMULATED foreign estate','countryCode':'LK','timezone':'UTC','status':'ACTIVE'},status=201)['id']
    foreign=c['user']('foreign-viewer','VIEWER')
    management_token=admin_token(config);url=c['realm']+'/users/'+foreign['id'];value,_=request(url,token=management_token)
    value['attributes']={**value.get('attributes',{}),'estate_ids':[foreign_estate]};request(url,'PUT',value,management_token,expected=204)
    foreign_token=login(config,foreign)
    call('/'+root+'/history',token=foreign_token,status=403)
    foreign_list,_,_=call('',token=foreign_token);assert foreign_list['totalElements']==0
    call('/'+root+'/void','POST',{'version':2,'reason':'SIMULATED duplicate'},key=str(uuid.uuid4()))
    summary,_,_=call('/summary'+bounds);row=summary['content'][0]
    assert row['knownDryRubberKg']==0 and row['voidedCollectionCount']==1 and row['totalWetLatexKg']==1
    zero={'version':0,'measurement':{**measurement['measurement'],'drcPercent':0,'measuredAt':datetime.now(timezone.utc).isoformat(timespec='microseconds')}}
    call('/'+second['id']+'/drc-measurements','POST',zero,key=str(uuid.uuid4()))
    # Stop/restart only the random project's broker. Commands commit while it is down.
    compose('stop','rabbitmq')
    outage,_,_=call('','POST',body('LOT-OUTAGE',2),c['worker_token'],str(uuid.uuid4()),201)
    identity=sql("SELECT event_id::text||'|'||md5(payload::text) FROM outbox_event WHERE aggregate_id='"+outage['id']+"';")
    assert identity and sql("SELECT count(*) FROM outbox_event WHERE aggregate_id='"+outage['id']+"' AND published_at IS NOT NULL;")=='0'
    compose('start','rabbitmq')
    for attempt in range(90):
        pending=sql("SELECT count(*) FROM outbox_event WHERE published_at IS NULL;")
        if pending=='0':break
        time.sleep(1)
    assert pending=='0','Outbox did not recover'
    assert identity==sql("SELECT event_id::text||'|'||md5(payload::text) FROM outbox_event WHERE aggregate_id='"+outage['id']+"';")
    assert sql("SELECT count(*) FROM outbox_event WHERE event_version=2;")=='7'
    assert sql("SELECT count(*) FROM outbox_event WHERE event_version=2 AND correlation_id='"+correlation+"';")=='7'
    # Broker management runs inside this project's configured init service, never localhost's active broker.
    code="""import os,json,urllib.request,base64
url='http://rabbitmq:15672/api/queues/%2F/agrosphere.dev.collections.v2'
r=urllib.request.Request(url,headers={'Authorization':'Basic '+base64.b64encode(('agrosphere:'+os.environ['RABBITMQ_PASSWORD']).encode()).decode()})
q=json.load(urllib.request.urlopen(r));assert q['durable'] and q['arguments']['x-max-length']==10000;print('PASS: durable bounded collection v2 sink')
"""
    result=compose('run','--rm','--no-deps','-T','rabbitmq-init','python','-c',code)
    print(result.stdout.strip(),flush=True)
    print('PASS: real Keycloak/Gateway collection workflow, exact decimal calculations, original receipt replay, scoped reads, correction/history/summary/void, zero DRC, correlated v2 events and broker outage/recovery.',flush=True)


if __name__=='__main__': main(collections)
