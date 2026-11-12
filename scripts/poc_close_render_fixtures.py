"""API-created generated renderer cases; no historical/source DB mutation."""
import hashlib
import json
import math
import time
import urllib.error
import urllib.request

from dev_identity import login


def prepare(owner):
    clients = json.loads((owner.private / 'generated-clients.json').read_text())
    token = login(owner.config, clients['admin'])

    def call(path, method='GET', body=None, status=200):
        nonlocal token
        owner.check_lifetime()
        req = urllib.request.Request(owner.record['gateway'] + '/api/v1' + path,
            data=None if body is None else json.dumps(body).encode(), method=method,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        try:
            response = urllib.request.urlopen(req, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read(2 * 1024 * 1024 + 1)
            assert response.status == status, ('renderer fixture API', method, path, response.status)
            return json.loads(raw) if raw else None

    def estate(code, name):
        return call('/estates', 'POST', {'estateCode': code, 'name': 'SIMULATED ' + name,
            'countryCode': 'LK', 'timezone': 'Asia/Colombo', 'status': 'ACTIVE'}, 201)['id']

    def division(e):
        return call('/estates/' + e + '/divisions', 'POST', {'estateId': e, 'divisionCode': 'RENDER',
            'name': 'SIMULATED renderer verification', 'status': 'ACTIVE'}, 201)['id']

    def block(e, d, number):
        return call('/divisions/' + d + '/blocks', 'POST', {'estateId': e, 'divisionId': d,
            'blockCode': f'R{number:03d}', 'name': f'SIMULATED render block {number:03d}',
            'cropType': 'RUBBER', 'plantedAreaHectares': 1, 'plantedTreeCount': 100,
            'tappableTreeCount': 80, 'status': 'ACTIVE'}, 201)['id']

    empty = estate('RENDEREMPTY', 'empty renderer estate')
    no_geometry = estate('RENDERNOGEO', 'metadata without geometry')
    no_geometry_block = block(no_geometry, division(no_geometry), 1)
    maximum = estate('RENDERMAX', 'maximum northern renderer estate')
    div = division(maximum)
    blocks = [block(maximum, div, i + 1) for i in range(100)]
    # Reference propagation remains the normal Estate event -> Spatial consumer.
    deadline = time.monotonic() + 90
    while True:
        count = owner.compose('exec', '-T', '-e', 'PGPASSWORD', 'postgres', 'psql', '-h', '127.0.0.1',
            '-U', 'agrosphere_spatial', '-d', 'agrosphere_spatial', '-Atc',
            "SELECT count(*) FROM reference_entity WHERE estate_id='" + maximum + "' AND entity_type='BLOCK'",
            environment={'PGPASSWORD': owner.config['SPATIAL_DB_PASSWORD']}).stdout.strip()
        if int(count) == 100:
            break
        assert time.monotonic() < deadline, 'Maximum renderer reference propagation timeout'
        time.sleep(.5)
    features = []
    for index, bid in enumerate(blocks):
        x, y = 80 + (index % 10) * .0014, 7 + (index // 10) * .0014
        def circle(points, radius, clockwise=False):
            values = [[x + radius * math.cos(((-1 if clockwise else 1) * 2 * math.pi * i) / (points - 1)),
                       y + radius * math.sin(((-1 if clockwise else 1) * 2 * math.pi * i) / (points - 1))]
                      for i in range(points - 1)]
            return values + [values[0]]
        # Exactly 100 closed-ring vertices per feature; the first has a hole.
        rings = [circle(95, .0005), circle(5, .0001, True)] if index == 0 else [circle(100, .0005)]
        payload = {'estateId': maximum, 'referenceEntityId': bid, 'referenceEntityType': 'BLOCK',
            'featureCode': f'R{index+1:03d}', 'geometry': {'type': 'Polygon', 'coordinates': rings},
            'srid': 4326, 'status': 'ACTIVE', 'sourceType': 'GENERATED',
            'sourceReference': 'POC-CLOSE renderer ' + owner.run, 'dataProvenance': 'SIMULATED'}
        features.append(call('/spatial/features', 'POST', payload, 201))
    encoded = json.dumps(features).encode()
    assert sum(len(r) for f in features for r in f['geometry']['coordinates']) == 10000
    assert len(encoded) < 10 * 1024 * 1024
    (owner.private / 'maximum-geometry.json').write_bytes(encoded)
    result = {'emptyEstateId': empty, 'noGeometryEstateId': no_geometry,
        'noGeometryBlockId': no_geometry_block, 'maximumEstateId': maximum, 'maximumBlockIds': blocks,
        'features': 100, 'closedRingVertices': 10000, 'dtoBytes': len(encoded),
        'dtoSha256': hashlib.sha256(encoded).hexdigest(),
        'purpose': 'Additional generated renderer-only estates; canonical E1/B1 and E2 denial unchanged. Admin reads these; E1-only viewer scope is preserved.'}
    owner.record['rendererFixtures'] = result
    owner.inventory_copies()
    owner.phase('API-created empty/no-geometry and maximum northern renderer fixtures', **result)
    return result
