"""Compare actual Web entity and Unreal mesh ECEF vertices to Spatial DTOs."""
import argparse
import hashlib
import json
import math

from poc_close_native import context, command


def ecef(lonlat):
    lon, lat = map(math.radians, lonlat[:2])
    a, e2 = 6378137.0, 6.6943799901413165e-3
    n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    return [n * math.cos(lat) * math.cos(lon), n * math.cos(lat) * math.sin(lon),
            n * (1 - e2) * math.sin(lat)]


def verify(manifest, profile):
    path, owner, private = context(manifest)
    scene = 'maximum' if profile.startswith('maximum') else 'story'
    source_file = private / ('maximum-geometry.json' if scene == 'maximum' else 'canonical-geometry.json')
    sources = json.loads(source_file.read_text())
    by_id = {s['id']: s for s in sources}
    web = json.loads((path.parent / ('web-' + scene + '-geometry.json')).read_text())
    assert web['runId'] == owner['runId']
    command(manifest, 'export')
    native = json.loads((private / 'native-geometry.json').read_text(encoding='utf-8-sig'))
    errors, values, matches = [], [], {'web': set(), 'native': set()}
    deltas = []

    def source_points(identity):
        source = by_id[identity]
        assert source['geometry']['type'] == 'Polygon'
        return [(ring_index, vertex_index, ll, ecef(ll))
                for ring_index, ring in enumerate(source['geometry']['coordinates'])
                for vertex_index, ll in enumerate(ring[:-1])]

    def check(kind, identity, block, version, actual, declared=None, render=None, loaded_ring=None):
        source = by_id.get(identity)
        if not source or block != source['referenceEntityId'] or version != source['geometryVersion']:
            errors.append(kind + ': loaded identity/version mismatch')
            return
        candidates = source_points(identity)
        # Match the actual loaded position, not the UUID or source formula alone.
        ring, vertex, ll, expected = min(candidates, key=lambda p: sum((p[3][i] - actual[i]) ** 2 for i in range(3)))
        if declared is not None and any(abs(declared[i] - ll[i]) > 1e-10 for i in range(2)):
            errors.append(kind + ': mesh triangulation annotation disagrees with authoritative vertex')
        if loaded_ring is not None and loaded_ring != ring:
            errors.append(kind + ': hole/ring ordering mismatch')
        delta = [actual[i] - expected[i] for i in range(3)]
        distance = math.sqrt(sum(v * v for v in delta))
        render_delta = None if render is None else [render[i] - expected[i] for i in range(3)]
        if any(abs(v) > .01 for v in delta) or render_delta is not None and any(abs(v) > .01 for v in render_delta):
            errors.append(kind + ': >0.01m coordinate tolerance')
        values.append(distance)
        matches[kind].add((identity, ring, vertex))
        deltas.append({'renderer': kind, 'featureId': identity, 'blockId': block, 'geometryVersion': version,
            'sourceRing': ring, 'sourceVertex': vertex, 'deltaEcefMetres': delta, 'distanceMetres': distance,
            'renderPrecisionDeltaMetres': render_delta})

    for row in web['rows']:
        for ring_index, ring in enumerate(row['rings']):
            for actual in ring:
                check('web', row['featureId'], row['blockId'], row['geometryVersion'], actual, loaded_ring=ring_index)
    for row in native['vertices']:
        check('native', row['featureId'], row['blockId'], row['geometryVersion'], row['actualEcefMetres'],
              row['canonicalLonLatHeight'], row['renderPrecisionEcefMetres'])
    expected = {(identity, r, v) for identity in by_id for r, v, _, _ in source_points(identity)}
    for kind, seen in matches.items():
        if seen != expected:
            errors.append(kind + ': missing/unexpected authoritative vertex identities')
    # Compare the actual recorded georeference to the first actual source vertex.
    origin = native['worldOriginLonLatHeight']
    base = by_id[native['vertices'][0]['featureId']]['geometry']['coordinates'][0][0] if native['vertices'] else sources[0]['geometry']['coordinates'][0][0]
    chord = math.dist(ecef(origin), ecef(base))
    if profile.endswith('rebased') and abs(chord - 100000) > .01:
        errors.append('Expected100km origin shift unavailable')
    report = {'runId': owner['runId'], 'profile': profile, 'tolerancePerAxisMetres': .01,
        'result': 'FAIL' if errors else 'PASS', 'errors': sorted(set(errors)), 'verticesCompared': len(deltas),
        'authoritativeUniqueVertices': len(expected), 'maxDistanceMetres': max(values) if values else None,
        'rmsDistanceMetres': math.sqrt(sum(v*v for v in values) / len(values)) if values else None,
        'originLonLatHeight': origin, 'originEcefChordFromFirstVertexMetres': chord,
        'sourceDtoSha256': hashlib.sha256(source_file.read_bytes()).hexdigest(),
        'webExportSha256': hashlib.sha256((path.parent / ('web-' + scene + '-geometry.json')).read_bytes()).hexdigest(),
        'nativeExportSha256': hashlib.sha256((private / 'native-geometry.json').read_bytes()).hexdigest(),
        'limits': 'Actual CPU mesh/world positions and float render-buffer precision; no GPU readback, imagery/survey or physical VR registration claim.',
        'perVertexDeltas': deltas}
    (path.parent / ('coordinates-' + profile + '.json')).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'perVertexDeltas'}))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest')
    parser.add_argument('profile', choices=['story', 'story-rebased', 'maximum', 'maximum-rebased'])
    arguments = parser.parse_args()
    result = verify(arguments.manifest, arguments.profile)
    raise SystemExit(0 if result['result'] == 'PASS' else 1)
