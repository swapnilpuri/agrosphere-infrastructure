# Privacy maintenance tooling — generated policy stage

Updated 2026-11-01. The independent watchdog evaluator is implemented; a database observer, cleanup runner, atomic heartbeat writer, scheduler and notification adapter are **not installed or delivered by this increment**. It does not query any database, inspect Docker, load private environment files, modify credentials/roles, delete records or send messages. Existing stack and data remain untouched.

## Scope and validation

`scripts/privacy_maintenance_watchdog.py` evaluates explicitly supplied generated heartbeat/aggregate-observation JSON files. This is an offline policy harness, not a target-authorization or deployed monitoring service. It cannot establish that the claimed target, database counts, ownership or collector exist. The future generated-only adapter must independently verify target ownership/migration/privilege state and produce fresh observations. Do not feed user records or production evidence to this stage.

Run independent tests from this repository:

```powershell
python -m unittest discover -s scripts -p test_privacy_maintenance_watchdog.py
python scripts/validate.py
```

The test step is included in the existing CI workflow. Local execution does not claim a hosted CI run. No dependency, image, topology, API/event contract or migration changed.

## Input format

Both inputs require exactly `version: 1`, `policyRevision: "AP_MAINTENANCE_1"` and an expected lowercase SHA-256 `targetFingerprint`. The fingerprint is a binding between supplied fixtures, not authentication. Unknown fields are rejected so identities cannot accidentally pass through. All timestamps require explicit UTC. File reads are limited to 64 KiB; duplicate JSON keys, nonfinite values, malformed/deep input and read failures yield UNKNOWN with no raw diagnostic/content echo.

Heartbeat fields: `runId` UUID; `startedAt`, `endedAt`, `databaseObservedAt`; nullable `lastVerifiedNoOverdueAt`; outcome `SUCCESS`, `PARTIAL`, `ERROR` or `UNKNOWN`; nonnegative integer `processedRoots`, `batches`, `lastCommittedBatch`. Completed batch cannot exceed batch count. End cannot precede start; future clock skew over 60 seconds is invalid. Last verified no-overdue cannot be later than the heartbeat database observation. That historical claim never replaces a fresh independent observation.

Observation fields: `observedAt`, `eligibleRootCount`, `copies`, `pendingRemoval`. `copies` has exactly `read`, `receipt`, `ack`, `evidence`, `ledger`; each contains nonnegative integer `count` and nullable `oldestEligibleAt`. Empty classes have null time; eligible classes with unknown time remain UNKNOWN. Eligible timestamps cannot be later than observation time. Ledger expiry is observable even with zero eligible roots. Root counts must be consistent with eligible non-ledger child counts. `pendingRemoval` contains `count` and nullable `oldestRequestedAt`; nonempty unknown age is UNKNOWN, empty has null age. Future request times are rejected.

The observer adapter must derive eligibility from every V7 cleanup predicate, including reopening watermarks and removal cutoffs. This evaluator validates shape/consistency, not SQL parity. Known due times must describe original eligibility, never reset at observation. Aggregate results still require restricted operational handling.

## States and boundaries

At 12 hours oldest physical eligibility age, warn; at 24 hours, breach. At verified removal request + 30 days, breach independently. Observation age at or over 300 seconds is stale; observation clock skew above 60 seconds is invalid. Two hours since the last completed job warns about missed hourly runs. A recent failed job stays ERROR even with empty backlog; partial is WARNING; uncertain commit is UNKNOWN. These are generated starting policy thresholds, not achieved service levels.

Output includes sanitized scheduler, backlog and removal component states. Overall priority is BREACH, UNKNOWN, ERROR, WARNING, HEALTHY, with exit codes 2, 3, 4, 1, 0 respectively. Thus a known overdue copy remains BREACH even if the heartbeat is missing; its missing-heartbeat component remains UNKNOWN. Malformed or foreign observations are not trusted for either healthy or breach claims. Zero roots processed never clears independently observed overdue work. A HEALTHY policy result means supplied evidence reports no overdue work; it does not mean all eligible copies have been deleted or an environment is operationally accepted.

CLI takes `--generated-fixture --expected-fingerprint <sha256> --heartbeat <generated-file> --observation <generated-file>`. It uses the current UTC clock and emits only enum states/reasons. Unit tests inject fixed clocks. The mandatory fixture flag marks this stage; it is not a security control that authorizes a database connection. Missing files produce sanitized UNKNOWN/exit 3.

## Next integration and open gates

Continue Operations-owned aggregate observer and privilege-boundary review, then generated-only connection/runner/heartbeat integration and a real disposable database failure/recovery drill. Test locked roots, large child counts, ledger-only work, unknown commit, stale/missing monitor evidence and original-source preservation. Do not modify V1–V7 to supply missing eligibility instants; review additive metadata if necessary. No runtime DELETE/DDL or broad table-read grant is introduced here.

Selected-environment maintenance authority, unattended scheduling, log/backup expiry and independent current-ledger synchronization remain OPEN. Actual-subject policy, existing-stack preflight/execution, owner functional, offline/French and M2 gates remain independent. No provider choice, actual-account activation, existing-stack authorization, deployment or AEO change follows from this policy harness.
