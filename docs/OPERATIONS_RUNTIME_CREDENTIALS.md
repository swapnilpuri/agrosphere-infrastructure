# Operations runtime and Flyway credentials

Milestone 3B uses two independent identities in the Operations database:

| Identity | Purpose | Private input |
|---|---|---|
| agrosphere_operations | Migration owner; owns V1/V2/V3 objects | OPERATIONS_DB_PASSWORD -> FLYWAY_PASSWORD |
| agrosphere_operations_app | Restricted application login; no DDL, role inheritance or ownership | OPERATIONS_APP_DB_PASSWORD -> DB_PASSWORD |

Tracked examples contain placeholders only. No password belongs in command arguments, logs, source or chat. Spring consumes FLYWAY_USER/FLYWAY_PASSWORD independently of DB_USER/DB_PASSWORD. There is no fallback to migration-owner credentials for application access.

Fresh disposable volumes run postgres/init.sh and the mounted provisioning SQL before service migration. V3 installs table grants, evidence/receipt guards and deferred invariants. The existing init_local.py generates the new placeholder through its generic no-overwrite logic; it must not be run to modify an existing private file.

## Existing environments: future operator action only

The present owner authorization permits implementation and generated disposable tests only. **No existing/running stack is provisioned by this development session.** Do not rerun bootstrap against populated volumes or start the intermediate image with missing role/credential settings.

The new scripts/provision_operations_runtime.py is an explicit operator tool. It reads process environment inputs, never .env files; defaults to no changes and requires --apply. Its SQL accepts only the Operations database, requires distinct owner/runtime credentials, creates a missing restricted login atomically and validates existing flags/membership/ownership. It never silently repairs unsafe roles or rotates an existing password.

When separately authorized for an operator-controlled environment, supply PGPASSWORD, OPERATIONS_DB_PASSWORD and OPERATIONS_APP_DB_PASSWORD privately and invoke the tool with explicit host/admin identity/database. No credential literal should appear in the invocation. Existing roles with unsafe drift fail closed and require review. Update the private deployment inputs separately; this repository never reads or overwrites them automatically.

## Generated-only verification

```powershell
python scripts/validate.py
python scripts/verify_operations_credentials.py
```

The verification uses generated values and an explicit empty Compose env-file, then creates only its own labelled disposable PostgreSQL container. It checks actual runtime authentication, refused schema DDL, wrong-database and identical-password guards, idempotence and preservation of the original runtime password on repeated provisioning. Cleanup targets only the created container ID; no active project, database or .env is inspected.

Operations' independent CollectionCredentialsIT also verifies actual runtime/Flyway identities, restricted evidence privileges and a pinned prior-3A image against V3 with Flyway disabled during the rollback rehearsal. Run its integration profile with Java 25 and Docker access. This proof does not authorize production rollout or reversal of populated evidence.
