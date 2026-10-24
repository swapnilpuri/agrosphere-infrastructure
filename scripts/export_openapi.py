"""Export authenticated backend OpenAPI without publicly exposing internal ports."""
import json
from platform_support import ROOT,configuration,internal_requests
from dev_identity import users,login
c=configuration();token=login(c,users(c)['admin'])
responses=internal_requests(c,[{'url':'http://estate:8081/v3/api-docs','token':token},{'url':'http://spatial:8082/v3/api-docs','token':token}])
(ROOT/'target').mkdir(exist_ok=True)
for name,response in zip(['estate','spatial'],responses):
    assert response['status']==200
    (ROOT/'target'/f'{name}.openapi.json').write_text(json.dumps(response['body'],indent=2)+'\n')
print('Exported authenticated OpenAPI to target/estate.openapi.json and target/spatial.openapi.json.')
