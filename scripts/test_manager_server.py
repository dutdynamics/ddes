"""Local HTTP regression tests; no GitHub writes or real PDF compilation."""

from copy import deepcopy
from datetime import datetime, timedelta
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

from archive_events import DALIAN
from manager_server import MAX_BODY, ManagerApp, main, make_handler
from report_builder import ReportError


class FakeStore:
    def __init__(self, event):
        self.event = event
        self.snapshot_calls = 0
        self.publish_calls = []

    def snapshot(self):
        self.snapshot_calls += 1
        return {'events': [deepcopy(self.event)], 'warnings': [], 'revision': '1' * 40}

    def publish(self, events, revision, pdf_paths=None):
        # Reading attachments here checks that they exist until publication ends.
        pdf_data = {identity: Path(path).read_bytes() for identity, path in (pdf_paths or {}).items()}
        self.publish_calls.append((deepcopy(events), revision, pdf_data))
        return {'status': 'merged', 'revision': '2' * 40,
                'prUrl': 'https://github.com/dutdynamics/ddes/pull/123'}


class ManagerServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.root = Path(self.temporary.name)
        (self.root / 'manager.html').write_text('<!doctype html><title>Editor</title>', encoding='utf-8')
        (self.root / '.private.json').write_text('{"private":"hidden"}', encoding='utf-8')
        (self.root / 'secret.py').write_text('private code', encoding='utf-8')
        (self.root / 'start-manager.cmd').write_text('@echo off', encoding='utf-8')
        tomorrow = (datetime.now(DALIAN) + timedelta(days=1)).date().isoformat()
        self.event = {'id': 'event-test', 'date': tomorrow, 'speakerName': 'Test speaker',
                      'title': 'TBA', 'abstract': 'TBA', 'place': 'Room 114',
                      'experiences': [], 'interests': []}
        self.store = FakeStore(self.event)
        self.pdf_calls = []

        def pdf_builder(event, output):
            self.pdf_calls.append(deepcopy(event))
            output.write_bytes(b'%PDF-1.7 local test')
            return output

        self.app = ManagerApp(store=self.store, root=self.root, pdf_builder=pdf_builder)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.app))
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, method='GET', path='/api/events', data=None, headers=None, raw=None):
        values = {'Host': f'127.0.0.1:{self.port}'}
        if method == 'POST':
            values.update({'Origin': f'http://127.0.0.1:{self.port}',
                           'X-DDES-Nonce': self.app.nonce,
                           'Content-Type': 'application/json'})
            if raw is None:
                raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
        for key, value in (headers or {}).items():
            if value is None:
                values.pop(key, None)
            else:
                values[key] = value
        connection = HTTPConnection('127.0.0.1', self.port, timeout=4)
        try:
            connection.request(method, path, body=raw, headers=values)
            response = connection.getresponse()
            body = response.read()
            return response.status, dict(response.getheaders()), body
        finally:
            connection.close()

    def test_static_page_and_security_headers(self):
        status, headers, body = self.request(path='/')
        self.assertEqual(status, 200)
        self.assertIn(b'Editor', body)
        self.assertEqual(headers['X-Frame-Options'], 'DENY')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(headers['Cross-Origin-Resource-Policy'], 'same-origin')
        self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_host_rebinding_and_alternate_localhost(self):
        for host in ('evil.example', f'evil.example:{self.port}', '127.0.0.1:1', f'127.0.0.1:{self.port}.evil'):
            with self.subTest(host=host):
                self.assertEqual(self.request(headers={'Host': host})[0], 403)
        self.assertEqual(self.store.snapshot_calls, 0)
        self.assertEqual(self.request(headers={'Host': f'localhost:{self.port}'})[0], 200)

    def test_status_does_not_expose_credentials_and_checks_compiler_fallback(self):
        with patch('manager_server.shutil.which', return_value=None), \
                patch('report_builder.WINDOWS_COMPILER', SimpleNamespace(is_file=lambda: True)):
            status, _, body = self.request(path='/api/status')
        values = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(values['xelatex'])
        self.assertFalse(values['github'])
        self.assertEqual(values['nonce'], self.app.nonce)
        self.assertEqual(set(values), {'service', 'local', 'github', 'xelatex', 'nonce'})
        with patch('manager_server.shutil.which', return_value=None), \
                patch('manager_server.find_compiler', side_effect=ReportError('Missing compiler')):
            self.assertFalse(self.app.status()['xelatex'])

    def test_status_checks_auth_without_returning_process_output(self):
        with patch('manager_server.shutil.which', return_value='gh'), \
                patch('manager_server.find_compiler', return_value='xelatex'), \
                patch('manager_server.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=b'sensitive', stderr=b'sensitive')):
            values = self.app.status()
        self.assertTrue(values['github'])
        self.assertNotIn('sensitive', json.dumps(values))

    def test_post_requires_same_origin_host_and_nonce(self):
        failures = ({'Origin': None}, {'Origin': 'null'}, {'Origin': 'https://evil.example'},
                    {'Origin': f'http://127.0.0.1:{self.port + 1}'},
                    {'X-DDES-Nonce': None}, {'X-DDES-Nonce': 'wrong'},
                    {'X-DDES-Nonce': 'é'}, {'Host': f'evil.example:{self.port}'})
        for headers in failures:
            with self.subTest(headers=list(headers)):
                # Authentication must reject before reading/validating any body.
                self.assertEqual(self.request('POST', '/api/report', headers=headers, raw=b'')[0], 403)
        self.assertEqual(self.pdf_calls, [])
        self.assertEqual(self.store.publish_calls, [])

    def test_localhost_origin_is_accepted(self):
        headers = {'Host': f'localhost:{self.port}', 'Origin': f'http://localhost:{self.port}'}
        self.assertEqual(self.request('POST', '/api/report', {'event': self.event}, headers)[0], 200)

    def test_body_size_content_type_and_invalid_json(self):
        for length in ('0', '-1', str(MAX_BODY + 1)):
            self.assertEqual(self.request('POST', '/api/report', headers={'Content-Length': length}, raw=b'')[0], 413)
        self.assertEqual(self.request('POST', '/api/report', headers={'Content-Length': 'invalid'}, raw=b'')[0], 400)
        self.assertEqual(self.request('POST', '/api/report', headers={'Content-Type': 'text/plain'}, raw=b'')[0], 415)
        for raw in (b'{ invalid', b'[]', b'null', b'\xff'):
            self.assertEqual(self.request('POST', '/api/report', raw=raw)[0], 400)
        self.assertEqual(self.pdf_calls, [])

    def test_private_paths_and_traversal_are_blocked(self):
        for path in ('/.private.json', '/secret.py', '/.git/config', '/../manager.html',
                     '/%2e%2e/manager.html', '/%2e%2e%5cmanager.html', '/C:/Windows/win.ini'):
            with self.subTest(path=path):
                status, _, body = self.request(path=path)
                self.assertIn(status, (403, 404))
                self.assertNotIn(b'private code', body)
        self.assertEqual(self.request(path='/api/unknown')[0], 404)

    def test_starter_download_is_a_file_not_executable_content(self):
        status, headers, body = self.request(path='/start-manager.cmd')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'application/octet-stream')
        self.assertEqual(body, b'@echo off')

    def test_pdf_generation_is_private_and_has_download_headers(self):
        status, headers, body = self.request('POST', '/api/report', {'event': self.event})
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'application/pdf')
        self.assertIn(self.event['date'], headers['Content-Disposition'])
        self.assertEqual(body, b'%PDF-1.7 local test')
        self.assertEqual(len(self.pdf_calls), 1)
        self.assertEqual(self.store.publish_calls, [])

    def test_pdf_rejects_started_reports_and_bad_compiler_output(self):
        started = dict(self.event, date=(datetime.now(DALIAN) - timedelta(days=1)).date().isoformat())
        self.assertEqual(self.request('POST', '/api/report', {'event': started})[0], 400)
        self.assertEqual(self.pdf_calls, [])

        def invalid_pdf(event, output):
            output.write_bytes(b'Not a PDF')
            return output

        self.app.pdf_builder = invalid_pdf
        self.assertEqual(self.request('POST', '/api/report', {'event': self.event})[0], 400)
        self.assertEqual(self.store.publish_calls, [])

    def test_publish_requires_explicit_public_confirmation(self):
        for confirmation in (None, False, 'true', 1):
            status, _, _ = self.request('POST', '/api/publish', {'events': [self.event],
                                                               'revision': '1' * 40,
                                                               'confirmPublic': confirmation})
            self.assertEqual(status, 400)
        self.assertEqual(self.store.publish_calls, [])
        self.assertEqual(self.pdf_calls, [])

    def test_publish_has_no_pdf_generation_or_attachment(self):
        second = dict(self.event, id='event-other', speakerName='Other speaker')
        payload = {'events': [self.event, second], 'revision': '1' * 40,
                   'confirmPublic': True}
        status, _, body = self.request('POST', '/api/publish', payload)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['status'], 'merged')
        self.assertEqual(self.pdf_calls, [])
        self.assertEqual(self.store.publish_calls[0][2], {})

    def test_legacy_pdf_upload_requests_cannot_write(self):
        base = {'events': [self.event], 'revision': '1' * 40, 'confirmPublic': True}
        for change in ({'pdfEventId': self.event['id']}, {'pdfPaths': {'file': 'data'}}, {'pdf_paths': {'file': 'data'}}):
            self.assertEqual(self.request('POST', '/api/publish', dict(base, **change))[0], 400)
        self.assertEqual(self.store.publish_calls, [])
        self.assertEqual(self.pdf_calls, [])

    def test_invalid_publish_selection_or_event_count_cannot_write(self):
        base = {'events': [self.event], 'revision': '1' * 40, 'confirmPublic': True}
        for change in ({'pdfEventId': 'unknown'}, {'events': []}, {'events': [self.event] * 201},
                       {'events': 'not a list'}):
            self.assertEqual(self.request('POST', '/api/publish', dict(base, **change))[0], 400)
        self.assertEqual(self.store.publish_calls, [])

    def test_unknown_post_route_is_not_published(self):
        self.assertEqual(self.request('POST', '/api/not-a-route', {})[0], 404)
        self.assertEqual(self.store.publish_calls, [])

    def test_cross_origin_preflight_receives_no_access_permission(self):
        status, headers, _ = self.request('OPTIONS', '/api/publish', headers={
            'Origin': 'https://evil.example', 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'X-DDES-Nonce'})
        self.assertEqual(status, 501)
        self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_storage_conflict_and_timeout_return_errors_and_release_lock(self):
        payload = {'events': [self.event], 'revision': '1' * 40, 'confirmPublic': True}
        with patch.object(self.store, 'publish', side_effect=ValueError('The website changed.')):
            status, _, body = self.request('POST', '/api/publish', payload)
        self.assertEqual(status, 400)
        self.assertIn('website changed', json.loads(body)['error'])
        self.assertFalse(self.app.lock.locked())
        import subprocess
        with patch.object(self.store, 'publish', side_effect=subprocess.TimeoutExpired('gh', 120)):
            self.assertEqual(self.request('POST', '/api/publish', payload)[0], 504)
        self.assertFalse(self.app.lock.locked())
        self.assertEqual(self.store.publish_calls, [])

    def test_pdf_error_releases_operation_lock(self):
        def unavailable(event, output):
            raise ReportError('Unsupported formula.')

        self.app.pdf_builder = unavailable
        self.assertEqual(self.request('POST', '/api/report', {'event': self.event})[0], 400)
        self.assertEqual(self.request()[0], 200)
        self.assertFalse(self.app.lock.locked())
    def test_concurrent_operation_is_rejected_then_recovers(self):
        entered, release = threading.Event(), threading.Event()
        original = self.store.snapshot

        def slow_snapshot():
            entered.set()
            if not release.wait(3):
                raise RuntimeError('Test request did not release.')
            return original()

        self.store.snapshot = slow_snapshot
        first_result = []
        first = threading.Thread(target=lambda: first_result.append(self.request()), daemon=True)
        first.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.request()[0], 400)
            self.assertEqual(self.request('POST', '/api/report', {'event': self.event})[0], 400)
        finally:
            release.set()
            first.join(timeout=3)
        self.assertEqual(first_result[0][0], 200)
        self.store.snapshot = original
        self.assertEqual(self.request()[0], 200)
        self.assertFalse(self.app.lock.locked())


class ManagerStartupTests(unittest.TestCase):
    def test_command_line_service_binds_only_loopback(self):
        with patch('sys.argv', ['manager_server.py', '--port', '9123']), \
                patch('manager_server.ManagerApp'), \
                patch('manager_server.ThreadingHTTPServer') as server_type, \
                patch('builtins.print'):
            main()
        self.assertEqual(server_type.call_args.args[0], ('127.0.0.1', 9123))
        server_type.return_value.__enter__.return_value.serve_forever.assert_called_once()

    def test_invalid_or_privileged_ports_are_rejected_before_binding(self):
        for port in ('80', '65536', '-1'):
            with self.subTest(port=port), patch('sys.argv', ['manager_server.py', '--port', port]), \
                    patch('sys.stderr', io.StringIO()), \
                    patch('manager_server.ThreadingHTTPServer') as server_type:
                with self.assertRaises(SystemExit):
                    main()
                server_type.assert_not_called()


if __name__ == '__main__':
    unittest.main()
