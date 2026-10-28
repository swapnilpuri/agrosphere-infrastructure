"""Isolated local Compose acceptance. Never reads or alters the developer's .env/users.
Builds independently tagged images, creates disposable random credentials and volumes,
uses real Keycloak Code/PKCE, and removes only its own project in finally.
"""
import json,os,secrets,socket,subprocess,tempfile,time,uuid,urllib.request,urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from platform_support import ROOT,request,admin_token
from dev_identity import login
from configure_identity import configure

def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));return sock.getsockname()[1]

def main(extra_acceptance=None):
    project='agrosphere-3a-check-'+uuid.uuid4().hex[:8]
    oidc_port,gateway_port=free_port(),free_port()
    while gateway_port==oidc_port: gateway_port=free_port()
    keys=['POSTGRES_ADMIN_PASSWORD','ESTATE_DB_PASSWORD','SPATIAL_DB_PASSWORD','OPERATIONS_DB_PASSWORD','OPERATIONS_APP_DB_PASSWORD','TELEMETRY_DB_PASSWORD','ANALYTICS_DB_PASSWORD','AI_DB_PASSWORD','KEYCLOAK_DB_PASSWORD','KEYCLOAK_ADMIN_PASSWORD','RABBITMQ_PASSWORD']
    config={key:secrets.token_urlsafe(28) for key in keys}
    config.update(COMPOSE_PROJECT_NAME=project,OIDC_PUBLIC_URL=f'http://localhost:{oidc_port}',ESTATE_IMAGE=project+'-estate',GATEWAY_IMAGE=project+'-gateway',OPERATIONS_IMAGE=project+'-operations',GATEWAY_RATE_LIMIT='1000',TRACING_SAMPLE_PROBABILITY='0')
    env={**os.environ,**config}
    with tempfile.TemporaryDirectory(prefix='agrosphere-3a-') as temporary:
        override=Path(temporary)/'override.yaml'
        # !override replaces existing port arrays rather than merging with occupied developer ports.
        override.write_text('services:\n'+''.join(f'  {name}:\n    ports: !override []\n' for name in ['postgres','rabbitmq','jaeger','otel-collector'])+f'  keycloak:\n    ports: !override ["127.0.0.1:{oidc_port}:8080"]\n  gateway:\n    ports: !override ["127.0.0.1:{gateway_port}:8080"]\n')
        command=['docker','compose','--project-name',project,'--env-file',str(Path(temporary)/'empty.env'),'-f',str(ROOT/'compose.yaml'),'-f',str(override),'--profile','apps']
        (Path(temporary)/'empty.env').write_text('')
        def compose(*args,check=True,environment=None,input_text=None):
            result=subprocess.run([*command,*args],cwd=ROOT,env={**env,**(environment or {})},input=input_text,capture_output=True,text=True)
            if check and result.returncode:
                # Docker build output contains no supplied credentials; do not print config/logs.
                raise RuntimeError('Isolated Compose '+args[0]+' failed; '+(result.stdout+result.stderr if args[0]=='build' else result.stderr[-1200:]))
            return result
        try:
            compose('config','--quiet')
            print('Building independent Operations, Estate and Gateway images...',flush=True)
            compose('build','operations','estate','gateway')
            print('Starting isolated Compose project '+project+'...',flush=True)
            compose('up','-d','--wait','--wait-timeout','240')
            print('All Compose services healthy; exercising real Keycloak and gateway workflows...',flush=True)
            configure(config)
            realm=config['OIDC_PUBLIC_URL']+'/admin/realms/agrosphere'
            kc=admin_token(config)
            def user(name,role):
                nonlocal kc
                kc=admin_token(config)
                value={'username':'verify-'+name,'password':secrets.token_urlsafe(28)}
                request(realm+'/users','POST',{'username':value['username'],'enabled':True,'emailVerified':True,'firstName':'Verification','lastName':name,'email':name+'@example.invalid','credentials':[{'type':'password','value':value['password'],'temporary':False}]},kc,expected=201)
                matches,_=request(realm+'/users?exact=true&username='+value['username'],token=kc)
                value['id']=matches[0]['id'];definition,_=request(realm+'/roles/'+role,token=kc)
                request(realm+'/users/'+value['id']+'/role-mappings/realm','POST',[definition],kc,expected=204)
                return value
            admin=user('admin','PLATFORM_ADMIN');worker=user('worker','FIELD_WORKER');auditor=user('auditor','AUDITOR')
            token=login(config,admin)
            import base64
            claims=json.loads(base64.urlsafe_b64decode(token.split('.')[1]+'=='))
            assert 'PLATFORM_ADMIN' in claims.get('realm_access',{}).get('roles',[]),'Administrator role missing from trusted claim'
            assert 'operations-service' in claims.get('aud',[]),'Operations audience missing'
            assert claims.get('sub')==admin['id'],'Canonical subject missing'
            base=f'http://127.0.0.1:{gateway_port}/api/v1'
            def call(path,method='GET',body=None,bearer=token,status=200):
                headers={'Authorization':'Bearer '+bearer,'Content-Type':'application/json'}
                req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),method=method,headers=headers)
                try: response=urllib.request.urlopen(req,timeout=20)
                except urllib.error.HTTPError as error: response=error
                with response:
                    raw=response.read();value=json.loads(raw) if raw else None
                    if response.status!=status:
                        detail={k:value.get(k) for k in ('status','title','detail') } if isinstance(value,dict) else None
                        raise AssertionError(f'{method} {path}: expected {status}, got {response.status}; {detail}')
                    return value
            estate=call('/estates','POST',{'estateCode':'VERIFY3A','name':'SIMULATED tapping verification','countryCode':'LK','timezone':'Asia/Colombo','status':'ACTIVE'},status=201)['id']
            division=call('/estates/'+estate+'/divisions','POST',{'estateId':estate,'divisionCode':'D1','name':'Verification','status':'ACTIVE'},status=201)['id']
            block=call('/divisions/'+division+'/blocks','POST',{'estateId':estate,'divisionId':division,'blockCode':'B1','name':'Verification','cropType':'RUBBER','plantedAreaHectares':1,'plantedTreeCount':100,'tappableTreeCount':80,'status':'ACTIVE'},status=201)['id']
            for value in [worker,auditor]:
                user_url=realm+'/users/'+value['id']
                current,_=request(user_url,token=kc)
                current['attributes']={**current.get('attributes',{}),'estate_ids':[estate]}
                request(user_url,'PUT',current,kc,expected=204)
            worker_token=login(config,worker);audit_token=login(config,auditor)
            worker_claims=json.loads(base64.urlsafe_b64decode(worker_token.split('.')[1]+'=='))
            assert worker_claims.get('sub')==worker['id'],'Worker subject mismatch'
            assert worker_claims.get('estate_ids')==[estate],'Trusted estate scope missing or malformed'
            today=datetime.now(ZoneInfo('Asia/Colombo')).date().isoformat()
            schedule=call('/tapping/schedules','POST',{'estateId':estate,'blockId':block,'name':'SIMULATED daily','recurrenceRule':'DAILY','plannedTreeCount':10,'effectiveFrom':today},status=201)['id']
            call('/tapping/schedules/'+schedule+'/activate','POST',{'version':0})
            generation={'version':1,'from':today,'to':today,'workerId':worker['id']}
            assignment=call('/tapping/schedules/'+schedule+'/generate-assignments','POST',generation)[0]['id']
            assert call('/tapping/schedules/'+schedule+'/generate-assignments','POST',generation)[0]['id']==assignment
            call('/tapping/assignments/'+assignment+'/start','POST',{'version':0},worker_token)
            completion={'version':1,'actualTreeCount':8,'notes':'SIMULATED verification'}
            call('/tapping/assignments/'+assignment+'/complete','POST',completion,worker_token)
            call('/tapping/assignments/'+assignment+'/complete','POST',completion,worker_token)
            call('/tapping/assignments/'+assignment+'/cancel','POST',{'version':2},audit_token,403)
            summary=call('/tapping/summary?estateId='+estate,bearer=audit_token)['content'][0]
            assert summary['completion_percentage']==100 and summary['actual_trees']==8
            # Read Operations-owned outbox only through its service database user.
            sql="select count(*) from outbox_event where published_at is not null"
            published=0
            for attempt in range(20):
                result=compose('exec','-T','-e','PGPASSWORD','postgres','psql','-h','127.0.0.1','-U','agrosphere_operations_app','-d','agrosphere_operations','-Atc',sql,environment={'PGPASSWORD':config['OPERATIONS_APP_DB_PASSWORD']})
                published=int(result.stdout.strip())
                if published==4:break
                time.sleep(0.5)
            assert published==4,'Outbox not confirmed/routed'
            print('PASS: isolated Compose health, independent Docker builds, real Keycloak PKCE/JWT, Gateway routing, Estate validation for worker, generation deduplication, completion retry, auditor denial, summary and four confirmed events.',flush=True)
            if extra_acceptance:
                extra_acceptance(config=config,compose=compose,call=call,user=user,base=base,estate=estate,block=block,assignment=assignment,worker=worker,worker_token=worker_token,admin=admin,admin_token=token,audit_token=audit_token,realm=realm,keycloak_token=kc)
        finally:
            compose('down','--volumes','--remove-orphans',check=False)
            print('Removed only isolated verification project '+project,flush=True)
if __name__=='__main__':main()
