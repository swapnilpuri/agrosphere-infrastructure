"""Serve an independent Web build with generated M5 configuration only."""
import argparse
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

parser = argparse.ArgumentParser()
parser.add_argument('--build', type=Path, required=True)
parser.add_argument('--manifest', type=Path, default=Path('target/m5-latest.json'))
args = parser.parse_args()
manifest = json.loads(args.manifest.read_text())
assert manifest['status'] == 'READY' and manifest['project'].startswith('agrosphere-m5-')
origin = urlsplit(manifest['webOrigin'])
assert origin.hostname == 'localhost' and origin.scheme == 'http' and origin.port
root = args.build.resolve(strict=True)
assert (root / 'index.html').is_file()
config = json.dumps({'apiBaseUrl': manifest['gateway'], 'keycloak': {
    'url': manifest['issuer'].split('/realms/')[0], 'realm': 'agrosphere',
    'clientId': 'agrosphere-web'}, 'cesium': {}}).encode()

class Handler(SimpleHTTPRequestHandler):
    def do_HEAD(self):
        self.send_error(405)

    def log_message(self, *_):
        pass  # Callback query strings must never be logged.

    def do_GET(self):
        path = urlsplit(self.path).path
        candidate = Path(self.translate_path(path)).resolve()
        if candidate == root / 'config.json':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(config)))
            self.end_headers()
            self.wfile.write(config)
            return
        if not candidate.is_relative_to(root):
            self.send_error(403)
            return
        if not candidate.is_file():
            self.path = '/index.html'
        super().do_GET()

print(f"Owned M5 Web build served at {manifest['webOrigin']}", flush=True)
ThreadingHTTPServer(('127.0.0.1', origin.port), partial(Handler, directory=str(root))).serve_forever()
