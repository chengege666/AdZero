#!/usr/bin/env python3
"""Loopback-only UI fixture. No router connections or runtime commands."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import mimetypes

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port', type=int, default=8765)
args = parser.parse_args()
routes = {
    '/': ROOT / 'scripts/ui_preview.html', '/ui_preview.js': ROOT / 'scripts/ui_preview.js',
    '/luci-static/resources/view/adzero/overview.js': ROOT / 'luci-app-adzero/htdocs/luci-static/resources/view/adzero/overview.js',
    '/luci-static/resources/view/adzero/overview.css': ROOT / 'luci-app-adzero/htdocs/luci-static/resources/view/adzero/overview.css',
}
theme = ROOT / 'artifacts/ui-preview/theme'
if theme.exists():
    for file in theme.rglob('*'):
        if file.is_file(): routes['/theme/' + file.relative_to(theme).as_posix()] = file

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        file = routes.get(self.path.split('?')[0])
        if file is None:
            if self.path == '/theme/css/cascade.css':
                self.send_response(200)
                self.send_header('Content-Type', 'text/css')
                self.end_headers()
                self.wfile.write(b'/* Optional host theme was not supplied. */')
                return
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', mimetypes.guess_type(file)[0] or 'application/octet-stream')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(file.read_bytes())

print(f'AdZero fixture preview: http://127.0.0.1:{args.port} (no router access)', flush=True)
ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
