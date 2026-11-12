"""Regression for the actual owner-context shadowing failure in the M4 adapter."""
from types import SimpleNamespace
import unittest
import subprocess
import sys
from unittest.mock import MagicMock

import verify_m4
from poc_close_owner import execute, process_identity


class ProbeReached(Exception):
    pass


class CallbackTest(unittest.TestCase):
    def test_blocked_cli_input_cannot_prevent_supervised_timeout_and_tree_stop(self):
        checks = []
        owner = SimpleNamespace(record={}, persist=lambda: None, check_lifetime=lambda: checks.append(True))
        with self.assertRaises(subprocess.TimeoutExpired):
            execute([sys.executable, '-c', 'import time; time.sleep(30)'], input_text='x' * 1048576,
                    timeout=.3, owner=owner)
        self.assertTrue(checks)
        child = owner.record['cliProcesses'][0]
        self.assertTrue(child['completed'])
        self.assertIsNone(process_identity(child['pid']))

    def test_m4_callback_uses_the_supplied_owner_before_local_marker_creation(self):
        project = 'agrosphere-poc-close-' + 'a' * 32
        owner = SimpleNamespace(project=project, docker=MagicMock(side_effect=ProbeReached), path=MagicMock())
        compose = MagicMock(return_value=SimpleNamespace(stdout='owned-gateway'))
        def platform(acceptance):
            acceptance(config={'COMPOSE_PROJECT_NAME': project}, compose=compose,
                       directory=MagicMock(), run='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        with self.assertRaises(ProbeReached):
            verify_m4.main(platform_runner=platform, owner=owner)
        owner.docker.assert_called_once()


if __name__ == '__main__':
    unittest.main()
