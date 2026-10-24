"""Real two-division/ten-block rubber plantation acceptance. No developer data is reset.
Creates clearly named SIMULATED records and private development users. --faults briefly stops services.
"""
import argparse
import copy
from decimal import Decimal
import json
import time
import uuid
from jsonschema import Draft202012Validator,FormatChecker
from platform_support import ROOT,configuration,request,compose,sql,broker,internal_requests
from dev_identity import users,login,assign_estate
parser=argparse.ArgumentParser();parser.add_argument('--faults',action='store_true');args=parser.parse_args()
config=configuration();gateway='http://localhost:8080';checks=[];people=users(config)
def passed(name):checks.append(name);print('PASS: '+name,flush=True)
def eventually(operation,timeout=75):
    deadline=time.monotonic()+timeout
    while True:
        try:
            result=operation()
            if result:return result
        except (AssertionError,OSError):pass
        if time.monotonic()>deadline:raise AssertionError('Condition did not become true before deadline')
        time.sleep(.25)
def api(path,method='GET',body=None,token=None,expected=200,headers=None):
    return request(gateway+'/api/v1'+path,method,body,token,headers,expected)
def validate(schema,body):
    # JSON numbers are decimal; avoid binary-float multipleOf false negatives (e.g. 1.2 / 0.0001).
    schema=json.loads(json.dumps(schema),parse_float=Decimal)
    body=json.loads(json.dumps(body),parse_float=Decimal)
    Draft202012Validator(schema,format_checker=FormatChecker()).validate(body)
def contract(service,name,body):
    document=json.loads((ROOT/'tests/contracts'/f'{service}.openapi.json').read_text());document['$ref']='#/components/schemas/'+name
    validate(document,body)
def publish(event):
    result=broker(config,'exchanges/%2F/agrosphere.domain/publish','POST',{'properties':{'delivery_mode':2,'content_type':'application/json','correlation_id':event['correlationId']},
        'routing_key':'agrosphere.'+event['eventType']+'.v2','payload':json.dumps(event),'payload_encoding':'string'})
    assert result['routed']
def polygon(w,s,e,n):return {'type':'Polygon','coordinates':[[[w,s],[e,s],[e,n],[w,n],[w,s]]]}

request(gateway+'/actuator/health/readiness');api('/estates',expected=401);api('/estates',token='invalid',expected=401)
manager=login(config,people['manager']);admin=login(config,people['admin'])
suffix=uuid.uuid4().hex[:12].upper();correlation=str(uuid.uuid4());trace=uuid.uuid4().hex
headers={'X-Correlation-ID':correlation,'traceparent':f'00-{trace}-0123456789abcdef-01'}
# Preserve the existing contract: managers cannot bootstrap global Estate identities.
estate_body={'estateCode':'SMOKE_'+suffix,'name':'Simulated rubber plantation','countryCode':'LK','timezone':'Asia/Colombo','totalAreaHectares':100,'status':'ACTIVE'}
api('/estates','POST',estate_body,manager,403)
estate,response=api('/estates','POST',estate_body,admin,201,headers);estate_id=estate['id'];contract('estate','Estate',estate)
assert response['X-Correlation-ID']==correlation
assert sql(config,'estate',f"SELECT count(*) FROM estate WHERE id='{estate_id}'")=='1'
assign_estate(config,people['manager'],estate_id);assign_estate(config,people['viewer'],estate_id)
manager=login(config,people['manager']);viewer=login(config,people['viewer']);outsider=login(config,people['outsider'])
passed('Real development users authenticate with Authorization Code + PKCE; admin-only estate creation and assigned manager scope')

estate_body.update(name='Updated simulated rubber plantation',version=estate['version'])
estate,_=api('/estates/'+estate_id,'PUT',estate_body,manager,headers=headers);contract('estate','Estate',estate)
divisions=[]
for i in range(2):
    division,_=api('/estates/'+estate_id+'/divisions','POST',{'estateId':estate_id,'divisionCode':f'D{i}_'+suffix,'name':f'Synthetic division {i+1}','status':'ACTIVE'},manager,201)
    contract('estate','Division',division);divisions.append(division)
clone,_=api('/rubber-clones','POST',{'cloneCode':'CL_'+suffix,'description':'SIMULATED integration clone','status':'ACTIVE'},admin,201);contract('estate','RubberClone',clone)
blocks=[];writes=[]
for i in range(10):
    body={'estateId':estate_id,'divisionId':divisions[i//5]['id'],'blockCode':f'B{i:02d}_'+suffix,'name':f'Synthetic rubber block {i+1}',
        'cropType':'RUBBER','rubberCloneCode':clone['cloneCode'],'plantingDate':'2020-01-01','plantedAreaHectares':1.2,
        'plantedTreeCount':100,'tappableTreeCount':50,'status':'ACTIVE'}
    block,_=api('/divisions/'+body['divisionId']+'/blocks','POST',body,manager,201,headers);contract('estate','PlantationBlock',block)
    blocks.append(block);writes.append(body)
invalid={**writes[0],'blockCode':'INVALID_'+suffix,'tappableTreeCount':101}
api('/divisions/'+divisions[0]['id']+'/blocks','POST',invalid,manager,400)
api('/divisions/'+divisions[0]['id']+'/blocks','POST',writes[0],manager,409)
updated={**writes[0],'name':'Updated synthetic rubber block','version':blocks[0]['version']}
blocks[0],_=api('/blocks/'+blocks[0]['id'],'PUT',updated,manager,headers=headers)
listing,_=api('/estates/'+estate_id+'/blocks?size=100',token=manager);assert len(listing['content'])==10
assert sql(config,'estate',f"SELECT count(*) FROM division WHERE estate_id='{estate_id}'")=='2'
assert sql(config,'estate',f"SELECT count(*) FROM plantation_block WHERE estate_id='{estate_id}'")=='10'
passed('Two divisions, ten unique rubber blocks with clone/planting/tree metadata; create/read/update, persisted relationships and domain rejection')

eventually(lambda:sql(config,'spatial',f"SELECT count(*) FROM reference_entity WHERE estate_id='{estate_id}' AND entity_type='BLOCK'")=='10')
eventually(lambda:sql(config,'estate',f"SELECT count(*) FROM outbox_event WHERE payload->>'estateId'='{estate_id}' AND delivery_status<>'PUBLISHED'")=='0')
assert sql(config,'spatial',f"SELECT count(*) FROM reference_entity WHERE estate_id='{estate_id}' AND entity_type='DIVISION'")=='2'
actual=json.loads(sql(config,'estate',f"SELECT json_agg(payload)::text FROM outbox_event WHERE payload->>'estateId'='{estate_id}'"))
assert {'EstateCreated','EstateUpdated','PlantationBlockCreated','PlantationBlockUpdated'}<={e['eventType'] for e in actual}
for event in actual:
    schema=json.loads((ROOT/'tests/contracts/events/v2'/f"{event['eventType']}.schema.json").read_text())
    validate(schema,event)
passed('All four Estate lifecycle event types are atomic, confirmed, contract-valid and projected with canonical IDs using bounded polling')

features=[]
def add_feature(reference,kind,code,geometry):
    features.append({'type':'Feature','properties':{'estateId':estate_id,'referenceEntityId':reference,'referenceEntityType':kind,
        'featureCode':code,'status':'ACTIVE','dataProvenance':'SIMULATED'},'geometry':geometry})
add_feature(estate_id,'ESTATE','ESTATE_'+suffix,polygon(80,7,80.01,7.005))
for i,division in enumerate(divisions):add_feature(division['id'],'DIVISION',f'DIV{i}_'+suffix,polygon(80,7+i*.0025,80.01,7+(i+1)*.0025))
for i,block in enumerate(blocks):
    w=round(80.0005+(i%5)*.0018,7);s=round(7.0005+(i//5)*.0025,7)
    add_feature(block['id'],'BLOCK',f'G{i:02d}_'+suffix,polygon(w,s,round(w+.001,7),round(s+.001,7)))
collection={'type':'FeatureCollection','features':features}
(ROOT/'target').mkdir(exist_ok=True);(ROOT/'target/rubber-plantation.geojson').write_text(json.dumps(collection,indent=2)+'\n')
job,_=api('/spatial/imports/geojson','POST',{'estateId':estate_id,'sourceFilename':'rubber-plantation.geojson','geojson':collection},manager,202,headers)
contract('spatial','ImportJob',job);assert job['status']=='COMPLETED' and job['importedCount']==13,job.get('validationReport')
assert sql(config,'spatial',f"SELECT count(*) FROM spatial_feature WHERE estate_id='{estate_id}' AND ST_SRID(geometry)=4326 AND ST_IsValid(geometry)")=='13'
assert sql(config,'spatial',f"SELECT count(*) FROM spatial_feature a JOIN spatial_feature b ON a.id<b.id AND a.estate_id=b.estate_id WHERE a.estate_id='{estate_id}' AND a.reference_entity_type='BLOCK' AND b.reference_entity_type='BLOCK' AND ST_Area(ST_CollectionExtract(ST_Intersection(a.geometry,b.geometry),3)::geography)>0")=='0'
assert sql(config,'spatial',f"SELECT bool_and(abs(calculated_area_hectares-ST_Area(geometry::geography)/10000)<0.000001) FROM spatial_feature WHERE estate_id='{estate_id}'")=='t'
passed('Canonical-UUID GeoJSON import: estate + two divisions + ten nonoverlapping WGS84 polygons, validity/SRID and spheroidal hectares')

boundaries,_=api('/spatial/estates/'+estate_id+'/boundaries?size=100',token=manager)
assert len([f for f in boundaries['content'] if f['referenceEntityType']=='ESTATE'])==1
geometries=[]
for block in blocks:
    geometry,_=api('/spatial/blocks/'+block['id']+'/geometry',token=manager);contract('spatial','Feature',geometry)
    assert geometry['centroid']['type']=='Point' and len(geometry['boundingBox'])==4 and 1<geometry['calculatedAreaHectares']<1.5
    geometries.append(geometry)
query,_=api('/spatial/query/point','POST',{'estateId':estate_id,'geometry':{'type':'Point','coordinates':[80.001,7.001]},'bbox':[80,7,80.01,7.005],'limit':100},manager)
contract('spatial','QueryResult',query);assert [f['referenceEntityId'] for f in query['content'] if f['referenceEntityType']=='BLOCK']==[blocks[0]['id']]
bounds,_=api('/spatial/estates/'+estate_id+'/bbox',token=manager);contract('spatial','Bounds',bounds);assert bounds['srid']==4326
layer,_=api('/spatial/layers','POST',{'estateId':estate_id,'layerCode':'LAY_'+suffix,'name':'SIMULATED rubber block boundaries','layerType':'BOUNDARY','format':'GEOJSON','enabled':True},manager,201)
contract('spatial','Layer',layer);layers,_=api('/spatial/estates/'+estate_id+'/layers',token=manager);assert layers['content'][0]['id']==layer['id']
exported,_=api('/spatial/estates/'+estate_id+'/export/geojson',token=manager);contract('spatial','GeoCollection',exported);assert len(exported['features'])==13
passed('Gateway spatial queries retrieve estate boundary, all block geometry, point membership, bbox/centroids, GIS layers and GeoJSON export')

api('/estates/'+estate_id,token=outsider,expected=403);api('/spatial/estates/'+estate_id+'/features',token=outsider,expected=403)
api('/blocks/'+blocks[0]['id'],'PUT',updated,outsider,403)
root_feature=next(f for f in boundaries['content'] if f['referenceEntityType']=='ESTATE')
write_boundary={k:root_feature[k] for k in ['estateId','referenceEntityId','referenceEntityType','featureCode','geometry','srid','geometryVersion','status','sourceType','sourceReference','dataProvenance']}
api('/spatial/features/'+root_feature['id'],'PUT',write_boundary,viewer,403)
api('/spatial/imports/geojson','POST',{'estateId':estate_id,'sourceFilename':'denied.geojson','geojson':collection},outsider,403)
for source,target in [('estate','spatial'),('spatial','estate')]:assert sql(config,source,'SELECT 1',database='agrosphere_'+target,check=False).returncode!=0
passed('VIEWER cannot modify boundary; unassigned users cannot read/write/import; database roles cannot connect across ownership boundaries')
internal=internal_requests(config,[
    {'url':'http://estate:8081/api/v1/estates/'+estate_id},
    {'url':'http://spatial:8082/api/v1/spatial/blocks/'+blocks[0]['id']+'/geometry'},
    {'url':'http://estate:8081/api/v1/estates/'+estate_id,'token':manager},
    {'url':'http://spatial:8082/api/v1/spatial/blocks/'+blocks[0]['id']+'/geometry','token':manager},
    {'url':'http://estate:8081/api/v1/estates/'+estate_id,'token':outsider},
    {'url':'http://spatial:8082/api/v1/spatial/blocks/'+blocks[0]['id']+'/geometry','token':outsider},
    {'url':'http://estate:8081/api/v1/estates','method':'POST','token':manager,'body':{'large':'x'*2097153}},
    {'url':'http://spatial:8082/api/v1/spatial/imports/geojson','method':'POST','token':manager,'body':{'large':'x'*2097153}},
    {'url':'http://estate:8081/v3/api-docs','token':manager},
    {'url':'http://spatial:8082/v3/api-docs','token':manager}])
assert [r['status'] for r in internal]==[401,401,200,200,403,403,413,413,200,200]
for name,value in zip(['estate','spatial'],internal[-2:]):
    actual_api=value['body'];pinned=json.loads((ROOT/'tests/contracts'/f'{name}.openapi.json').read_text())
    assert set(actual_api['paths'])==set(pinned['paths'])
    (ROOT/'target'/f'{name}.openapi.json').write_text(json.dumps(actual_api,indent=2)+'\n')
passed('Direct backend JWT/estate authorization without gateway, 2 MiB request limits and authenticated runtime OpenAPI contracts')

# Replay newer snapshot then older snapshot under a new delivery identity; stale snapshots must not win.
stale=next(e for e in actual if e['eventType']=='PlantationBlockCreated' and e['blockId']==blocks[0]['id'])
latest=next(e for e in actual if e['eventType']=='PlantationBlockUpdated')
for envelope in [latest,latest,{**stale,'eventId':str(uuid.uuid4())}]:publish(envelope)
eventually(lambda:sql(config,'spatial',f"SELECT count(*) FROM processed_event WHERE event_id='{latest['eventId']}'")=='1')
eventually(lambda:sql(config,'spatial',f"SELECT count(*) FROM processed_event WHERE event_id NOT IN ('{latest['eventId']}') AND event_id='{envelope['eventId']}'")=='1')
assert sql(config,'spatial',f"SELECT revision FROM reference_entity WHERE id='{blocks[0]['id']}' AND entity_type='BLOCK'")==str(latest['payload']['version'])
# Parent-late strategy: retain child snapshot durably; later parent snapshot reconciles without dropping/replaying child.
late_estate=str(uuid.uuid4());late_block=str(uuid.uuid4());late_division=str(uuid.uuid4())
child=copy.deepcopy(stale);child.update(eventId=str(uuid.uuid4()),estateId=late_estate,entityId=late_block,blockId=late_block)
child['payload'].update(id=late_block,estateId=late_estate,divisionId=late_division)
publish(child);eventually(lambda:sql(config,'spatial',f"SELECT count(*) FROM reference_entity WHERE id='{late_block}' AND entity_type='BLOCK'")=='1')
assert sql(config,'spatial',f"SELECT count(*) FROM reference_entity WHERE id='{late_estate}' AND entity_type='ESTATE'")=='0'
parent=copy.deepcopy(next(e for e in actual if e['eventType']=='EstateCreated'));parent.update(eventId=str(uuid.uuid4()),estateId=late_estate,entityId=late_estate);parent['payload'].update(id=late_estate)
publish(parent);eventually(lambda:sql(config,'spatial',f"SELECT count(*) FROM reference_entity WHERE estate_id='{late_estate}'")=='3')
passed('RabbitMQ duplicates and out-of-order revisions are idempotent; parent-late child snapshots are retained and reconcile when the estate arrives')

# The persisted initiating trace must include AMQP producer and consumer spans after outbox relay.
def traced():
    data,_=request('http://localhost:16686/api/traces/'+trace)
    if not data.get('data'):return False
    value=data['data'][0];services={p['serviceName'] for p in value['processes'].values()}
    names=[s['operationName'] for s in value['spans']]
    return {'agrosphere-api-gateway','agrosphere-estate-service','agrosphere-spatial-service'}.issubset(services) and any('publish' in n or 'send' in n for n in names) and any('process' in n or 'receive' in n for n in names)
eventually(traced,90)
assert sql(config,'estate',f"SELECT bool_and(trace_parent IS NOT NULL) FROM outbox_event WHERE correlation_id='{correlation}'")=='t'
passed('Durable W3C HTTP -> transactional outbox -> RabbitMQ publish -> Spatial consume spans are visible together in Jaeger')

if args.faults:
    compose(config,'stop','estate')
    try:
        api('/estates',token=manager,expected=503)
        independent,_=api('/spatial/blocks/'+blocks[0]['id']+'/geometry',token=manager);assert independent['id']==geometries[0]['id']
        api('/spatial/estates/'+estate_id+'/layers',token=manager)
    finally:compose(config,'up','-d','--wait','--wait-timeout','120','estate')
    passed('Spatial serves existing geometry and layers while Estate is stopped; safe gateway 503 and independent restart recovery')
    compose(config,'stop','rabbitmq')
    try:
        recovery,_=api('/estates','POST',{'estateCode':'REC_'+suffix,'name':'SIMULATED broker recovery','countryCode':'LK','timezone':'Asia/Colombo','status':'ACTIVE'},admin,201)
        assert sql(config,'estate',f"SELECT count(*) FROM outbox_event WHERE aggregate_id='{recovery['id']}' AND delivery_status='PENDING'")=='1'
    finally:compose(config,'up','-d','--wait','--wait-timeout','120','rabbitmq')
    eventually(lambda:sql(config,'spatial',f"SELECT count(*) FROM reference_entity WHERE id='{recovery['id']}' AND entity_type='ESTATE'")=='1')
    passed('Broker outage preserves pending atomic outbox; messaging resumes without duplicate projection effects')
(ROOT/'target/platform-smoke.json').write_text(json.dumps({'checks':checks,'estateId':estate_id,'divisionIds':[d['id'] for d in divisions],
    'blockIds':[b['id'] for b in blocks],'importId':job['id'],'traceId':trace,'provenance':'SIMULATED'},indent=2)+'\n')
print(f'PASS: {len(checks)} full platform acceptance groups; development data retained; no volumes deleted.')
