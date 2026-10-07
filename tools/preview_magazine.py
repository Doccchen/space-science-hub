"""Loopback magazine preview: labeled news fixtures, real catalog, no paid calls or DB writes."""
import json
import mimetypes
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit, unquote

from tools.preview_frontend import Handler, ROOT


class MagazinePreview(Handler):
    def send_bytes(self, data, content_type):
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if url.path == '/':
            html = (ROOT / 'web/index.html').read_text(encoding='utf-8')
            html = html.replace('<body class="editorial-ui">', '<body class="editorial-ui"><div style="padding:8px 20px;background:#10233f;color:#f3f1ea;font-size:12px;text-align:center">本地正式前端预览 · 新闻为离线测试样本 · 资料来自现有目录 · 未连接百炼</div>')
            return self.send_bytes(html.encode(), 'text/html; charset=utf-8')
        if url.path == '/api/resources':
            catalog = [item for item in json.loads((ROOT / 'content/resources.json').read_text(encoding='utf-8')) if item.get('published')]
            categories = sorted({item['category'] for item in catalog})
            term = query.get('q', [''])[0].casefold()
            category = query.get('category', [''])[0]
            items = [item for item in catalog if (not category or item['category'] == category) and term in (item['title'] + ' ' + ' '.join(item['authors'])).casefold()]
            items.sort(key=lambda item: (item.get('display_order', 0), item['id']))
            size = 12
            pages = (len(items) + size - 1) // size
            try:
                page = min(max(1, int(query.get('page', ['1'])[0])), max(1, pages))
            except ValueError:
                return self.send_json({'error': 'invalid_page'}, 400)
            rows = []
            for item in items[(page - 1) * size:page * size]:
                rows.append({**item, 'cover_url': '/assets/resource-covers/' + item['cover_asset'] if item.get('cover_asset') else None,
                             'download_url': '/api/resources/' + item['id'] + '/download'})
            return self.send_json({'items': rows, 'pages': pages, 'total': len(items), 'categories': categories})
        if url.path.startswith('/api/resources/'):
            return self.send_json({'message': '请在正式网站下载资料；本地预览不连接文件存储。'}, 409)
        if url.path.startswith('/assets/'):
            target = (ROOT / 'web' / unquote(url.path.removeprefix('/assets/'))).resolve()
            if not target.is_relative_to((ROOT / 'web').resolve()) or not target.is_file():
                return self.send_json({}, 404)
            return self.send_bytes(target.read_bytes(), mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
        return super().do_GET()


if __name__ == '__main__':
    print('Magazine frontend preview: http://127.0.0.1:8096 (fixtures / real catalog / no DB writes)', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8096), MagazinePreview).serve_forever()
