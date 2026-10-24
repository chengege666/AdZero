"""Public handbook integrity and deployment boundary checks (standard library)."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SITE = REPO / 'docs/site'
spec = importlib.util.spec_from_file_location('docs_build', SITE / 'build.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class Handbook(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        builder.build(self.output)

    def test_version_and_release_match_installer(self):
        config = json.loads((SITE / 'site.json').read_text(encoding='utf-8'))
        makefile = (REPO / 'luci-app-adzero/Makefile').read_text(encoding='utf-8')
        self.assertIn('PKG_VERSION:=' + config['version'], makefile)
        self.assertEqual(config['release'], 'v' + config['version'])
        self.assertIn('/download/' + config['release'], (REPO / 'scripts/install.sh').read_text(encoding='utf-8'))
        body = (self.output / 'installation.html').read_text(encoding='utf-8')
        self.assertIn('/' + config['release'] + '/scripts/install.sh', body)
        self.assertNotIn('$release', body)

    def test_only_public_assets_and_navigation_are_published(self):
        pages = list(self.output.glob('*.html'))
        self.assertEqual(len(pages), 12)
        self.assertEqual([p.name for p in (self.output / 'assets').iterdir()], ['adzero-logo.png'])
        approved=(REPO / 'docs/images/adzero-logo.png').read_bytes()
        self.assertEqual((self.output / 'assets/adzero-logo.png').read_bytes(),approved)
        self.assertEqual((REPO / 'luci-app-adzero/htdocs/luci-static/resources/view/adzero/logo.png').read_bytes(),approved)
        for file in pages:
            body = file.read_text(encoding='utf-8')
            self.assertNotIn('NaiLink 文档', body)
            self.assertNotIn('基于 daed', body)
            self.assertNotRegex(body, r'<script[^>]+src="https?://')
            self.assertNotRegex(body, r'<link[^>]+rel="stylesheet"[^>]+href="https?://')
            self.assertIn('跳转到正文', body)
        workflow = (REPO / '.github/workflows/docs.yml').read_text(encoding='utf-8')
        self.assertIn('path: .build/docs-site', workflow)
        self.assertNotIn('path: .\n', workflow)

    def test_broken_link_and_anchor_are_rejected(self):
        file = self.output / 'index.html'
        original = file.read_text(encoding='utf-8')
        for broken in ['missing.html', 'rules.html#missing', '../README.md']:
            file.write_text(original + f'<a href="{broken}">bad</a>', encoding='utf-8')
            with self.subTest(link=broken), self.assertRaises(ValueError):
                builder.validate(self.output)

    def test_duplicate_headings_and_invalid_search_are_rejected(self):
        with self.assertRaises(ValueError):
            doc = builder.Document()
            doc.feed('<h2 id="same">A</h2><h2 id="same">B</h2>')
        (self.output / 'search-index.json').write_text('[{"url":"rules.html#missing"}]', encoding='utf-8')
        with self.assertRaises(ValueError):
            builder.validate(self.output)

    def test_chinese_search_and_404_subpath(self):
        index = json.loads((self.output / 'search-index.json').read_text(encoding='utf-8'))
        self.assertTrue(any('临时放行' in entry['text'] and entry['url'].startswith('access-control.html') for entry in index))
        body = (self.output / '404.html').read_text(encoding='utf-8')
        self.assertIn('<base href="https://slobys.github.io/AdZero/">', body)
        self.assertIn('页面未找到 · AdZero', body)
        self.assertNotIn('<aside class="toc"', body)


if __name__ == '__main__':
    unittest.main()
