"""Regression for actual Mosquitto negative PUBACK with process exit zero."""
import subprocess
import unittest

from poc_close_mqtt import verify_denied_puback


class PubackTest(unittest.TestCase):
    def test_exit_zero_with_reason135_is_a_broker_authorization_denial(self):
        result = subprocess.CompletedProcess([], 0, 'Client generated received PUBACK (Mid: 1, RC:135)\n',
                                             'Warning: Publish 1 failed: Not authorized.\n')
        self.assertEqual(verify_denied_puback(result), {'clientExitCode': 0, 'pubackReasonCodes': [135]})

    def test_no_matching_subscriber_and_cli_failure_do_not_prove_acl_denial(self):
        for result in (subprocess.CompletedProcess([], 0, 'Client generated received PUBACK (Mid: 1, RC:16)\n', ''),
                       subprocess.CompletedProcess([], 1, '', 'Connection refused')):
            with self.assertRaises(AssertionError):
                verify_denied_puback(result)


if __name__ == '__main__':
    unittest.main()
