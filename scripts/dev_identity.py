"""Development users and real Authorization Code + PKCE authentication; no password grant."""
import base64
import hashlib
import http.cookiejar
from html.parser import HTMLParser
import json
import secrets
import urllib.parse
import urllib.request
import urllib.error
from platform_support import ROOT,request,admin_token

def users(config):
    secret_file=ROOT/'local-secrets/dev-users.json';secret_file.parent.mkdir(exist_ok=True)
    known=json.loads(secret_file.read_text()) if secret_file.exists() else {}
    base=config.get('OIDC_PUBLIC_URL','http://localhost:8180')+'/admin/realms/agrosphere'
    token=admin_token(config)
    for key,role in [('admin','PLATFORM_ADMIN'),('manager','ESTATE_MANAGER'),('viewer','VIEWER'),('outsider','VIEWER')]:
        username='dev-'+key
        found,_=request(base+'/users?exact=true&username='+username,token=token)
        if key not in known:
            if found: raise RuntimeError(username+' already exists without local credentials; no password was reset')
            known[key]={'username':username,'password':secrets.token_urlsafe(28)}
            request(base+'/users','POST',{'username':username,'enabled':True,'emailVerified':True,'firstName':'Development','lastName':key,
                'email':username+'@example.invalid','credentials':[{'type':'password','value':known[key]['password'],'temporary':False}]},token,expected=201)
            with secret_file.open('w') as out:json.dump(known,out,indent=2)
            found,_=request(base+'/users?exact=true&username='+username,token=token)
        if not found:raise RuntimeError('Saved development user is absent from this realm; no credentials were overwritten')
        known[key]['id']=found[0]['id']
        definition,_=request(base+'/roles/'+role,token=token)
        request(base+'/users/'+found[0]['id']+'/role-mappings/realm','POST',[definition],token,expected=204)
    with secret_file.open('w') as out:json.dump(known,out,indent=2)
    return known

def assign_estate(config,user,estate):
    base=config.get('OIDC_PUBLIC_URL','http://localhost:8180')+'/admin/realms/agrosphere/users/'+user['id']
    token=admin_token(config);current,_=request(base,token=token);attributes=current.get('attributes',{})
    attributes['estate_ids']=list(dict.fromkeys([*attributes.get('estate_ids',[]),estate]))
    request(base,'PUT',{'attributes':attributes},token,expected=204)

class LoginForm(HTMLParser):
    action=None
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='form' and attrs.get('id')=='kc-form-login':self.action=attrs.get('action')

class LocalhostCookiePolicy(http.cookiejar.DefaultCookiePolicy):
    # Chromium treats HTTP localhost as a trustworthy origin and send Secure cookies there.
    # Match that behavior only for loopback; retain normal Secure policy everywhere else.
    def return_ok_secure(self,cookie,request):
        url=urllib.parse.urlparse(request.get_full_url())
        if url.scheme=='http' and url.hostname in ('localhost','127.0.0.1','::1'):return True
        return super().return_ok_secure(cookie,request)

class NoCallback(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if newurl.startswith('http://localhost:4200/smoke-callback'):return None
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def login(config,user):
    issuer=config.get('OIDC_PUBLIC_URL','http://localhost:8180')+'/realms/agrosphere'
    verifier=secrets.token_urlsafe(48);state=secrets.token_urlsafe(24)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    redirect='http://localhost:4200/smoke-callback'
    query=urllib.parse.urlencode({'client_id':'agrosphere-integration-tests','response_type':'code','redirect_uri':redirect,
        'scope':'openid agrosphere-api','state':state,'code_challenge':challenge,'code_challenge_method':'S256'})
    opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar(policy=LocalhostCookiePolicy())),NoCallback())
    # Keep the advertised hostname for session cookies and exact OIDC redirect checks.
    with opener.open(issuer+'/protocol/openid-connect/auth?'+query,timeout=20) as response:
        form=LoginForm();form.feed(response.read().decode())
    if not form.action:raise AssertionError('Keycloak did not return the configured login form')
    post=urllib.request.Request(form.action,data=urllib.parse.urlencode({'username':user['username'],'password':user['password'],'credentialId':''}).encode())
    try:
        with opener.open(post,timeout=20) as response:response.read()
        raise AssertionError('PKCE login did not redirect with an authorization code')
    except urllib.error.HTTPError as response:
        if response.code!=302:raise AssertionError('Development user login failed: HTTP '+str(response.code)) from None
        callback=urllib.parse.parse_qs(urllib.parse.urlparse(response.headers['Location']).query)
    assert callback.get('state')==[state] and 'code' in callback,'OIDC callback state/code mismatch'
    data,_=request(issuer+'/protocol/openid-connect/token','POST',{'grant_type':'authorization_code','client_id':'agrosphere-integration-tests',
        'redirect_uri':redirect,'code_verifier':verifier,'code':callback['code'][0]},form=True)
    return data['access_token']

if __name__=='__main__':
    from platform_support import configuration
    users(configuration());print('Development users ready; private passwords are in ignored local-secrets/dev-users.json.')
