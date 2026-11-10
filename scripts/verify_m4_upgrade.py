"""Real nonempty 0001 -> 0002 preservation and wrong-target denial, wholly new AI fixture."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from platform_support import ROOT


def main():
    project = 'agrosphere-3a-check-' + uuid.uuid4().hex[:8]
    run = str(uuid.uuid4())
    network, image, postgres = project + '-dev', project + '-ai-upgrade', None
    record = {'status': 'NOT_RUN', 'scope': 'new owned M4 nonempty foundation upgrade only', 'project': project, 'runId': run}

    def docker(*args, input_text=None, check=True):
        r = subprocess.run(['docker', *args], input=input_text, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if check and r.returncode:
            raise RuntimeError('Owned upgrade Docker operation failed: ' + args[0])
        return r

    def sql(value, database='postgres'):
        return docker('exec', '-i', postgres, 'psql', '-U', 'postgres', '-d', database, '-At', '-v', 'ON_ERROR_STOP=1', input_text=value).stdout.strip()

    try:
        with tempfile.TemporaryDirectory(prefix='agrosphere-m4-upgrade-') as temporary:
            directory = Path(temporary)
            password, migration_password, runtime_password = [secrets.token_urlsafe(28) for _ in range(3)]
            migrator, runtime = 'm' + uuid.uuid4().hex, 'r' + uuid.uuid4().hex
            pg_env = directory / 'postgres.env'; pg_env.write_text('POSTGRES_PASSWORD=' + password + '\n')
            docker('network', 'create', '--label', 'com.docker.compose.project=' + project, network)
            postgres = docker('run', '-d', '--name', project + '-postgres', '--label', 'com.docker.compose.project=' + project,
                              '--network', network, '--network-alias', 'postgres', '--env-file', str(pg_env), 'postgres:18').stdout.strip()
            for _ in range(90):
                if docker('exec', postgres, 'pg_isready', '-U', 'postgres', check=False).returncode == 0:
                    break
                time.sleep(.5)
            else:
                raise RuntimeError('Owned upgrade PostgreSQL unavailable')
            sql("CREATE ROLE " + migrator + " LOGIN PASSWORD '" + migration_password + "' NOSUPERUSER NOCREATEDB NOCREATEROLE; CREATE ROLE " + runtime + " LOGIN PASSWORD '" + runtime_password + "' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;")
            sql('CREATE DATABASE agrosphere_ai_upgrade OWNER ' + migrator + ';')
            sql("COMMENT ON DATABASE agrosphere_ai_upgrade IS 'M4:" + run + "'; REVOKE ALL ON DATABASE agrosphere_ai_upgrade FROM PUBLIC;")
            sql('REVOKE CREATE ON SCHEMA public FROM PUBLIC;', 'agrosphere_ai_upgrade')
            now = datetime.now(timezone.utc)
            dsn = 'postgresql://' + runtime + ':' + runtime_password + '@postgres:5432/agrosphere_ai_upgrade'
            manifest = {'runId': run, 'project': project, 'createdAt': now.isoformat(), 'expiresAt': (now + timedelta(hours=1)).isoformat(),
                        'dsnSha256': hashlib.sha256(dsn.encode()).hexdigest(), 'dbMarker': 'M4:' + run, 'runtimeUser': runtime, 'migrationUser': migrator,
                        'scopes': [{'estateId': str(uuid.uuid4()), 'blockId': str(uuid.uuid4())}]}
            marker = directory / '.generated-m4-owner'; marker.write_text(run)
            manifest_file = directory / 'manifest.json'; manifest_file.write_text(json.dumps(manifest))
            env = directory / 'migration.env'
            env.write_text('AI_DATABASE_URL=' + dsn + '\nDATABASE_URL=postgresql+psycopg://' + migrator + ':' + migration_password + '@postgres:5432/agrosphere_ai_upgrade\nAI_GENERATED_MANIFEST=/fixture/manifest.json\nAI_GENERATED_MANIFEST_SHA256=' + hashlib.sha256(manifest_file.read_bytes()).hexdigest() + '\n')
            docker('build', '-t', image, str(ROOT.parent / 'agrosphere-ai-service'))
            record['imageId'] = docker('image', 'inspect', '-f', '{{.Id}}', image).stdout.strip()
            def migrate(target, check=True):
                return docker('run', '--rm', '--label', 'com.docker.compose.project=' + project, '--network', network,
                              '--env-file', str(env), '--mount', 'type=bind,source=' + str(directory) + ',target=/fixture,readonly',
                              image, 'alembic', 'upgrade', target, check=check)
            migrate('0001')
            event, aggregate, correlation = [str(uuid.uuid4()) for _ in range(3)]
            sql("INSERT INTO processed_event(consumer_name,event_id) VALUES ('M4_UPGRADE_PRESERVE','" + event + "'); INSERT INTO outbox_event(event_id,aggregate_id,event_type,event_version,correlation_id,occurred_at,payload) VALUES ('" + event + "','" + aggregate + "','SIMULATED_UPGRADE',1,'" + correlation + "',clock_timestamp(),'{\"policy\":\"SIMULATED_PRESERVATION_PROBE\"}');", 'agrosphere_ai_upgrade')
            digest_sql = "SELECT md5(row_to_json(p)::text) FROM processed_event p; SELECT md5(row_to_json(o)::text) FROM outbox_event o;"
            before = sql(digest_sql, 'agrosphere_ai_upgrade')
            sql("COMMENT ON DATABASE agrosphere_ai_upgrade IS 'WRONG_TARGET';")
            assert migrate('head', check=False).returncode != 0
            assert sql("SELECT version_num FROM alembic_version", 'agrosphere_ai_upgrade') == '0001'
            assert sql(digest_sql, 'agrosphere_ai_upgrade') == before
            sql("COMMENT ON DATABASE agrosphere_ai_upgrade IS 'M4:" + run + "';")
            migrate('head')
            assert sql('SELECT version_num FROM alembic_version', 'agrosphere_ai_upgrade') == '0002'
            assert sql(digest_sql, 'agrosphere_ai_upgrade') == before
            assert sql("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'ai_%'", 'agrosphere_ai_upgrade') == '7'
            record.update(status='PASS', freshFoundation=True, nonemptyUpgradePreserved=True, wrongTargetDeniedBeforeMigration=True, wrongTargetRollback=True,
                          oldRecordHashes=before.splitlines(), additiveTables=7)
            print('PASS: fresh 0001, nonempty upgrade, exact old row hashes, wrong-target denial/rollback.', flush=True)
    except Exception:
        record['status'] = 'FAILED'
        raise
    finally:
        if postgres:
            assert docker('inspect', '-f', '{{index .Config.Labels "com.docker.compose.project"}}', postgres).stdout.strip() == project
            mounts = json.loads(docker('inspect', '-f', '{{json .Mounts}}', postgres).stdout)
            volumes = [m['Name'] for m in mounts if m['Type'] == 'volume']
            docker('rm', '-f', '-v', postgres)
            assert all(docker('volume', 'inspect', v, check=False).returncode != 0 for v in volumes)
            record['ownedContainerAndVolumesRemoved'] = True
        docker('network', 'rm', network, check=False)
        record['ownedNetworkRemoved'] = docker('network', 'inspect', network, check=False).returncode != 0
        docker('image', 'rm', image, check=False)
        record['ownedImageTagAbsent'] = docker('image', 'inspect', image, check=False).returncode != 0
        (ROOT / 'target/m4-upgrade.json').write_text(json.dumps(record, indent=2) + '\n')


if __name__ == '__main__':
    main()
