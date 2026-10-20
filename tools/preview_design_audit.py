"""Current-file UI preview with labeled fixtures; no DB, models or provider calls."""
import json
import mimetypes
import time
from urllib.parse import urlsplit

from .preview_frontend import Handler, ROOT, ThreadingHTTPServer


class AuditHandler(Handler):
    def send_json(self, value, status=200):
        try:
            return super().send_json(value, status)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # Cancelling a slow fixture intentionally disconnects its client.
            pass

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ('/reader', '/reader/'):
            file = ROOT / 'reader_web/index.html'
        elif path.startswith('/reader-assets/'):
            file = ROOT / 'reader_web' / path.removeprefix('/reader-assets/')
        elif path == '/admin/':
            file = ROOT / 'admin_web/index.html'
        elif path in ('/admin.css', '/admin.js', '/resources.js', '/ai-settings.js'):
            file = ROOT / 'admin_web' / path.lstrip('/')
        elif path == '/api/ai/status':
            return self.send_json({'enabled': True, 'message': '离线审核样本，无模型连接', 'history_retention_seconds': 3600})
        elif path.startswith('/api/admin/'):
            return self.send_json({'detail': '离线审核，不连接管理数据'}, 401)
        else:
            return super().do_GET()
        if not file.resolve().is_relative_to(ROOT.resolve()) or not file.is_file():
            return self.send_json({}, 404)
        self.send_response(200)
        self.send_header('Content-Type', mimetypes.guess_type(file)[0] or 'application/octet-stream')
        self.end_headers()
        self.wfile.write(file.read_bytes())

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or '{}')
        path = urlsplit(self.path).path
        if path == '/api/reader/analyze':
            return self.send_json({'detail': '离线审核样本：主题识别暂不可用，请直接检索。'}, 503)
        if path == '/api/reader/search':
            query = data.get('query', '')
            if 'slow' in query:
                time.sleep(5)
            return self.send_json({'query': query, 'papers': [],
                                   'sources': [{'source': '离线审核样本', 'state': 'ok', 'count': 0}],
                                   'links': [{'name': 'NASA 原站检索', 'url': 'https://ntrs.nasa.gov/search'}]})
        if path == '/api/ai/conversations':
            return self.send_json({'conversation_id': 'offline-design-audit'})
        if path == '/api/ai/ask':
            return self.send_json({'answer': '这是离线审核样本，不是真实模型回答。', 'sources': [], 'remaining_rounds': 2})
        return self.send_json({}, 404)

    def do_DELETE(self):
        if self.path == '/api/ai/conversations/offline-design-audit':
            self.send_response(204)
            self.end_headers()
            return
        self.send_json({}, 404)


if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', 8097), AuditHandler)
    print('Offline design audit: http://127.0.0.1:8097 (fixtures only; Ctrl+C stops)', flush=True)
    server.serve_forever()
