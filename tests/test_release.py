"""Release selection boundaries, with fake SDK output contents."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_release
import fetch_sdk


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "release"

    def manifest(self, target="rockchip/armv8", arch="aarch64_generic"):
        package = self.root / ("luci-app-adzero-" + build_release.version() + ".apk")
        package.write_bytes(b"mock-SDK-output")
        report = {"sdk_build":"passed", "source_sha256":"current", "firmware_declared":"openwrt",
                  "target_observed":target, "package_arch_observed":arch, "release_declared":"25.12.5",
                  "package_format":"apk", "package":package.name,
                  "sha256":hashlib.sha256(package.read_bytes()).hexdigest()}
        manifest = self.root / "build-manifest.json"
        manifest.write_text(json.dumps(report))
        return manifest

    def test_verified_arm_build_gets_distinct_target_and_sdk_arch_row(self):
        with mock.patch.object(build_release, "source_hash", return_value="current"):
            build_release.bundle([self.manifest()], self.output)
        rows = (self.output / "releases.tsv").read_text()
        self.assertIn("rockchip-armv8-aarch64_generic.apk", rows)
        self.assertIn("rockchip/armv8\taarch64_generic\tapk", rows)
        release = build_release.version().rsplit('-r', 1)[0]
        self.assertTrue((self.root / f"adzero-{release}-install.tar.gz").exists())

    def test_x86_output_cannot_be_relabelled_as_arm(self):
        with mock.patch.object(build_release, "source_hash", return_value="current"):
            with self.assertRaisesRegex(ValueError, "supported build matrix"):
                build_release.bundle([self.manifest(arch="x86_64")], self.output)
        self.assertFalse((self.output / "releases.tsv").exists())

    def test_unknown_target_has_no_release_row(self):
        with mock.patch.object(build_release, "source_hash", return_value="current"):
            with self.assertRaisesRegex(ValueError, "supported build matrix"):
                build_release.bundle([self.manifest(target="mediatek/filogic")], self.output)

    def test_pinned_rockchip_sdk_and_unsupported_combinations(self):
        name, sha = fetch_sdk.sdk_pin("25.12.5", "rockchip/armv8")
        self.assertIn("rockchip-armv8", name)
        self.assertEqual(sha, "59194a023968398af64bfa7d8bc3eac322641f6dc9cdbade28a4d9dd41866eba")
        with self.assertRaisesRegex(ValueError, "No pinned SDK"):
            fetch_sdk.sdk_pin("24.10.8", "rockchip/armv8")
