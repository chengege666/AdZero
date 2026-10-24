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
    '/source_catalog.json': ROOT / 'artifacts/ui-preview/source_catalog.json',
    '/native-dom.js': ROOT / 'artifacts/ui-preview/native-dom.js',
    '/luci-static/resources/view/adzero/overview.js': ROOT / 'luci-app-adzero/htdocs/luci-static/resources/view/adzero/overview.js',
    '/luci-static/resources/view/adzero/overview.css': ROOT / 'luci-app-adzero/htdocs/luci-static/resources/view/adzero/overview.css',
    '/luci-static/resources/view/adzero/logo.png': ROOT / 'luci-app-adzero/htdocs/luci-static/resources/view/adzero/logo.png',
}
theme = ROOT / 'artifacts/ui-preview/theme'
if theme.exists():
    for file in theme.rglob('*'):
        if file.is_file(): routes['/theme/' + file.relative_to(theme).as_posix()] = file

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/mobile':
            page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>AdZero · 360px 手机预览</title>
<style>body{margin:0;background:#e5ebe8;font:14px system-ui;color:#243d33}header{padding:14px 20px;text-align:center}iframe{display:block;width:360px;height:1080px;border:1px solid #b8c9bf;margin:0 auto;background:#fff;border-radius:12px}</style>
<header>360px 手机视口 · 实际生产界面 · 模拟数据</header><iframe title="AdZero 手机视口" src="/"></iframe></html>'''
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers()
            self.wfile.write(page.encode('utf-8')); return
        file = routes.get(self.path.split('?')[0])
        if self.path == '/native-dom.js' and not file.exists():
            self.send_response(200)
            self.send_header('Content-Type', 'application/javascript')
            self.end_headers()
            self.wfile.write(b'/* Optional SDK LuCI DOM was not supplied; use fallback. */')
            return
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
