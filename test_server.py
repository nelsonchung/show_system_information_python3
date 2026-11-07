import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import server


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.http.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()

    def get(self, path):
        return urlopen(self.url + path, timeout=10)

    def test_live_system_data(self):
        with self.get('/api/system') as response:
            data = json.load(response)
        self.assertGreater(data['memory']['total'], 0)
        self.assertGreater(data['uptime_seconds'], 0)
        self.assertGreaterEqual(data['cpu']['percent'], 0)
        self.assertLessEqual(data['cpu']['percent'], 100)
        self.assertTrue(data['disks'])
        self.assertTrue(data['network'])

    def test_dmesg_limit(self):
        with patch('server.command', return_value={'available': True, 'output': 'a\nb\nc', 'error': None}):
            with self.get('/api/dmesg?lines=2') as response:
                data = json.load(response)
        self.assertEqual(data['lines'], ['b', 'c'])
        self.assertEqual(data['total_lines'], 3)

    def test_permission_failure_is_visible(self):
        with patch('server.command', return_value={'available': False, 'output': '', 'error': 'Operation not permitted'}):
            with self.assertRaises(HTTPError) as caught:
                self.get('/api/dmesg')
            self.assertEqual(caught.exception.code, 503)
            self.assertEqual(json.load(caught.exception)['error'], 'Operation not permitted')

    def test_reject_invalid_limits(self):
        for value in ['0', '-1', '1001', 'abc', '1%3Bwhoami']:
            with self.assertRaises(HTTPError) as caught:
                self.get('/api/dmesg?lines=' + value)
            self.assertEqual(caught.exception.code, 400)

    def test_no_arbitrary_file_access(self):
        for path in ['/server.py', '/.git/config', '/../etc/passwd']:
            with self.assertRaises(HTTPError) as caught:
                self.get(path)
            self.assertEqual(caught.exception.code, 404)

    def test_static_files_and_health(self):
        for path in ['/', '/app.js', '/style.css', '/api/health']:
            with self.get(path) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(response.read())
                self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_diagnostics_routes(self):
        fixtures = {
            '/api/network': {'available': True, 'error': None, 'interfaces': [],
                             'wifi_available': False, 'wifi_error': 'not supported'},
            '/api/services': {'available': True, 'error': None, 'units': []},
            '/api/processes': {'available': True, 'error': None, 'total': 0,
                               'cpu_top': [], 'memory_top': []},
            '/api/usb': {'available': True, 'error': None, 'devices': []},
        }
        for path, payload in fixtures.items():
            with self.subTest(path=path):
                with patch.dict(server.diagnostics_routes, {path: lambda: payload}):
                    with self.get(path) as response:
                        self.assertEqual(json.load(response), payload)

    def test_diagnostics_failure_does_not_break_health(self):
        for path in server.diagnostics_routes:
            payload = {'available': False, 'error': 'source unavailable'}
            with patch.dict(server.diagnostics_routes, {path: lambda: payload}):
                with self.assertRaises(HTTPError) as caught:
                    self.get(path)
                self.assertEqual(caught.exception.code, 503)
                self.assertEqual(json.load(caught.exception)['error'], 'source unavailable')
                with self.get('/api/health') as response:
                    self.assertEqual(json.load(response)['status'], 'ok')

    def test_missing_command(self):
        self.assertFalse(server.command(['/nonexistent-command'])['available'])


if __name__ == '__main__':
    unittest.main()
