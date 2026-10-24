"""Local tooling: never print configuration values or bearer tokens."""
import base64
import json
import os
from pathlib import Path
import subprocess
import urllib.request
import urllib.error
import urllib.parse
ROOT=Path(__file__).resolve().parents[1]
def configuration(file=None):
    result={}
    for line in Path(file or ROOT/'.env').read_text().splitlines():
        if line and not line.startswith('#') and '=' in line:
            key,value=line.split('=',1); result[key]=value
    return result

def request(url,method='GET',body=None,token=None,headers=None,expected=200,form=False):
    headers=dict(headers or {})
    if token: headers['Authorization']='Bearer '+token
    if body is not None:
        if form: body=urllib.parse.urlencode(body).encode();headers['Content-Type']='application/x-www-form-urlencoded'
        else: body=json.dumps(body).encode();headers['Content-Type']='application/json'
    url=url.replace('http://localhost:','http://127.0.0.1:')
    req=urllib.request.Request(url,data=body,method=method,headers=headers)
    try:
        response=urllib.request.urlopen(req,timeout=20)
    except urllib.error.HTTPError as error: response=error
    with response:
        raw=response.read();status=response.status
        if status != expected: raise AssertionError(f'{method} {urllib.parse.urlparse(url).path}: expected {expected}, got {status}')
        return (json.loads(raw) if raw else None),response.headers

def admin_token(config):
    url=config.get('OIDC_PUBLIC_URL','http://localhost:8180')
    data,_=request(url+'/realms/master/protocol/openid-connect/token','POST',{
        'grant_type':'password','client_id':'admin-cli','username':'agrosphere_admin','password':config['KEYCLOAK_ADMIN_PASSWORD']},form=True)
    return data['access_token']

def compose(config,*args,check=True):
    command=['docker','compose','--project-name',config.get('COMPOSE_PROJECT_NAME','agrosphere-local'),'--profile','apps',*args]
    result=subprocess.run(command,cwd=ROOT,env={**os.environ,**config},capture_output=True,text=True)
    if check and result.returncode: raise RuntimeError('Compose operation failed: '+' '.join(args[:2]))
    return result

def sql(config,service,statement,database=None,check=True):
    env={**config,'PGPASSWORD':config[service.upper()+'_DB_PASSWORD']}
    result=compose(env,'exec','-T','-e','PGPASSWORD','postgres','psql','-h','127.0.0.1','-U','agrosphere_'+service,
        '-d',database or 'agrosphere_'+service,'-v','ON_ERROR_STOP=1','-Atc',statement,check=check)
    return result.stdout.strip() if check else result

def broker(config,path,method='GET',body=None):
    auth=base64.b64encode(('agrosphere:'+config['RABBITMQ_PASSWORD']).encode()).decode()
    return request('http://localhost:15672/api/'+path,method,body,headers={'Authorization':'Basic '+auth})[0]


def internal_requests(config,calls):
    """Exercise internal resource servers through a disposable client; credentials travel on stdin."""
    code="""import json,sys,urllib.request,urllib.error
results=[]
for call in json.load(sys.stdin):
 headers={}
 if call.get('token'):headers['Authorization']='Bearer '+call['token']
 data=None
 if 'body' in call:data=json.dumps(call['body']).encode();headers['Content-Type']='application/json'
 try:r=urllib.request.urlopen(urllib.request.Request(call['url'],data=data,method=call.get('method','GET'),headers=headers),timeout=20)
 except urllib.error.HTTPError as e:r=e
 with r:
  raw=r.read();results.append({'status':r.status,'body':json.loads(raw) if raw else None})
print(json.dumps(results))"""
    command=['docker','compose','--project-name',config.get('COMPOSE_PROJECT_NAME','agrosphere-local'),'--profile','apps','run','--rm','--no-deps','-T','rabbitmq-init','python','-c',code]
    result=subprocess.run(command,cwd=ROOT,env={**os.environ,**config},input=json.dumps(calls),capture_output=True,text=True)
    if result.returncode:raise RuntimeError('Internal HTTP verification client failed')
    return json.loads(result.stdout)
