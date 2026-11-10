"""Finite deterministic SIMULATED publisher, restricted to verified owned fixtures.

Uses the existing broker's maintained mosquitto_pub client and protected generated
configuration. It never discovers private .env files or accepts an arbitrary broker.
"""
import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid

MAX_FILE = 65536
BROKER_CONFIG = ('listener 1883\nallow_anonymous false\npassword_file /tmp/passwords\nacl_file /tmp/acl\n'
                 'persistence true\npersistence_location /mosquitto/data/\nlog_type error\n'
                 'max_inflight_messages 10\nmax_queued_messages 100\nmessage_size_limit 4096\n'
                 'max_packet_size 8192\nuse_username_as_clientid true\n')


def canonical_id(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('Invalid generated identity')
    return value


def instant(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z', value):
        raise ValueError('Invalid UTC fixture clock')
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def wire_time(value):
    return value.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def sequence(channel, plan):
    """Pure generator: no wall-clock reads, network, randomness or persistence."""
    run = canonical_id(channel['runId'])
    if plan['runId'] != run or len(channel['devices']) != 1 or plan['dataProvenance'] != 'SIMULATED':
        raise ValueError('One matching generated device required')
    device = channel['devices'][0]
    for key in ['deviceId', 'estateId', 'blockId']:
        canonical_id(device[key])
    count = plan.get('sampleCount', 6)
    if type(count) is not int or not 1 <= count <= 120 or plan['cadenceSeconds'] != 30:
        raise ValueError('Bounded scenario count/cadence required')
    if not isinstance(plan['seed'], str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', plan['seed']):
        raise ValueError('Bounded scenario seed required')
    start, reference = instant(plan['start']), instant(plan['referenceAt'])
    end = start + timedelta(seconds=(count - 1) * 30)
    if start < instant(channel['windowStart']) or end > instant(channel['windowEnd']) or end > reference:
        raise ValueError('Scenario outside declared admission clocks')
    result = []
    for index in range(count):
        observed = start + timedelta(seconds=index * 30)
        measurements = [('AIR_TEMPERATURE', 'CELSIUS', Decimal('27.5') + Decimal(index % 6) / 4),
                        ('SOIL_MOISTURE', 'PERCENT', Decimal(45) + Decimal(index % 6) / 8),
                        ('INTERVAL_RAINFALL', 'MILLIMETRE', Decimal(index % 4) / 8)]
        for kind, unit, value in measurements:
            identity = uuid.uuid5(uuid.UUID(run), f"TLM02:{plan['seed']}:{wire_time(start)}:{device['deviceId']}:{kind}:{index}")
            body = {'schemaVersion': 1, 'observationId': str(identity), 'deviceId': device['deviceId'],
                    'estateId': device['estateId'], 'blockId': device['blockId'], 'kind': kind, 'unit': unit,
                    'value': format(value, 'f'), 'observedAt': wire_time(observed), 'dataProvenance': 'SIMULATED'}
            if kind == 'INTERVAL_RAINFALL':
                body.update(intervalStart=wire_time(observed - timedelta(seconds=30)), intervalEnd=wire_time(observed))
            result.append(body)
    return result


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class GeneratedPublisher:
    def __init__(self, path, expected_sha256, execute=None):
        self.path = Path(path).resolve(strict=True)
        self.root = self.path.parent
        self.expected = expected_sha256
        self.execute = execute or self._execute
        marker = canonical_id(self._read(self._owned('.generated-telemetry-owner')).decode().strip())
        raw = self._read(self.path)
        if digest(raw) != self.expected:
            raise ValueError('Unverified fixture plan')
        self.plan = json.loads(raw)
        if self.plan['runId'] != marker:
            raise ValueError('Owner marker mismatch')
        self.channel_path = self._owned(self.plan['channelManifest'])
        self.channel = json.loads(self._read(self.channel_path))
        self.container = self.plan['brokerContainerId']
        if not re.fullmatch(r'[0-9a-f]{64}', self.container):
            raise ValueError('Exact owned container identity required')
        self.messages = sequence(self.channel, self.plan)
        self.verify()

    @staticmethod
    def _execute(command, body=None):
        result = subprocess.run(command, input=body, capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise RuntimeError('Generated publisher operation failed')
        return result.stdout

    def _read(self, path):
        if not path.is_file() or path.stat().st_size > MAX_FILE:
            raise ValueError('Invalid owned fixture file')
        return path.read_bytes()

    def _owned(self, name):
        if not isinstance(name, str) or Path(name).is_absolute():
            raise ValueError('Relative owned fixture file required')
        path = (self.root / name).resolve(strict=True)
        if not path.is_relative_to(self.root):
            raise ValueError('Fixture path escaped owner root')
        return path

    def verify(self):
        if digest(self._read(self.path)) != self.expected or digest(self._read(self.channel_path)) != self.plan['channelSha256']:
            raise ValueError('Changed fixture plan/channel')
        run = canonical_id(self.plan['runId'])
        if self._owned('.generated-telemetry-owner').read_text().strip() != run:
            raise ValueError('Owner marker mismatch')
        if self.channel['host'] != '127.0.0.1' or self.channel['port'] != 1883:
            raise ValueError('Only the owned shared-namespace loopback fixture is supported')
        device = self.channel['devices'][0]
        principal, subscriber = device['publisherPrincipal'], self.channel['subscriberUser']
        if principal == subscriber or not all(re.fullmatch(r'[A-Za-z0-9._-]{1,64}', p) for p in [principal, subscriber]):
            raise ValueError('Invalid fixture principals')
        topic = f"agrosphere/v1/estates/{device['estateId']}/devices/{device['deviceId']}/observations"
        acl = f'user {principal}\ntopic write {topic}\nuser {subscriber}\ntopic read {topic}\n'
        checks = [(self.channel['aclFile'], self.channel['aclSha256'], acl),
                  (self.channel['brokerConfigFile'], self.channel['brokerConfigSha256'], BROKER_CONFIG)]
        for name, expected, text in checks:
            raw = self._read(self._owned(name))
            if digest(raw) != expected or raw.decode() != text:
                raise ValueError('Unverified fixture ACL/config')
        state = self.execute(['docker', 'inspect', '--type', 'container', '-f',
                              '{{.State.Running}} {{index .Config.Labels "agrosphere.tlm.run"}}', self.container])
        if state.strip() != 'true ' + run:
            raise ValueError('Not the running owned fixture')
        hashes = self.execute(['docker', 'exec', self.container, 'sha256sum', '/tmp/config', '/tmp/acl', '/tmp/mosquitto_pub'])
        actual = {line.split()[1]: line.split()[0] for line in hashes.splitlines()}
        if actual != {'/tmp/config': self.channel['brokerConfigSha256'], '/tmp/acl': self.channel['aclSha256'],
                      '/tmp/mosquitto_pub': self.plan['publisherConfigSha256']}:
            raise ValueError('Running broker fixture changed')
        self.topic = topic

    def publish(self):
        for body in self.messages:
            self.verify()
            raw = json.dumps(body, sort_keys=True, separators=(',', ':'))
            if len(raw.encode()) > 4096:
                raise ValueError('Oversized generated observation')
            self.execute(['docker', 'exec', '-i', '-e', 'XDG_CONFIG_HOME=/tmp', self.container,
                          'mosquitto_pub', '-h', '127.0.0.1', '-t', self.topic, '-q', '1', '-s'], raw)
        # Transport publication is not a claim of committed domain acceptance.
        return {'transportPublished': len(self.messages), 'sampleCount': len(self.messages) // 3, 'dataProvenance': 'SIMULATED'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', required=True)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    try:
        report = GeneratedPublisher(args.plan, args.sha256).publish()
    except Exception:
        raise SystemExit('Generated telemetry publisher failed; no target fallback attempted') from None
    print(json.dumps(report))


if __name__ == '__main__':
    main()
