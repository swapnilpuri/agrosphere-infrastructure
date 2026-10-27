"""Explicit operator tool; never reads .env files or prints credentials/SQL errors.

Implementation is authorized; invocation on an existing stack requires a separate
operator action. Use environment PGPASSWORD and OPERATIONS_APP_DB_PASSWORD.
"""
import argparse
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--port', type=int, default=5432)
    parser.add_argument('--admin-user', required=True)
    parser.add_argument('--database', choices=['agrosphere_operations'], default='agrosphere_operations')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        print('No changes: explicit --apply is required for this operator-controlled action.')
        return
    if not 1 <= args.port <= 65535:
        parser.error('Invalid PostgreSQL port')
    password = os.environ.get('OPERATIONS_APP_DB_PASSWORD', '')
    owner_password = os.environ.get('OPERATIONS_DB_PASSWORD', '')
    if len(password) < 16 or 'REPLACE' in password or not owner_password or password == owner_password:
        parser.error('Supply generated runtime credentials through the environment; values are never printed.')
    result = subprocess.run(['psql', '-X', '--host', args.host, '--port', str(args.port),
                             '--username', args.admin_user, '--dbname', args.database,
                             '--file', str(ROOT/'postgres/provision_operations_runtime.sql')],
                            env=dict(os.environ), capture_output=True, text=True)
    if result.returncode:
        raise SystemExit('Operations runtime provisioning failed; no private process output was printed. Review role drift and operator prerequisites.')
    print('Operations runtime role provisioned/validated; existing passwords are not rotated.')


if __name__ == '__main__':
    main()
