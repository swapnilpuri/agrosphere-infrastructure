"""Failure-oriented tests for the independent generated watchdog policy."""
import copy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import privacy_maintenance_watchdog as watchdog


class PrivacyWatchdogTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
        self.fingerprint = "a" * 64
        envelope = {"version": 1, "policyRevision": watchdog.POLICY,
                    "targetFingerprint": self.fingerprint}
        self.heartbeat = dict(envelope, runId="00000000-0000-4000-8000-000000000001",
                              startedAt=self.at(-60), endedAt=self.at(-30),
                              databaseObservedAt=self.at(-40), lastVerifiedNoOverdueAt=None,
                              outcome="SUCCESS", processedRoots=0, batches=1, lastCommittedBatch=1)
        self.observation = dict(envelope, observedAt=self.at(0), eligibleRootCount=0,
                                copies={n: {"count": 0, "oldestEligibleAt": None} for n in watchdog.CLASSES},
                                pendingRemoval={"count": 0, "oldestRequestedAt": None})

    def at(self, seconds):
        return (self.now + timedelta(seconds=seconds)).isoformat()

    def evaluate(self):
        return watchdog.evaluate(self.fingerprint, self.heartbeat, self.observation, self.now)

    def backlog(self, name, seconds, count=1):
        self.observation["copies"][name] = {"count": count, "oldestEligibleAt": self.at(-seconds)}
        if name != "ledger":
            self.observation["eligibleRootCount"] = 1

    def test_healthy_requires_fresh_valid_independent_observation(self):
        self.assertEqual(self.evaluate()["state"], "HEALTHY")
        self.observation = None
        self.assertEqual(self.evaluate()["state"], "UNKNOWN")

    def test_zero_processed_with_locked_overdue_root_is_breach(self):
        self.backlog("read", 86400)
        self.assertEqual(self.evaluate()["state"], "BREACH")
        self.assertEqual(self.heartbeat["processedRoots"], 0)

    def test_physical_thresholds_are_inclusive_for_every_copy_class(self):
        for name in watchdog.CLASSES:
            for age, expected in [(43199.999, "HEALTHY"), (43200, "WARNING"),
                                  (86399.999, "WARNING"), (86400, "BREACH")]:
                with self.subTest(name=name, age=age):
                    self.setUp()
                    self.backlog(name, age)
                    self.assertEqual(self.evaluate()["state"], expected)

    def test_ledger_only_expiry_is_not_hidden_by_zero_roots(self):
        self.backlog("ledger", 90000)
        self.assertEqual(self.observation["eligibleRootCount"], 0)
        self.assertEqual(self.evaluate()["state"], "BREACH")

    def test_pending_removal_deadline_is_separate_and_inclusive(self):
        for age, expected in [(2591999.999, "HEALTHY"), (2592000, "BREACH")]:
            with self.subTest(age=age):
                self.observation["pendingRemoval"] = {"count": 1, "oldestRequestedAt": self.at(-age)}
                self.assertEqual(self.evaluate()["state"], expected)

    def test_missing_or_stale_heartbeat_does_not_clear_known_breach(self):
        self.heartbeat = None
        self.backlog("receipt", 90000)
        result = self.evaluate()
        self.assertEqual(result["state"], "BREACH")
        self.assertEqual(result["components"]["scheduler"]["state"], "UNKNOWN")

    def test_missed_run_threshold_is_inclusive(self):
        self.heartbeat.update(startedAt=self.at(-7260), endedAt=self.at(-7200), databaseObservedAt=self.at(-7230))
        self.assertEqual(self.evaluate()["state"], "WARNING")

    def test_recent_failed_job_visible_even_with_empty_backlog(self):
        self.heartbeat["outcome"] = "ERROR"
        self.assertEqual(self.evaluate()["state"], "ERROR")

    def test_unknown_commit_and_partial_run_are_not_success(self):
        for outcome, expected in [("UNKNOWN", "UNKNOWN"), ("PARTIAL", "WARNING")]:
            self.heartbeat["outcome"] = outcome
            self.assertEqual(self.evaluate()["state"], expected)

    def test_missing_eligibility_age_is_unknown(self):
        self.backlog("ack", 1)
        self.observation["copies"]["ack"]["oldestEligibleAt"] = None
        self.assertEqual(self.evaluate()["state"], "UNKNOWN")

    def test_known_breach_wins_over_unknown_age_in_other_class(self):
        self.backlog("ack", 1)
        self.observation["copies"]["ack"]["oldestEligibleAt"] = None
        self.backlog("evidence", 90000)
        self.assertEqual(self.evaluate()["state"], "BREACH")

    def test_pending_request_unknown_age_is_unknown(self):
        self.observation["pendingRemoval"]["count"] = 1
        self.assertEqual(self.evaluate()["state"], "UNKNOWN")

    def test_observer_freshness_and_future_skew_boundaries(self):
        for offset, expected in [(-299.999, "HEALTHY"), (-300, "UNKNOWN"),
                                 (60, "HEALTHY"), (60.001, "UNKNOWN")]:
            with self.subTest(offset=offset):
                self.observation["observedAt"] = self.at(offset)
                self.assertEqual(self.evaluate()["state"], expected)

    def test_foreign_target_or_policy_is_unknown_and_never_echoed(self):
        for field in ("targetFingerprint", "policyRevision"):
            for source in ("heartbeat", "observation"):
                with self.subTest(field=field, source=source):
                    self.setUp()
                    getattr(self, source)[field] = "sensitive-value-never-echo"
                    result = self.evaluate()
                    self.assertEqual(result["state"], "UNKNOWN")
                    self.assertNotIn("sensitive-value", json.dumps(result))

    def test_unexpected_identity_fields_are_rejected_without_disclosure(self):
        self.observation["subject"] = "personal-identity"
        result = self.evaluate()
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertNotIn("personal-identity", json.dumps(result))

    def test_invalid_counts_and_versions_fail_closed(self):
        for value in (True, -1, 1.0, "1", 2**63, None):
            with self.subTest(value=value):
                self.setUp()
                self.observation["eligibleRootCount"] = value
                self.assertEqual(self.evaluate()["state"], "UNKNOWN")
        self.setUp()
        self.observation["version"] = True
        self.assertEqual(self.evaluate()["state"], "UNKNOWN")

    def test_inconsistent_counts_and_future_eligibility_fail_closed(self):
        for mutate in (
            lambda o: o.update(eligibleRootCount=1),
            lambda o: o["copies"]["read"].update(count=1, oldestEligibleAt=self.at(-90000)),
            lambda o: o["copies"]["read"].update(oldestEligibleAt=self.at(-90000)),
            lambda o: o["pendingRemoval"].update(oldestRequestedAt=self.at(1)),
        ):
            with self.subTest(mutate=mutate):
                self.setUp()
                mutate(self.observation)
                self.assertEqual(self.evaluate()["state"], "UNKNOWN")
        self.setUp()
        self.backlog("read", -1)
        self.assertEqual(self.evaluate()["state"], "UNKNOWN")

    def test_invalid_clock_or_expected_fingerprint_is_unknown(self):
        for clock in (datetime(2026, 11, 1), "bad"):
            self.assertEqual(watchdog.evaluate(self.fingerprint, self.heartbeat, self.observation, clock)["state"], "UNKNOWN")
        self.assertEqual(watchdog.evaluate("bad", self.heartbeat, self.observation, self.now)["state"], "UNKNOWN")

    def test_bad_heartbeat_chronology_batch_and_outcome_are_unknown(self):
        changes = [{"startedAt": self.at(61), "endedAt": self.at(61)},
                   {"startedAt": self.at(0)}, {"databaseObservedAt": self.at(61)},
                   {"lastCommittedBatch": 2}, {"runId": None},
                   {"lastVerifiedNoOverdueAt": self.at(0)}, {"outcome": "OTHER"}]
        for change in changes:
            with self.subTest(change=change):
                self.setUp()
                self.heartbeat.update(change)
                self.assertEqual(self.evaluate()["state"], "UNKNOWN")

    def test_naive_or_non_utc_evidence_is_unknown(self):
        for at in ("2026-11-01T12:00:00", "2026-11-01T13:00:00+01:00", "invalid"):
            self.observation["observedAt"] = at
            self.assertEqual(self.evaluate()["state"], "UNKNOWN")

    def test_loader_rejects_duplicate_nonfinite_large_and_missing_input(self):
        path = Path("generated-fixture.json")
        for raw in ('{"version":1,"version":1}', '{"x":NaN}', '{"x":Infinity}',
                    'x' * (watchdog.MAX_INPUT_BYTES + 1), '\ufffd', '[' * 1500):
            with self.subTest(rawLength=len(raw)), patch.object(Path, "open", return_value=io.BytesIO(raw.encode())):
                self.assertIsNone(watchdog.load_fixture(path))
        with patch.object(Path, "open", side_effect=FileNotFoundError):
            self.assertIsNone(watchdog.load_fixture(path))
        with patch.object(Path, "open", return_value=io.BytesIO(b'{"version":1}')):
            self.assertEqual(watchdog.load_fixture(path), {"version": 1})

    def test_cli_missing_files_returns_sanitized_unknown(self):
        directory = "generated-missing-evidence-directory"
        with patch.object(Path, "open", side_effect=FileNotFoundError), redirect_stdout(io.StringIO()) as output:
            code = watchdog.main(["--generated-fixture", "--expected-fingerprint", self.fingerprint,
                                  "--heartbeat", str(Path(directory) / "missing"),
                                  "--observation", str(Path(directory) / "missing")])
            self.assertEqual(code, 3)
            result = json.loads(output.getvalue())
            self.assertEqual(result["state"], "UNKNOWN")
            self.assertNotIn(directory, output.getvalue())

    def test_evaluation_does_not_mutate_input_evidence(self):
        previous = copy.deepcopy((self.heartbeat, self.observation))
        self.evaluate()
        self.assertEqual(previous, (self.heartbeat, self.observation))


if __name__ == "__main__":
    unittest.main()
