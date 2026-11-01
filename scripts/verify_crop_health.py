"""II-1 plus retained 3A/3B/WA-1 in verify_tapping's generated disposable Compose project."""
import json
import uuid
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from verify_tapping import main
from verify_workforce import workforce


def crop_health(**c):
    workforce(**c)
    compose, config = c['compose'], c['config']
    def call(path, method='GET', body=None, token=None, key=None, status=200):
        headers={'Authorization':'Bearer '+(token or c['admin_token']), 'Content-Type':'application/json', 'X-Correlation-ID':str(uuid.uuid4())}
        if method != 'GET': headers['Idempotency-Key']=key or str(uuid.uuid4())
        req=urllib.request.Request(c['base']+path, data=None if body is None else json.dumps(body).encode(),method=method,headers=headers)
        try: response=urllib.request.urlopen(req,timeout=25)
        except urllib.error.HTTPError as e: response=e
        with response:
            raw=response.read();value=json.loads(raw) if raw else None
            assert response.status==status,(method,path,response.status,value)
            return value,raw,response.headers.get('Location')
    def sql(query):
        return compose('exec','-T','-e','PGPASSWORD','postgres','psql','-h','127.0.0.1','-U','agrosphere_operations_app','-d','agrosphere_operations','-At','-v','ON_ERROR_STOP=1',environment={'PGPASSWORD':config['OPERATIONS_APP_DB_PASSWORD']},input_text=query).stdout.strip()
    observed=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(timespec='microseconds')
    body={'estateId':c['estate'],'blockId':c['block'],'dataProvenance':'SIMULATED','observedAt':observed,'outcome':'FOLLOW_UP','findings':'SIMULATED field finding',
          'incident':{'category':'TREE_DAMAGE','severity':'LOW','summary':'SIMULATED observation','details':'SIMULATED details'}}
    key=str(uuid.uuid4());created,raw,location=call('/inspections','POST',body,key=key,status=201)
    i,incident=created['inspection']['id'],created['incident']['id'];assert i!=incident
    assert created['incident']['inspectionId']==i and created['inspection']['linkedIncidentId']==incident
    call('/inspections','POST',{**body,'dataProvenance':'REAL'},status=403)
    call('/incidents/'+incident,token=c['worker_token'],status=403)
    call('/incidents/'+incident+'/triage','POST',{'expectedVersion':0,'inspectionVersion':0,'reason':'SIMULATED triage'})
    call('/incidents/'+incident+'/resolve','POST',{'expectedVersion':1,'inspectionVersion':0,'resolvedAt':datetime.now(timezone.utc).isoformat(timespec='microseconds'),'resolutionNote':'SIMULATED closure','reason':'SIMULATED resolution'})
    call('/incidents/'+incident+'/reopen','POST',{'expectedVersion':2,'inspectionVersion':0,'reason':'SIMULATED revisit'})
    call('/incidents/'+incident+'/void','POST',{'expectedVersion':3,'inspectionVersion':0,'reason':'SIMULATED invalid report'})
    call('/inspections/'+i+'/corrections','POST',{'inspectionVersion':0,'incidentVersion':4,'observedAt':observed,'outcome':'CLEAR','findings':'SIMULATED corrected finding','reason':'SIMULATED correction'})
    call('/inspections/'+i+'/void','POST',{'inspectionVersion':1,'incidentVersion':4,'reason':'SIMULATED invalid inspection'})
    _,replayed,replay_location=call('/inspections','POST',body,key=key,status=201);assert raw==replayed and location==replay_location
    history,_,_=call('/incidents/'+incident+'/history');assert history['totalElements']==5
    compose('stop','rabbitmq')
    outage_body={'estateId':c['estate'],'blockId':c['block'],'dataProvenance':'SIMULATED','observedAt':observed,**body['incident']}
    outage,_,_=call('/incidents','POST',outage_body,status=201)
    identity=sql("SELECT event_id::text||'|'||md5(payload::text) FROM outbox_event WHERE aggregate_id='"+outage['id']+"';")
    compose('start','rabbitmq')
    for _ in range(90):
        if sql('SELECT count(*) FROM outbox_event WHERE published_at IS NULL;')=='0': break
        time.sleep(1)
    assert sql('SELECT count(*) FROM outbox_event WHERE published_at IS NULL;')=='0'
    assert identity==sql("SELECT event_id::text||'|'||md5(payload::text) FROM outbox_event WHERE aggregate_id='"+outage['id']+"';")
    code="""import os,json,urllib.request,base64
url='http://rabbitmq:15672/api/queues/%2F/agrosphere.dev.crop-health.v1'
headers={'Authorization':'Basic '+base64.b64encode(('agrosphere:'+os.environ['RABBITMQ_PASSWORD']).encode()).decode(),'Content-Type':'application/json'}
q=json.load(urllib.request.urlopen(urllib.request.Request(url,headers=headers)));assert q['durable'] and q['arguments']['x-max-length']==10000
req=urllib.request.Request(url+'/get',data=json.dumps({'count':100,'ackmode':'ack_requeue_false','encoding':'auto','truncate':50000}).encode(),headers=headers,method='POST')
events=[json.loads(m['payload']) for m in json.load(urllib.request.urlopen(req))]
assert {e['eventType'] for e in events}=={'FieldInspectionRecorded','FieldInspectionChanged','CropHealthIncidentReported','CropHealthIncidentChanged'}
for e in events:
 s=e['payload']['snapshot'];assert e['dataProvenance']=='SIMULATED' and e['aggregateId']==s['id'] and e['aggregateVersion']==s['version']
 assert not {'summary','details','findings','reason','recordedBy','resolutionNote','createdBy','updatedBy'} & set(s)
print('PASS: all four minimal crop-health families received from bounded durable sink')
"""
    print(compose('run','--rm','--no-deps','-T','rabbitmq-init','python','-c',code).stdout.strip(),flush=True)
    print('PASS: II-1 real Keycloak/Gateway/Estate/Operations linked lifecycle, REAL/role denial, original receipt replay, immutable history and broker recovery; retained 3A/3B/WA-1 passed.',flush=True)


if __name__=='__main__':main(crop_health)
