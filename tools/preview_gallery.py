"""Local-only static preview. API fixtures never contact models or production."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import json

WEB = Path(__file__).resolve().parents[1] / 'web'

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def do_GET(self):
        if self.path.startswith('/api/'):
            payload = {'enabled': False, 'available': False, 'message': '本地预览：问答服务未连接',
                       'items': [], 'sources': [], 'categories': [], 'geographic_regions': [],
                       'total': 0, 'page': 1, 'page_size': 10, 'total_pages': 1}
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path.startswith('/assets/'):
            self.path = self.path.removeprefix('/assets')
        super().do_GET()

if __name__ == '__main__':
    print('Local fixture preview: http://127.0.0.1:8876', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8876), Handler).serve_forever()
