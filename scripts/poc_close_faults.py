"""Bounded loopback fault adapter for exactly one owned fixture upstream.

No access/body/query/header logs, arbitrary upstream URLs or redirect following.
The real IdP remains the signer; its configured public issuer is this adapter.
"""
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
import threading
import time
from urllib.parse import urlsplit


HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade', 'content-length'}
LIMIT = 12 * 1024 * 1024


class OwnedHTTPServer(ThreadingHTTPServer):
    # The approved workload admits20 simultaneous connections. The stdlib
    # backlog5 induced SYN retransmission delays before Gateway received them.
    request_queue_size = 64


class FaultAdapter:
    def __init__(self, *, port, upstream_port, scope, private):
        assert scope in ('gateway', 'identity')
        assert 1024 <= port <= 65535 and 1024 <= upstream_port <= 65535 and port != upstream_port
        self.scope, self.private, self.upstream = scope, private, upstream_port
        self.events = []
        self.server = OwnedHTTPServer(('127.0.0.1', port), self.handler())
        self.server.daemon_threads = False
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()

    def rule(self, method, path):
        file = self.private / 'faults.json'
        if not file.exists():
            return None
        raw = file.read_bytes()
        assert len(raw) <= 65536
        rules = json.loads(raw)
        assert isinstance(rules, list) and len(rules) <= 16
        for rule in rules:
            if rule.get('scope') == self.scope and rule.get('method') == method and rule.get('path') == path:
                assert rule.get('action') in ('delay', 'status', 'malformed', 'oversize', 'empty', 'fixture-reply')
                return rule
        return None

    def handler(self):
        adapter = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_):
                pass

            def do_GET(self):
                self.forward()

            def do_POST(self):
                self.forward()

            def do_PUT(self):
                self.forward()

            def do_PATCH(self):
                self.forward()

            def do_DELETE(self):
                self.forward()

            def do_OPTIONS(self):
                self.forward()

            def send(self, code, body, headers=None):
                self.send_response(code)
                for key, value in headers or [('Content-Type', 'application/json'), ('Cache-Control', 'no-store')]:
                    if key.lower() not in HOP:
                        self.send_header(key, value)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Connection', 'close')
                self.end_headers()
                self.close_connection = True
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass  # Cancellation/oversize rejection is an expected native outcome.

            def forward(self):
                parsed = urlsplit(self.path)
                allowed = parsed.path.startswith('/api/v1/') or parsed.path.startswith('/api/v2/') if adapter.scope == 'gateway' else parsed.path.startswith(('/realms/agrosphere/', '/admin/', '/resources/')) or parsed.path == '/realms/master/protocol/openid-connect/token'
                if parsed.scheme or parsed.netloc or not allowed:
                    self.send(403, b'{"status":403,"title":"Owned route denied"}')
                    return
                length = self.headers.get('Content-Length', '0')
                if not length.isdecimal() or int(length) > 2 * 1024 * 1024 or self.headers.get('Transfer-Encoding'):
                    self.send(413, b'{"status":413}')
                    return
                self.connection.settimeout(15)
                body = self.rfile.read(int(length))
                try:
                    rule = adapter.rule(self.command, parsed.path)
                    if rule:
                        action = rule['action']
                        event = {'scope': adapter.scope, 'method': self.command, 'path': parsed.path,
                                 'action': action, 'startedMonotonic': time.monotonic()}
                        adapter.events.append(event)
                        if action == 'fixture-reply':
                            # One fixed owned file; no request-selected or arbitrary
                            # filesystem path. Size/hash reviewed for each case.
                            target = adapter.private / 'native-fault-reply.json'
                            assert not target.is_symlink() and not target.is_junction()
                            bound = 128 * 1024 if adapter.scope == 'identity' else 10 * 1024 * 1024
                            assert target.stat().st_size <= bound
                            with target.open('rb') as source:
                                value = source.read(bound + 1)
                            assert len(value) <= bound
                            fingerprint = hashlib.sha256(value).hexdigest()
                            assert fingerprint == rule.get('bodySha256')
                            event.update(bodySha256=fingerprint, bytes=len(value))
                            self.send(200, value)
                            return
                        if action == 'status':
                            status = rule.get('status')
                            assert status in (400, 401, 403, 404, 409, 413, 429, 500, 503)
                            self.send(status, json.dumps({'status': status, 'title': 'Owned injected fault'}).encode())
                            return
                        if action == 'malformed':
                            self.send(200, b'{"content":"wrong-type"}')
                            return
                        if action == 'oversize':
                            size = 128 * 1024 + 1 if adapter.scope == 'identity' else 10 * 1024 * 1024 + 1
                            self.send(200, b' ' * size)
                            return
                        if action == 'empty':
                            self.send(200, b'{"content":[],"page":0,"size":100,"totalElements":0}')
                            return
                    headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP | {'host'}}
                    # Advertised Keycloak hostname stays the adapter, signed tokens
                    # therefore retain their actual configured public issuer.
                    connection = HTTPConnection('127.0.0.1', adapter.upstream, timeout=15)
                    try:
                        connection.request(self.command, self.path, body, headers)
                        response = connection.getresponse()
                        value = response.read(LIMIT + 1)
                        assert len(value) <= LIMIT
                        status, response_headers = response.status, response.getheaders()
                    finally:
                        connection.close()
                    if rule and rule['action'] == 'delay':
                        deadline = time.monotonic() + 8
                        while time.monotonic() < deadline and not (adapter.private / 'release').exists():
                            time.sleep(.02)
                        event['releasedMonotonic'] = time.monotonic()
                    self.send(status, value, response_headers)
                except (OSError, ValueError, AssertionError):
                    self.send(502, b'{"status":502,"title":"Owned dependency unavailable"}')

        return Handler
