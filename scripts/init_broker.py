"""Import topology after RabbitMQ has bootstrapped its private default user."""
import base64
import os
import time
import urllib.request
from pathlib import Path
for attempt in range(60):
    try:
        request=urllib.request.Request('http://rabbitmq:15672/api/definitions', data=Path('/scripts/definitions.json').read_bytes(), method='POST', headers={
            'Content-Type':'application/json',
            'Authorization':'Basic '+base64.b64encode(('agrosphere:'+os.environ['RABBITMQ_PASSWORD']).encode()).decode()})
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status in (200,204)
        print('Imported durable development event topology.')
        break
    except Exception:
        if attempt==59: raise RuntimeError('Broker management API unavailable; topology was not imported') from None
        time.sleep(1)
