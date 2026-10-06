"""Private local assistant for the DDES editor; uses existing gh and XeLaTeX.

Start with python scripts/manager_server.py. No credentials enter the web page.
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
import mimetypes
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import threading
from urllib.parse import unquote, urlsplit

from manager_store import Store, validate_event
from report_builder import build_pdf, ReportError, find_compiler

ROOT = Path(__file__).resolve().parents[1]
MAX_BODY = 512 * 1024


class ManagerApp:
    def __init__(self, store=None, root=ROOT, pdf_builder=build_pdf):
        self.store = store or Store()
        self.root = Path(root).resolve()
        self.pdf_builder = pdf_builder
        self.nonce = secrets.token_urlsafe(32)
        self.lock = threading.Lock()

    @contextmanager
    def operation(self):
        if not self.lock.acquire(blocking=False):
            raise ValueError('另一个操作正在进行，请稍后重试。')
        try:
            yield
        finally:
            self.lock.release()

    def status(self):
        github = False
        if shutil.which('gh'):
            try:
                github = subprocess.run(['gh', 'auth', 'status', '--hostname', 'github.com'],
                                        capture_output=True, timeout=10).returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                pass
        try:
            find_compiler()
            xelatex = True
        except ReportError:
            xelatex = False
        return {'service': 'ddes-manager', 'local': True, 'github': github,
                'xelatex': xelatex, 'nonce': self.nonce}


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never log draft content, headers, or credentials.

        def valid_host(self):
            port = self.server.server_address[1]
            return self.headers.get('Host') in (f'127.0.0.1:{port}', f'localhost:{port}')

        def headers_for(self, status, content_type, size=None):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Frame-Options', 'DENY')
            if size is not None:
                self.send_header('Content-Length', str(size))

        def json(self, status, value):
            raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.headers_for(status, 'application/json; charset=utf-8', len(raw))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if not self.valid_host():
                return self.json(403, {'error': '仅允许本机访问。'})
            route = unquote(urlsplit(self.path).path)
            try:
                if route == '/api/status':
                    return self.json(200, app.status())
                if route == '/api/events':
                    with app.operation():
                        snapshot = app.store.snapshot()
                    return self.json(200, snapshot)
                if route.startswith('/api/'):
                    return self.json(404, {'error': '接口不存在。'})
                relative = route.lstrip('/') or 'manager.html'
                if any(part.startswith('.') for part in Path(relative).parts):
                    return self.json(403, {'error': '不可访问此路径。'})
                file = (app.root / relative).resolve()
                if not file.is_relative_to(app.root) or not file.is_file():
                    return self.json(404, {'error': '文件不存在。'})
                if file.suffix.lower() not in {'.html', '.css', '.js', '.json', '.svg', '.pdf', '.tex', '.md', '.cmd', '.ps1'}:
                    return self.json(403, {'error': '不可访问此文件。'})
                raw = file.read_bytes()
                mime = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
                if file.suffix.lower() in {'.cmd', '.ps1'}:
                    mime = 'application/octet-stream'
                self.headers_for(200, mime, len(raw))
                self.end_headers()
                self.wfile.write(raw)
            except (ValueError, RuntimeError, OSError) as error:
                self.json(400, {'error': str(error)})

        def do_POST(self):
            port = self.server.server_address[1]
            origins = {f'http://127.0.0.1:{port}', f'http://localhost:{port}'}
            if (not self.valid_host() or self.headers.get('Origin') not in origins
                    or not secrets.compare_digest(self.headers.get('X-DDES-Nonce', '').encode('utf-8'), app.nonce.encode('ascii'))):
                return self.json(403, {'error': '请从本地管理页发起操作。'})
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.json(415, {'error': '仅接受 JSON 数据。'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= MAX_BODY:
                    return self.json(413, {'error': '上传数据过大或为空。'})
                data = json.loads(self.rfile.read(length).decode('utf-8'))
                if not isinstance(data, dict):
                    raise ValueError('数据必须是对象。')
                route = urlsplit(self.path).path
                if route == '/api/report':
                    event = validate_event(data.get('event'))
                    with app.operation(), tempfile.TemporaryDirectory(prefix='ddes-report-') as temp:
                        output = app.pdf_builder(event, Path(temp) / 'report.pdf')
                        raw = Path(output).read_bytes()
                    if not raw.startswith(b'%PDF-'):
                        raise ValueError('未生成有效的 PDF。')
                    self.headers_for(200, 'application/pdf', len(raw))
                    self.send_header('Content-Disposition', f'attachment; filename="DDES-Seminar-{event["date"]}.pdf"')
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if route == '/api/publish':
                    if data.get('confirmPublic') is not True:
                        raise ValueError('发布前请确认内容可以公开。')
                    if data.get('pdfEventId') or data.get('pdfPaths') or data.get('pdf_paths'):
                        raise ValueError('PDF 仅用于线下发布，不支持上传网站。')
                    with app.operation():
                        events = data.get('events')
                        if not isinstance(events, list) or not 0 < len(events) <= 200:
                            raise ValueError('报告列表无效。')
                        result = app.store.publish(events, data.get('revision'))
                    return self.json(200, result)
                return self.json(404, {'error': '接口不存在。'})
            except (ValueError, RuntimeError, OSError, ReportError, json.JSONDecodeError) as error:
                return self.json(400, {'error': str(error)})
            except subprocess.TimeoutExpired:
                return self.json(504, {'error': '操作超时，草稿已保留，请稍后重试。'})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('port must be between 1024 and 65535')
    app = ManagerApp()
    with ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(app)) as server:
        print(f'DDES manager: http://127.0.0.1:{args.port}/manager.html', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
