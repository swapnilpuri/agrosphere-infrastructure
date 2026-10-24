"""Create a private local environment without printing secrets. Never overwrites a file."""
import secrets
from pathlib import Path
root = Path(__file__).resolve().parents[1]
lines = []
for line in (root / '.env.example').read_text().splitlines():
    if line.startswith('#') or '=' not in line:
        lines.append(line)
        continue
    key, value = line.split('=', 1)
    if 'REPLACE' in value:
        value = secrets.token_urlsafe(32)
    lines.append(key + '=' + value)
with (root / '.env').open('x', encoding='utf-8') as out:
    out.write('\n'.join(lines) + '\n')
print('Created private .env with distinct random credentials.')
