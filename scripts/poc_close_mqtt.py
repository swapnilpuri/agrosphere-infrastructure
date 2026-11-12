"""Finite weather/soil publication through two owned MQTT principals."""
import hashlib
import json
import re
import uuid

from telemetry_simulator import BROKER_CONFIG, sequence


def verify_denied_puback(result):
    reasons = [int(value) for value in re.findall(r'received PUBACK \(Mid: \d+, RC:(\d+)\)', result.stdout + result.stderr)]
    assert reasons == [135], 'Cross-topic publication must receive MQTTv5 Not authorized'
    return {'clientExitCode': result.returncode, 'pubackReasonCodes': reasons}


def publish(owner, directory, mqtt, plan, channel):
    owner.check_lifetime()
    directory = directory.resolve(strict=True)
    assert directory.parent == owner.private and not directory.is_symlink() and not directory.is_junction()
    run = str(uuid.UUID(owner.run))
    assert (directory / '.generated-telemetry-owner').read_text() == run
    assert channel['runId'] == plan['runId'] == run
    assert channel['host'] == '127.0.0.1' and channel['port'] == 1883
    assert len(channel['devices']) == 2
    weather, soil = channel['devices']
    principals = [weather['publisherPrincipal'], soil['publisherPrincipal'], channel['subscriberUser']]
    assert len(set(principals)) == 3 and all(re.fullmatch(r'[A-Za-z0-9._-]{1,64}', p) for p in principals)
    topics = []
    for device in (weather, soil):
        for key in ('deviceId', 'estateId', 'blockId'):
            assert str(uuid.UUID(device[key])) == device[key]
        assert device['estateId'] == owner.record['canonical']['estateId']
        assert device['blockId'] == owner.record['canonical']['blockId']
        topics.append(f"agrosphere/v1/estates/{device['estateId']}/devices/{device['deviceId']}/observations")
    assert topics[0] != topics[1]
    topic_principals = sorted(zip(topics, principals[:2]))
    expected_acl = ''.join(f'user {who}\ntopic write {allowed}\n' for allowed, who in topic_principals)
    expected_acl += f'user {principals[2]}\n' + ''.join(f'topic read {allowed}\n' for allowed, _ in topic_principals)
    assert (directory / 'acl').read_text() == expected_acl
    assert (directory / 'broker.conf').read_text() == BROKER_CONFIG
    fingerprint = lambda file: hashlib.sha256(file.read_bytes()).hexdigest()
    assert fingerprint(directory / 'manifest.json') == plan['channelSha256']
    assert fingerprint(directory / 'acl') == channel['aclSha256']
    assert fingerprint(directory / 'broker.conf') == channel['brokerConfigSha256']
    expected_hashes = {'/tmp/config': channel['brokerConfigSha256'], '/tmp/acl': channel['aclSha256'],
        '/tmp/mosquitto_pub': fingerprint(directory / 'mosquitto_pub'),
        '/tmp/soil/mosquitto_pub': fingerprint(directory / 'soil/mosquitto_pub')}

    def verify_running():
        state = owner.docker('inspect', '--type', 'container', '-f',
            '{{.State.Running}} {{index .Config.Labels "agrosphere.tlm.run"}}', mqtt).stdout.strip()
        assert state == 'true ' + run
        hashes = owner.docker('exec', mqtt, 'sha256sum', *expected_hashes).stdout.splitlines()
        assert {line.split()[1]: line.split()[0] for line in hashes} == expected_hashes

    def send(body, device_index, topic=None, check=True, mqtt_v5=False):
        verify_running()
        encoded = json.dumps(body, sort_keys=True, separators=(',', ':'))
        assert len(encoded.encode()) <= 4096
        return owner.docker('exec', '-i', '-e', 'XDG_CONFIG_HOME=' + ('/tmp' if device_index == 0 else '/tmp/soil'),
            mqtt, 'mosquitto_pub', '-h', '127.0.0.1', '-t', topic or topics[device_index],
            *(['-V', 'mqttv5', '-d'] if mqtt_v5 else []), '-q', '1', '-s', input_text=encoded, check=check)

    messages = []
    for index, device in enumerate((weather, soil)):
        selected = {**channel, 'devices': [device]}
        kinds = {'AIR_TEMPERATURE', 'INTERVAL_RAINFALL'} if index == 0 else {'SOIL_MOISTURE'}
        messages.extend((index, message) for message in sequence(selected, plan) if message['kind'] in kinds)
    assert len(messages) == 18
    sample = messages[0][1]
    # These are rejected inputs to the existing consumer and exact-topic ACL.
    send({**sample, 'schemaVersion': 2}, 0)
    send({**sample, 'unit': 'PERCENT'}, 0)
    denied = send(sample, 0, topics[1], check=False, mqtt_v5=True)
    acknowledgement = verify_denied_puback(denied)
    for index, body in messages:
        send(body, index)
    send(messages[0][1], messages[0][0])
    report = {'runId': owner.run, 'weatherDeviceId': weather['deviceId'], 'soilDeviceId': soil['deviceId'],
        'estateId': weather['estateId'], 'blockId': weather['blockId'], 'distinctPublishers': True,
        'exactTopics': topics, 'validPublications': 18, 'duplicatePublications': 1,
        'invalidInputProbes': ['schemaVersion', 'unit', 'deviceTopicScope'], 'crossTopicPublishDenied': True,
        'crossTopicAcknowledgement': acknowledgement,
        'scopeEvidence': 'Connected scope probe exercises broker topic authorization. Independent Telemetry tests cover payload mapping.',
        'result': 'TRANSPORT_COMPLETE_CONSUMER_COUNTS_CHECKED_BY_ENVIRONMENT_FLOW'}
    (owner.path.parent / 'mqtt-two-device.json').write_text(json.dumps(report, indent=2) + '\n')
    return report
