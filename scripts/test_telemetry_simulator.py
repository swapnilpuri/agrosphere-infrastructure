import copy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
from telemetry_simulator import BROKER_CONFIG, GeneratedPublisher, digest, instant, sequence

RUN = '00000000-0000-4000-8000-000000000001'
DEVICE = '00000000-0000-4000-8000-000000000002'
ESTATE = '00000000-0000-4000-8000-000000000003'
BLOCK = '00000000-0000-4000-8000-000000000004'


class SimulatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='agrosphere-tlm02-unit-')
        self.root = Path(self.temp.name)
        self.topic = f'agrosphere/v1/estates/{ESTATE}/devices/{DEVICE}/observations'
        acl = f'user fixture-publisher\ntopic write {self.topic}\nuser fixture-subscriber\ntopic read {self.topic}\n'
        (self.root / '.generated-telemetry-owner').write_text(RUN)
        (self.root / 'broker.conf').write_bytes(BROKER_CONFIG.encode())
        (self.root / 'acl').write_bytes(acl.encode())
        self.channel = {'runId': RUN, 'host': '127.0.0.1', 'port': 1883,
                        'subscriberUser': 'fixture-subscriber', 'aclFile': 'acl', 'aclSha256': digest(acl.encode()),
                        'brokerConfigFile': 'broker.conf', 'brokerConfigSha256': digest(BROKER_CONFIG.encode()),
                        'windowStart': '2026-01-01T11:00:00Z', 'windowEnd': '2026-01-01T13:00:00Z',
                        'devices': [{'deviceId': DEVICE, 'estateId': ESTATE, 'blockId': BLOCK, 'publisherPrincipal': 'fixture-publisher'}]}
        self.plan = {'runId': RUN, 'dataProvenance': 'SIMULATED', 'channelManifest': 'manifest.json',
                     'brokerContainerId': 'a' * 64, 'publisherConfigSha256': 'b' * 64,
                     'start': '2026-01-01T11:57:30Z', 'referenceAt': '2026-01-01T12:00:00Z',
                     'sampleCount': 6, 'cadenceSeconds': 30, 'seed': 'FIXED_V1'}
        self.calls = []
        self.write()

    def tearDown(self):
        self.temp.cleanup()

    def write(self):
        raw = json.dumps(self.channel).encode()
        (self.root / 'manifest.json').write_bytes(raw)
        self.plan['channelSha256'] = digest(raw)
        raw = json.dumps(self.plan).encode()
        (self.root / 'publisher-plan.json').write_bytes(raw)
        return digest(raw)

    def execute(self, command, body=None):
        self.calls.append((command, body))
        if command[1] == 'inspect':
            return 'true ' + RUN
        if command[3] == 'sha256sum':
            return f"{self.channel['brokerConfigSha256']}  /tmp/config\n{self.channel['aclSha256']}  /tmp/acl\n{'b' * 64}  /tmp/mosquitto_pub\n"
        return ''

    def publisher(self):
        return GeneratedPublisher(self.root / 'publisher-plan.json', self.write(), self.execute)

    def test_deterministic_restart_same_bodies_ids_units_and_clocks(self):
        first = sequence(self.channel, self.plan)
        self.assertEqual(first, sequence(copy.deepcopy(self.channel), copy.deepcopy(self.plan)))
        self.assertEqual(18, len(first))
        self.assertEqual(18, len({x['observationId'] for x in first}))
        self.assertEqual({'AIR_TEMPERATURE', 'SOIL_MOISTURE', 'INTERVAL_RAINFALL'}, {x['kind'] for x in first})
        self.assertEqual({'SIMULATED'}, {x['dataProvenance'] for x in first})
        for rain in [x for x in first if x['kind'] == 'INTERVAL_RAINFALL']:
            self.assertEqual(timedelta(seconds=30), instant(rain['intervalEnd']) - instant(rain['intervalStart']))

    def test_counts_are_finite_and_not_boolean_or_fractional(self):
        default_plan = dict(self.plan)
        del default_plan['sampleCount']
        self.assertEqual(18, len(sequence(self.channel, default_plan)))
        for value in [0, 121, True, 1.5]:
            with self.assertRaises(ValueError):
                sequence(self.channel, dict(self.plan, sampleCount=value))
        self.assertEqual(360, len(sequence(self.channel, dict(self.plan, sampleCount=120, start='2026-01-01T11:00:00Z'))))

    def test_window_future_real_and_unbounded_seed_rejected(self):
        for change in [{'start': '2026-01-01T10:59:59Z'}, {'start': '2026-01-01T12:00:00Z'},
                       {'cadenceSeconds': 0}, {'seed': 'x' * 65}, {'dataProvenance': 'REAL'}]:
            with self.assertRaises(ValueError):
                sequence(self.channel, dict(self.plan, **change))

    def test_transport_report_not_domain_acceptance_and_no_cli_password(self):
        report = self.publisher().publish()
        self.assertEqual(18, report['transportPublished'])
        publications = [(c, b) for c, b in self.calls if 'mosquitto_pub' in c]
        self.assertEqual(18, len(publications))
        for command, body in publications:
            self.assertNotIn('-P', command)
            self.assertNotIn('fixture-publisher', command)
            self.assertEqual(self.topic, command[command.index('-t') + 1])
            self.assertEqual('SIMULATED', json.loads(body)['dataProvenance'])

    def test_unowned_plan_bad_hash_and_changed_plan_fail_before_publish(self):
        with self.assertRaises(ValueError):
            GeneratedPublisher(self.root / 'publisher-plan.json', '0' * 64, self.execute)
        self.assertEqual([], self.calls)
        publisher = self.publisher()
        (self.root / 'publisher-plan.json').write_text('{}')
        with self.assertRaises(ValueError):
            publisher.publish()
        self.assertFalse(any('mosquitto_pub' in c for c, _ in self.calls))

    def test_changed_acl_and_external_manifest_path_refused(self):
        (self.root / 'acl').write_text('topic write #\n')
        with self.assertRaises(ValueError):
            self.publisher()
        self.assertFalse(any('mosquitto_pub' in c for c, _ in self.calls))
        self.plan['channelManifest'] = '../outside.json'
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.publisher()

    def test_wrong_container_owner_and_runtime_hash_refused(self):
        def wrong_owner(command, body=None):
            return 'true wrong-owner'
        with self.assertRaises(ValueError):
            GeneratedPublisher(self.root / 'publisher-plan.json', self.write(), wrong_owner)
        def wrong_hash(command, body=None):
            return 'true ' + RUN if command[1] == 'inspect' else '0 /tmp/config\n'
        with self.assertRaises(ValueError):
            GeneratedPublisher(self.root / 'publisher-plan.json', self.write(), wrong_hash)


if __name__ == '__main__':
    unittest.main()
