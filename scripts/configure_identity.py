"""Apply reviewed local client scopes/profile without replacing users or the realm."""
import json
from platform_support import ROOT,configuration,request,admin_token

def configure(config):
    realm=json.loads((ROOT/'keycloak/agrosphere-realm.json').read_text())
    base=config.get('OIDC_PUBLIC_URL','http://localhost:8180')+'/admin/realms/agrosphere'
    token=admin_token(config)
    scopes,_=request(base+'/client-scopes',token=token)
    for desired in realm['clientScopes']:
        found=next((s for s in scopes if s['name']==desired['name']),None)
        if found is None:
            request(base+'/client-scopes','POST',desired,token,expected=201)
            scopes,_=request(base+'/client-scopes',token=token)
            found=next(s for s in scopes if s['name']==desired['name'])
        scope_url=base+'/client-scopes/'+found['id']
        current,_=request(scope_url+'/protocol-mappers/models',token=token)
        for mapper in desired['protocolMappers']:
            existing=next((m for m in current if m['name']==mapper['name']),None)
            if existing: request(scope_url+'/protocol-mappers/models/'+existing['id'],'PUT',{**mapper,'id':existing['id']},token,expected=204)
            else: request(scope_url+'/protocol-mappers/models','POST',mapper,token,expected=201)
    for desired in realm['clients']:
        matches,_=request(base+'/clients?clientId='+desired['clientId'],token=token)
        if matches: request(base+'/clients/'+matches[0]['id'],'PUT',desired,token,expected=204)
        else: request(base+'/clients','POST',desired,token,expected=201)
    profile=json.loads(realm['components']['org.keycloak.userprofile.UserProfileProvider'][0]['config']['kcUserProfileConfig'][0])
    current_profile,_=request(base+'/users/profile',token=token)
    estate_attribute=next(a for a in profile['attributes'] if a['name']=='estate_ids')
    attributes=[a for a in current_profile.get('attributes',[]) if a['name']!='estate_ids']
    current_profile['attributes']=[*attributes,estate_attribute]
    request(base+'/users/profile','PUT',current_profile,token)
    print('Applied local audience, trusted roles and administrator-only estate scope configuration.')
if __name__=='__main__': configure(configuration())
