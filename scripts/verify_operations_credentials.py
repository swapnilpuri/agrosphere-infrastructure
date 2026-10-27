"""Disposable-only proof of the actual provisioning SQL; never reads any .env.

Generated credentials travel through process environments/stdin, not arguments or
logs. No Compose project or running stack is inspected or provisioned.
"""
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
import tempfile
import uuid

ROOT=Path(__file__).resolve().parents[1]


def main():
    name='agrosphere-credential-check-'+uuid.uuid4().hex
    env={**os.environ,'POSTGRES_PASSWORD':secrets.token_urlsafe(32),
         'OPERATIONS_DB_PASSWORD':secrets.token_urlsafe(32),
         'OPERATIONS_APP_DB_PASSWORD':secrets.token_urlsafe(32)}
    # Explicit empty env-file prevents Compose from loading any developer .env.
    generated={line.split('=',1)[0]:secrets.token_urlsafe(32) for line in (ROOT/'.env.example').read_text().splitlines()
               if '=' in line and line.split('=',1)[0].endswith('_PASSWORD')}
    with tempfile.TemporaryDirectory(prefix='agrosphere-configuration-check-') as directory:
        empty=Path(directory)/'empty.env';empty.write_text('',encoding='utf-8')
        result=subprocess.run(['docker','compose','--project-name',name,'--env-file',str(empty),'-f',str(ROOT/'compose.yaml'),'config','--quiet'],
                              env={**os.environ,**generated},capture_output=True,text=True)
        if result.returncode:raise RuntimeError('Generated-only Compose configuration validation failed; private output suppressed')
    container=None
    def run(args,body=None,check=True,extra=None):
        result=subprocess.run(['docker',*args],input=body,env={**env,**(extra or {})},capture_output=True,text=True)
        if check and result.returncode:
            raise RuntimeError('Disposable credential verification failed; private process output suppressed')
        return result
    try:
        result=run(['run','-d','--rm','--name',name,'--label','agrosphere.disposable='+name,
                    '-e','POSTGRES_PASSWORD','postgres:17-alpine'])
        container=result.stdout.strip()
        if not re.fullmatch('[a-f0-9]{64}',container):raise RuntimeError('Unexpected disposable container identifier')
        print('Started only disposable credential test container '+name,flush=True)
        for _ in range(100):
            if run(['exec',container,'pg_isready','-h','127.0.0.1','-U','postgres'],check=False).returncode==0:break
            time.sleep(0.2)
        else:raise RuntimeError('Disposable PostgreSQL readiness timeout')
        bootstrap=r"""\getenv owner_password OPERATIONS_DB_PASSWORD
SELECT format('CREATE ROLE agrosphere_operations LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', :'owner_password') \gexec
CREATE DATABASE agrosphere_operations OWNER agrosphere_operations;
REVOKE ALL ON DATABASE agrosphere_operations FROM PUBLIC;
"""
        run(['exec','-i','-e','OPERATIONS_DB_PASSWORD',container,'psql','-X','-v','ON_ERROR_STOP=1','-U','postgres','-d','postgres'],bootstrap)
        sql=(ROOT/'postgres/provision_operations_runtime.sql').read_text(encoding='utf-8')
        command=['exec','-i','-e','OPERATIONS_APP_DB_PASSWORD','-e','OPERATIONS_DB_PASSWORD',container,'psql','-X','-U','postgres','-d','agrosphere_operations']
        run(command,sql)
        run(command,sql) # Idempotence; no password reset.
        run(command,sql,extra={'OPERATIONS_APP_DB_PASSWORD':secrets.token_urlsafe(32)})
        assert run(command,sql,check=False,extra={'OPERATIONS_APP_DB_PASSWORD':env['OPERATIONS_DB_PASSWORD']}).returncode!=0,'Identical credential guard failed'
        login=['exec','-i','-e','PGPASSWORD',container,'psql','-X','-h','127.0.0.1','-U','agrosphere_operations_app','-d','agrosphere_operations','-At']
        result=run(login,'SELECT current_user;\n',extra={'PGPASSWORD':env['OPERATIONS_APP_DB_PASSWORD']})
        assert result.stdout.strip()=='agrosphere_operations_app'
        # psql must use ON_ERROR_STOP for an expected SQL failure to affect exit code.
        denied=run([*login,'-v','ON_ERROR_STOP=1'],'CREATE TABLE forbidden(id int);\n',check=False,extra={'PGPASSWORD':env['OPERATIONS_APP_DB_PASSWORD']})
        assert denied.returncode!=0,'Runtime role unexpectedly has schema DDL'
        wrong=['exec','-i','-e','OPERATIONS_APP_DB_PASSWORD',container,'psql','-X','-U','postgres','-d','postgres']
        assert run(wrong,sql,check=False).returncode!=0,'Wrong-database guard failed'
        print('PASS: actual restricted login, no DDL, Operations-only provisioning, idempotence and no existing-password rotation; generated credentials omitted.',flush=True)
    finally:
        if container and re.fullmatch('[a-f0-9]{64}',container):
            run(['rm','-f',container],check=False)
            print('Removed only the disposable credential test container.',flush=True)


if __name__=='__main__':main()
