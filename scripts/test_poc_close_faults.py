"""Real loopback adapter tests; no platform fixture or actual identity data."""
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
from pathlib import Path
import tempfile
import threading
import time
import unittest

from poc_close_faults import FaultAdapter
from verify_tapping import free_port


class AdapterTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='poc-close-adapter-test-')
        self.private = Path(self.directory.name)
        self.requests = []
        requests = self.requests
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                requests.append(self.path)
                self.send_response(307 if self.path.startswith('/api/v1/redirect') else 200)
                self.send_header('Location', 'http://127.0.0.1:1/never-follow')
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'{}')
            def do_PATCH(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                requests.append((self.command, self.path, body, self.headers.get('Idempotency-Key')))
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        self.upstream = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        self.thread.start()
        self.port = free_port()
        self.adapter = FaultAdapter(port=self.port, upstream_port=self.upstream.server_port, scope='gateway', private=self.private)
        self.adapter.start()

    def tearDown(self):
        self.adapter.close()
        self.upstream.shutdown()
        self.upstream.server_close()
        self.thread.join(timeout=5)
        self.directory.cleanup()

    def get(self, path):
        connection = HTTPConnection('127.0.0.1', self.port, timeout=12)
        try:
            connection.request('GET', path)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_absolute_url_and_unowned_route_never_reach_upstream(self):
        for path in ('http://example.invalid/api/v1/x', '/arbitrary'):
            self.assertEqual(self.get(path)[0], 403)
        self.assertEqual(self.requests, [])

    def test_redirect_is_returned_without_following_it(self):
        self.assertEqual(self.get('/api/v1/redirect')[0], 307)
        self.assertEqual(self.requests, ['/api/v1/redirect'])

    def test_patch_preserves_body_and_idempotency_key(self):
        connection = HTTPConnection('127.0.0.1', self.port, timeout=12)
        body = b'{"version":0,"displayName":"SIMULATED Updated"}'
        try:
            connection.request('PATCH', '/api/v1/workers/generated', body,
                               {'Content-Type': 'application/json', 'Idempotency-Key': 'generated-key'})
            response = connection.getresponse()
            self.assertEqual((response.status, response.read()), (200, body))
        finally:
            connection.close()
        self.assertEqual(self.requests, [('PATCH', '/api/v1/workers/generated', body, 'generated-key')])

    def test_exact_rule_does_not_affect_another_route(self):
        (self.private / 'faults.json').write_text(json.dumps([{'scope': 'gateway', 'method': 'GET',
            'path': '/api/v1/a', 'action': 'status', 'status': 503}]))
        self.assertEqual(self.get('/api/v1/a')[0], 503)
        self.assertEqual(self.get('/api/v1/b')[0], 200)
        self.assertEqual(self.requests, ['/api/v1/b'])

    def test_delay_retains_real_response_until_explicit_release_without_query_evidence(self):
        (self.private / 'faults.json').write_text(json.dumps([{'scope': 'gateway', 'method': 'GET',
            'path': '/api/v1/a', 'action': 'delay'}]))
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(self.get, '/api/v1/a?generated-private-value=do-not-retain')
            end = time.monotonic() + 5
            while not self.requests and time.monotonic() < end:
                time.sleep(.01)
            self.assertTrue(self.requests)
            self.assertFalse(result.done())
            (self.private / 'release').write_text('release')
            self.assertEqual(result.result(timeout=5), (200, b'{}'))
        self.assertNotIn('do-not-retain', json.dumps(self.adapter.events))
        self.assertIn('releasedMonotonic', self.adapter.events[0])

    def test_bad_fault_configuration_fails_closed_without_upstream(self):
        (self.private / 'faults.json').write_text('{invalid')
        self.assertEqual(self.get('/api/v1/a')[0], 502)
        self.assertEqual(self.requests, [])

    def test_fixture_reply_requires_fixed_file_exact_hash_and_bounded_body(self):
        body = b'{"content":[],"page":0,"size":100,"totalElements":0}'
        target = self.private / 'native-fault-reply.json'
        target.write_bytes(body)
        rule = {'scope': 'gateway', 'method': 'GET', 'path': '/api/v1/a', 'action': 'fixture-reply',
                'bodySha256': hashlib.sha256(body).hexdigest()}
        (self.private / 'faults.json').write_text(json.dumps([rule]))
        self.assertEqual(self.get('/api/v1/a'), (200, body))
        target.write_bytes(body + b' ')
        self.assertEqual(self.get('/api/v1/a')[0], 502)
        target.write_bytes(b' ' * (10 * 1024 * 1024 + 1))
        self.assertEqual(self.get('/api/v1/a')[0], 502)
        self.assertEqual(self.requests, [])


if __name__ == '__main__':
    unittest.main()
