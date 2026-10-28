"""Safety of iStoreOS firmware provenance discovery, not fake SDK certification."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import probe_istoreos as probe


class IstoreSourceProbeTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            "commit.buildinfo": (probe.SOURCE_COMMIT[:10] + "\n").encode(),
            "config.buildinfo": b'CONFIG_VERSION_DIST="iStoreOS"\n',
            "feeds.buildinfo": (
                b'src-git packages https://example.invalid/packages^abc\n'
                b'src-git luci https://example.invalid/luci^def\n'),
            "feeds.conf": b"src-include defaults feeds.conf.default\n",
            "version.latest.v2": f"[{probe.IMAGE_FILENAME}]({probe.IMAGE_FILENAME})\n".encode(),
        }
        self.hashes = {key: hashlib.sha256(value).hexdigest()
                       for key, value in self.data.items()}

    def validate(self):
        with mock.patch.dict(probe.METADATA_SHA256, self.hashes, clear=True):
            return probe.validate_metadata(
                lambda url: self.data[url.removeprefix(probe.ORIGIN)])

    def test_exact_vendor_source_report_cannot_be_published(self):
        result = self.validate()
        self.assertEqual(result["firmware"], "istoreos")
        self.assertEqual(result["source_commit"], probe.SOURCE_COMMIT)
        self.assertEqual(result["sdk_build"], "not_run")
        self.assertFalse(result["publishable"])
        self.assertIn("vendor_sdk", result["package_format"])

    def test_modified_metadata_fails_closed(self):
        for name in self.data:
            with self.subTest(name=name):
                original = self.data[name]
                self.data[name] = original + b"# changed\n"
                with self.assertRaisesRegex(ValueError, "vendor metadata changed"):
                    self.validate()
                self.data[name] = original

    def test_invalid_vendor_commit_is_rejected(self):
        self.data["commit.buildinfo"] = b"0000000000\n"
        self.hashes["commit.buildinfo"] = hashlib.sha256(
            self.data["commit.buildinfo"]).hexdigest()
        with self.assertRaisesRegex(ValueError, "source commit differs"):
            self.validate()

    def test_incorrect_vendor_identity_is_rejected(self):
        self.data["config.buildinfo"] = b'CONFIG_VERSION_DIST="OpenWrt"\n'
        self.hashes["config.buildinfo"] = hashlib.sha256(
            self.data["config.buildinfo"]).hexdigest()
        with self.assertRaisesRegex(ValueError, "wrong CONFIG_VERSION_DIST"):
            self.validate()

    def test_disallow_unexpected_vendor_urls(self):
        for url in ("https://example.com/file",
                    probe.ORIGIN + "../../secret",
                    probe.ORIGIN + "unlisted-file"):
            with self.subTest(url=url):
                with self.assertRaisesRegex(ValueError, "Unexpected vendor metadata"):
                    probe.read_remote(url)

    def test_unbounded_or_empty_response_is_rejected(self):
        for value in (b"", b"x" * (64 * 1024 + 1), "not-bytes"):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaisesRegex(ValueError, "Invalid iStoreOS metadata"):
                    with mock.patch.dict(probe.METADATA_SHA256, self.hashes, clear=True):
                        probe.validate_metadata(lambda _url: value)


if __name__ == "__main__":
    unittest.main()
