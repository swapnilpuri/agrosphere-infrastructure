"""Owned static Web listener; never reads the developer's public config file."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit
from poc_close_faults import OwnedHTTPServer


class Web:
    def __init__(self, owner, build):
        self.root = Path(build).resolve(strict=True)
        assert (self.root / 'index.html').is_file()
        config = json.dumps({'apiBaseUrl': owner.record['gateway'], 'keycloak': {
            'url': owner.config['OIDC_PUBLIC_URL'], 'realm': 'agrosphere', 'clientId': 'agrosphere-web'},
            'cesium': {}, 'verification': {'runId': owner.run}}).encode()
        root = self.root

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *_):
                pass

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

        self.server = OwnedHTTPServer(('127.0.0.1', owner.web_port), partial(Handler, directory=str(root)))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()
