"""AN-1 plus retained II/WA/3B/3A in a new generated-only Compose project."""
import json
import time
import uuid
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from verify_tapping import main
from verify_crop_health import crop_health
from platform_support import request, admin_token
from dev_identity import login


def uuid7():
    at=int(time.time()*1000)
    return str(uuid.UUID(int=(at<<80)|(7<<76)|(int.from_bytes(__import__('os').urandom(2),'big')&4095)<<64|(2<<62)|(int.from_bytes(__import__('os').urandom(8),'big')&((1<<62)-1))))


def privacy_alerts(**c):
    crop_health(**c)
    def call(path, method='GET', body=None, token=None, key=None, status=200):
        headers={'Authorization':'Bearer '+(token or c['admin_token']), 'Content-Type':'application/json'}
        if method!='GET':headers['Idempotency-Key']=key or (uuid7() if path.startswith('/alerts') else str(uuid.uuid4()))
        base=c['base'].removesuffix('/api/v1')+'/api/v2' if path.startswith('/alerts') else c['base']
        req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),method=method,headers=headers)
        try:r=urllib.request.urlopen(req,timeout=30)
        except urllib.error.HTTPError as error:r=error
        with r:
            raw=r.read();value=json.loads(raw) if raw else None
            assert r.status==status,(method,path,r.status,value)
            if path.startswith('/alerts'):assert r.headers.get('Cache-Control')=='no-store'
            return value,raw
    call('/alerts/counts?estateId='+c['estate'],status=503)
    observed=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(timespec='microseconds')
    body={'estateId':c['estate'],'blockId':c['block'],'dataProvenance':'SIMULATED','observedAt':observed,
          'category':'TREE_DAMAGE','severity':'HIGH','summary':'SIMULATED alert source','details':'SIMULATED generated evidence'}
    prior,_=call('/incidents','POST',body,status=201)
    manager=c['user']('alert-manager','ESTATE_MANAGER')
    management=admin_token(c['config']);url=c['realm']+'/users/'+manager['id'];profile,_=request(url,token=management)
    profile['attributes']={**profile.get('attributes',{}),'estate_ids':[c['estate']]};request(url,'PUT',profile,management,expected=204)
    manager_token=login(c['config'],manager)
    subjects=[c['admin']['id'],manager['id']]
    manager_b=None
    if c.get('poc_owner'):
        manager_b=c['user']('alert-manager-b','ESTATE_MANAGER')
        management=admin_token(c['config']);url=c['realm']+'/users/'+manager_b['id'];profile,_=request(url,token=management)
        profile['attributes']={**profile.get('attributes',{}),'estate_ids':[c['estate']]};request(url,'PUT',profile,management,expected=204)
        subjects.append(manager_b['id'])
    c['enable_generated_alerts'](subjects,privacy=True)
    counts,_=call('/alerts/counts?estateId='+c['estate']);assert counts['activeTotal']==0,'No historical backfill'
    call('/incidents/'+prior['id']+'/triage','POST',{'expectedVersion':0,'reason':'SIMULATED future command'})
    page,_=call('/alerts?estateId='+c['estate']);assert page['totalElements']==1;alert=page['content'][0];aid=alert['id']
    assert alert['sourceVersion']==1 and alert['unreadForMe'] and not alert['acknowledged']
    assert alert['policyVersion']=='AN_PRIVACY_PROVISIONAL_1' and alert['readState']=='UNREAD'
    assert not {'summary','details','acknowledgedBy','recipients','subject'} & set(alert)
    read,_=call('/alerts/'+aid+'/read','POST',{'attentionVersion':1},token=manager_token);assert not read['unreadForMe'] and not read['acknowledged']
    other,_=call('/alerts/'+aid);assert other['unreadForMe'],'Personal reads do not fan out'
    if manager_b:
        manager_b_token=login(c['config'],manager_b)
        other_b,_=call('/alerts/'+aid,token=manager_b_token);assert other_b['unreadForMe']
    key=uuid7();command={'expectedAlertVersion':1,'attentionVersion':1}
    ack,original=call('/alerts/'+aid+'/acknowledgements','POST',command,token=manager_token,key=key);assert ack['acknowledged'] and ack['alertVersion']==2
    if manager_b:
        shared,_=call('/alerts/'+aid,token=manager_b_token);assert shared['acknowledged'] and shared['unreadForMe']
    call('/alerts/'+aid+'/acknowledgements','POST',{'expectedAlertVersion':2,'attentionVersion':1},status=409)
    call('/incidents/'+prior['id']+'/resolve','POST',{'expectedVersion':1,'reason':'SIMULATED closure','resolvedAt':datetime.now(timezone.utc).isoformat(timespec='microseconds'),'resolutionNote':'SIMULATED resolution'})
    _,replay=call('/alerts/'+aid+'/acknowledgements','POST',command,token=manager_token,key=key);assert original==replay
    call('/incidents/'+prior['id']+'/reopen','POST',{'expectedVersion':2,'reason':'SIMULATED revisit'})
    current,_=call('/alerts/'+aid);assert current['attentionVersion']==2 and not current['acknowledged'] and current['unreadForMe']
    call('/alerts/'+aid+'/read','POST',{'attentionVersion':1},status=409)
    history,_=call('/alerts/'+aid+'/history');assert history['totalElements']==4
    call('/alerts/'+aid,token=c['worker_token'],status=403)
    call('/incidents','POST',{**body,'dataProvenance':'REAL'},status=403)
    # No new consumer/queue: broker outage affects source publication, not inbox visibility.
    c['compose']('stop','rabbitmq')
    try:
        source,_=call('/incidents','POST',body,status=201)
        page,_=call('/alerts?estateId='+c['estate']);assert any(a['incidentId']==source['id'] for a in page['content'])
    finally:c['compose']('start','rabbitmq')
    for _ in range(90):
        status=c['compose']('exec','-T','-e','PGPASSWORD','postgres','psql','-h','127.0.0.1','-U','agrosphere_operations_app','-d','agrosphere_operations','-Atc','SELECT count(*) FROM outbox_event WHERE published_at IS NULL;',environment={'PGPASSWORD':c['config']['OPERATIONS_APP_DB_PASSWORD']}).stdout.strip()
        if status=='0':break
        time.sleep(1)
    assert status=='0','Existing outbox recovery must complete'
    if c.get('poc_owner'):
        from poc_close_privacy import verify as verify_policy
        verify_policy(c,call,manager,manager_b)
    print('PASS: privacy v2 real generated Keycloak/Gateway/Estate/Operations source->inbox->own read->shared ack->resolve/reopen; no backfill, role/REAL denial, original replay and broker-independent inbox. Retained II/WA/3B/3A passed.',flush=True)


if __name__=='__main__':main(privacy_alerts)
