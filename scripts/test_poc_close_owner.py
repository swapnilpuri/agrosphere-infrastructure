"""Ownership/lifetime refusal tests; no Docker resource is created."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from poc_close_owner import Owner, LABEL


class OwnershipTest(unittest.TestCase):
    def owner(self):
        owner = Owner.__new__(Owner)
        owner.run = 'a' * 32
        owner.project = 'agrosphere-poc-close-' + owner.run
        owner.recovery = False
        owner.record = {'expiresUtc': None, 'images': {}, 'copyInventory': []}
        owner.persist = lambda: None
        return owner

    def test_foreign_label_refuses_before_any_removal(self):
        owner = self.owner()
        owner.ids = lambda kind: ['fixture-container'] if kind == 'container' else []
        info = {'Config': {'Labels': {LABEL: owner.run, 'com.docker.compose.project': 'another-project'}}}
        with patch('poc_close_owner.execute', return_value=subprocess.CompletedProcess([], 0, json.dumps([info]), '')) as run:
            with self.assertRaises(AssertionError):
                owner.cleanup()
            self.assertTrue(all('rm' not in call.args[0] for call in run.call_args_list))

    def test_unknown_copy_refuses_before_removal(self):
        owner = self.owner()
        owner.ids = lambda kind: []
        with tempfile.TemporaryDirectory(prefix=owner.project + '-') as directory:
            owner.private = Path(directory).resolve()
            (owner.private / '.poc-close-owner').write_text(owner.run)
            (owner.private / 'unknown-copy').write_text('generated')
            with patch('poc_close_owner.execute') as run:
                with self.assertRaises(AssertionError):
                    owner.cleanup()
                run.assert_not_called()
            self.assertTrue((owner.private / 'unknown-copy').exists())

    def test_old_or_retagged_image_refuses_before_any_removal(self):
        owner = self.owner()
        owner.ids = lambda kind: []
        owner.record['images'] = {owner.project + '-api': 'sha256:expected'}
        with tempfile.TemporaryDirectory(prefix=owner.project + '-') as directory:
            owner.private = Path(directory).resolve()
            (owner.private / '.poc-close-owner').write_text(owner.run)
            with patch('poc_close_owner.execute', return_value=subprocess.CompletedProcess([], 0, 'sha256:changed', '')) as run:
                with self.assertRaises(AssertionError):
                    owner.cleanup()
                self.assertTrue(all('rm' not in call.args[0] for call in run.call_args_list))

    def test_105_minute_admission_stop_is_before_expiry(self):
        owner = self.owner()
        owner.record['expiresUtc'] = (datetime.now(timezone.utc) + timedelta(minutes=14)).isoformat()
        with self.assertRaises(AssertionError):
            owner.check_lifetime()
        owner.check_lifetime(teardown=True)
        owner.record['expiresUtc'] = (datetime.now(timezone.utc) + timedelta(minutes=16)).isoformat()
        owner.check_lifetime()

    def test_inventory_is_required_for_raw_copy_cleanup(self):
        owner = self.owner()
        owner.ids = lambda kind: []
        with tempfile.TemporaryDirectory() as parent:
            with tempfile.TemporaryDirectory(prefix=owner.project + '-') as directory:
                owner.private = Path(directory).resolve()
                (owner.private / '.poc-close-owner').write_text(owner.run)
                (owner.private / 'generated-file').write_text('generated')
                owner.inventory_copies()
                with patch('poc_close_owner.execute') as run:
                    owner.cleanup()
                    run.assert_not_called()
                self.assertFalse(owner.private.exists())
                self.assertEqual(owner.record['cleanup'], 'PASS')

    def test_existing_image_tag_cannot_be_overwritten(self):
        owner = self.owner()
        with patch('poc_close_owner.execute', return_value=subprocess.CompletedProcess([], 0, 'exists', '')) as run:
            with self.assertRaises(AssertionError):
                owner.docker('build', '-t', owner.project + '-api', '.')
            self.assertEqual(len(run.call_args_list), 1)


if __name__ == '__main__':
    unittest.main()
