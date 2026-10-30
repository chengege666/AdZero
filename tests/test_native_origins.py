"""Native origin archives remain pinned independently of mutable latest metadata."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import check_native_origins as origins


class NativeOriginChecks(unittest.TestCase):
    def test_each_profile_uses_exact_published_dependency_archives(self):
        specs = list(origins.archive_specs('all'))
        self.assertEqual(len(specs), 6)
        self.assertEqual(len({name for name, _, _ in specs}), 6)
        for profile in ('armsr', 'rockchip-r6xs', 'x86_64'):
            self.assertEqual(len(list(origins.archive_specs(profile))), 2)
        self.assertTrue(all(url.startswith('https://github.com/slobys/AdZero/releases/download/') and url.endswith('/' + name) for name, _, url in specs))
        with self.assertRaises(ValueError): list(origins.archive_specs('../untrusted'))

    def test_changed_bytes_are_rejected_without_refreshing_the_pin(self):
        data = b'original'; digest = hashlib.sha256(data).hexdigest()
        origins.verify_bytes(data, digest)
        for changed in (b'', b'changed'):
            with self.assertRaises(ValueError): origins.verify_bytes(changed, digest)

    def test_cached_corruption_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d); (cache / 'archive.tar.gz').write_bytes(b'changed')
            with patch.object(origins, 'archive_specs', return_value=[('archive.tar.gz', hashlib.sha256(b'original').hexdigest(), 'https://example.invalid/archive')]):
                with patch.object(origins, 'urlopen') as fetch:
                    with self.assertRaises(ValueError): origins.audit('armsr', cache)
                    fetch.assert_not_called()
