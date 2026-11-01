"""Generated-fixture watchdog policy; no database, scheduler or delivery adapter.

Inputs are untrusted local evidence, never proof of target ownership or authority.
Keep this independent from the future cleanup runner so missed jobs are observable.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import uuid


POLICY = "AP_MAINTENANCE_1"
EXIT_CODES = {"HEALTHY": 0, "WARNING": 1, "BREACH": 2, "UNKNOWN": 3, "ERROR": 4}
PRIORITY = ("BREACH", "UNKNOWN", "ERROR", "WARNING", "HEALTHY")
CLASSES = ("read", "receipt", "ack", "evidence", "ledger")
ENVELOPE = {"version", "policyRevision", "targetFingerprint"}
MAX_INPUT_BYTES = 65536


def _time(value):
    if not isinstance(value, str):
        raise ValueError("timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() != timedelta(0):
        raise ValueError("UTC required")
    return result


def _count(value):
    if type(value) is not int or value < 0 or value > 2**63 - 1:
        raise ValueError("count")
    return value


def _envelope(value, expected, fields):
    if not isinstance(value, dict) or set(value) != ENVELOPE | fields:
        raise ValueError("shape")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("version")
    if value["policyRevision"] != POLICY or value["targetFingerprint"] != expected:
        raise ValueError("binding")


def _signal(state, reason):
    return {"state": state, "reason": reason}


def _heartbeat(value, expected, now):
    try:
        _envelope(value, expected, {
            "runId", "startedAt", "endedAt", "outcome", "processedRoots",
            "batches", "lastCommittedBatch", "databaseObservedAt",
            "lastVerifiedNoOverdueAt",
        })
        uuid.UUID(value["runId"])
        start, end = _time(value["startedAt"]), _time(value["endedAt"])
        db = _time(value["databaseObservedAt"])
        verified = value["lastVerifiedNoOverdueAt"]
        if verified is not None and _time(verified) > db:
            raise ValueError("verified observation")
        if start > end or end > now + timedelta(seconds=60):
            raise ValueError("clock")
        if db > end + timedelta(seconds=60) or db > now + timedelta(seconds=60):
            raise ValueError("database clock")
        batches = _count(value["batches"])
        if _count(value["lastCommittedBatch"]) > batches:
            raise ValueError("batch")
        _count(value["processedRoots"])
        outcome = value["outcome"]
        if outcome not in ("SUCCESS", "PARTIAL", "ERROR", "UNKNOWN"):
            raise ValueError("outcome")
        if outcome == "ERROR":
            return _signal("ERROR", "LAST_JOB_FAILED")
        if outcome == "UNKNOWN":
            return _signal("UNKNOWN", "LAST_JOB_UNCERTAIN")
        if now - end >= timedelta(hours=2):
            return _signal("WARNING", "MISSED_RUNS")
        if outcome == "PARTIAL":
            return _signal("WARNING", "PARTIAL_RUN")
        return _signal("HEALTHY", "RECENT_JOB_SUCCESS")
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
        return _signal("UNKNOWN", "HEARTBEAT_INVALID_OR_MISSING")


def _observation(value, expected, now):
    """Validate the whole snapshot before using any of its claimed counts/ages."""
    _envelope(value, expected, {
        "observedAt", "eligibleRootCount", "copies", "pendingRemoval",
    })
    observed = _time(value["observedAt"])
    if observed > now + timedelta(seconds=60) or now - observed >= timedelta(seconds=300):
        raise ValueError("observation clock/freshness")
    _count(value["eligibleRootCount"])
    if not isinstance(value["copies"], dict) or set(value["copies"]) != set(CLASSES):
        raise ValueError("classes")
    deadlines = []
    unknown_age = False
    for name in CLASSES:
        item = value["copies"][name]
        if not isinstance(item, dict) or set(item) != {"count", "oldestEligibleAt"}:
            raise ValueError("copy shape")
        count = _count(item["count"])
        at = item["oldestEligibleAt"]
        if not count:
            if at is not None:
                raise ValueError("empty class has deadline")
        elif at is None:
            unknown_age = True
        else:
            at = _time(at)
            if at > observed:
                raise ValueError("not eligible")
            deadlines.append(at)
    # A root cannot be eligible without a corresponding eligible child class.
    child_count = sum(value["copies"][n]["count"] for n in CLASSES if n != "ledger")
    if (value["eligibleRootCount"] == 0) != (child_count == 0):
        raise ValueError("root/copy inconsistency")
    if value["eligibleRootCount"] > child_count:
        raise ValueError("root count")
    removal = value["pendingRemoval"]
    if not isinstance(removal, dict) or set(removal) != {"count", "oldestRequestedAt"}:
        raise ValueError("removal shape")
    count = _count(removal["count"])
    requested = removal["oldestRequestedAt"]
    if not count and requested is not None:
        raise ValueError("empty removal")
    if requested is not None:
        requested = _time(requested)
        if requested > observed:
            raise ValueError("future removal")
    return deadlines, unknown_age, count, requested


def evaluate(expected_fingerprint, heartbeat, observation, now=None):
    """Return sanitized component states. Zero processed roots never clears backlog."""
    now = now if now is not None else datetime.now(timezone.utc)
    if not isinstance(expected_fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_fingerprint):
        return {"state": "UNKNOWN", "exitCode": 3, "components": {
            "inputs": _signal("UNKNOWN", "INVALID_EXPECTED_TARGET"),
        }}
    if not isinstance(now, datetime) or now.utcoffset() != timedelta(0):
        return {"state": "UNKNOWN", "exitCode": 3, "components": {
            "inputs": _signal("UNKNOWN", "INVALID_CLOCK"),
        }}
    components = {"scheduler": _heartbeat(heartbeat, expected_fingerprint, now)}
    try:
        deadlines, unknown_age, pending, requested = _observation(observation, expected_fingerprint, now)
        age = (now - min(deadlines)).total_seconds() if deadlines else 0
        if age >= 86400:
            backlog = _signal("BREACH", "PHYSICAL_CLEANUP_OVERDUE")
        elif unknown_age:
            backlog = _signal("UNKNOWN", "ELIGIBILITY_AGE_UNKNOWN")
        elif age >= 43200:
            backlog = _signal("WARNING", "PHYSICAL_CLEANUP_DUE_SOON")
        else:
            backlog = _signal("HEALTHY", "NO_OVERDUE_COPIES_OBSERVED")
        if pending and requested is None:
            removal = _signal("UNKNOWN", "REMOVAL_AGE_UNKNOWN")
        elif requested is not None and now - requested >= timedelta(days=30):
            removal = _signal("BREACH", "VERIFIED_REMOVAL_OVERDUE")
        else:
            removal = _signal("HEALTHY", "NO_OVERDUE_REMOVAL_OBSERVED")
        components.update(backlog=backlog, removal=removal)
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
        components.update(
            backlog=_signal("UNKNOWN", "OBSERVATION_INVALID_OR_MISSING"),
            removal=_signal("UNKNOWN", "OBSERVATION_INVALID_OR_MISSING"),
        )
    state = next(s for s in PRIORITY if any(c["state"] == s for c in components.values()))
    return {"state": state, "exitCode": EXIT_CODES[state], "components": components}


def _reject_constant(_):
    raise ValueError("nonfinite value")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def load_fixture(path):
    """Bound input and suppress raw parser/path/content diagnostics."""
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            return None
        return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-fixture", required=True, action="store_true")
    parser.add_argument("--expected-fingerprint", required=True)
    parser.add_argument("--heartbeat", required=True)
    parser.add_argument("--observation", required=True)
    args = parser.parse_args(argv)
    result = evaluate(args.expected_fingerprint, load_fixture(args.heartbeat), load_fixture(args.observation))
    print(json.dumps(result, sort_keys=True))
    return result["exitCode"]


if __name__ == "__main__":
    raise SystemExit(main())
