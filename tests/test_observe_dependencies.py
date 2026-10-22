"""Observer fixtures must be pinned and ready before network isolation."""
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import check_observe_runtime as runtime


class ObserverDependenciesTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.data=b'pinned fixture'
        self.cache=self.root/'artifacts/runtime/observe-extras/fixture.ipk'
        for context in (patch.object(runtime,'ROOT',self.root),patch.object(runtime,'EXTRAS',{'fixture.ipk':hashlib.sha256(self.data).hexdigest()})):
            context.start();self.addCleanup(context.stop)

    def test_cold_download_happens_before_isolation_and_is_checked(self):
        with patch.object(runtime.urllib.request,'urlopen',return_value=io.BytesIO(self.data)) as fetch:
            self.assertEqual(runtime.prepare_extras(download=True),[self.cache])
            self.assertEqual(self.cache.read_bytes(),self.data);fetch.assert_called_once()

    def test_missing_inside_cache_never_uses_network(self):
        with patch.object(runtime.urllib.request,'urlopen') as fetch:
            with self.assertRaisesRegex(RuntimeError,'before network isolation'):runtime.prepare_extras(download=False)
            fetch.assert_not_called()

    def test_warm_cache_does_not_download_in_either_context(self):
        self.cache.parent.mkdir(parents=True);self.cache.write_bytes(self.data)
        with patch.object(runtime.urllib.request,'urlopen') as fetch:
            for download in (False,True):self.assertEqual(runtime.prepare_extras(download),[self.cache])
            fetch.assert_not_called()

    def test_bad_download_and_bad_cache_are_rejected(self):
        with patch.object(runtime.urllib.request,'urlopen',return_value=io.BytesIO(b'bad')):
            with self.assertRaisesRegex(ValueError,'SHA-256'):runtime.prepare_extras(download=True)
            self.assertFalse(self.cache.exists())
        self.cache.parent.mkdir(parents=True);self.cache.write_bytes(b'bad')
        with patch.object(runtime.urllib.request,'urlopen') as fetch:
            with self.assertRaisesRegex(ValueError,'SHA-256'):runtime.prepare_extras(download=False)
            fetch.assert_not_called()
