"""Local research-workspace UI preview. Fixtures only; no provider calls or database writes."""
import argparse
from tools.preview_design_audit import AuditHandler, ThreadingHTTPServer


class ResearchHandler(AuditHandler):
    def do_GET(self):
        if self.path.split('?')[0] == '/api/ai/status':
            return self.send_json({'enabled': True, 'preview': True,
                                   'message': '离线交互预览，未连接模型', 'history_retention_seconds': 3600})
        return super().do_GET()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8098)
    args = parser.parse_args()
    print(f'Research UI preview: http://127.0.0.1:{args.port}/assets/research.html (offline fixtures)', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), ResearchHandler).serve_forever()
