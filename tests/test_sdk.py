"""Exercise SDK preparation and artifact boundaries without a real toolchain."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_sdk
import fetch_sdk


class SdkBuildTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.sdk = self.base / "sdk"
        self.output = self.base / "output"
        for name in ("rules.mk", "Makefile", "scripts/config/Makefile", "feeds/luci/luci.mk", "package/feeds/packages/adblock-fast/Makefile", "package/feeds/luci/luci-base/Makefile"):
            path = self.sdk / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture")
        (self.sdk / ".config").write_text('CONFIG_TARGET_BOARD="x86"\nCONFIG_TARGET_SUBTARGET="64"\nCONFIG_TARGET_ARCH_PACKAGES="x86_64"\n')

    def sdk_digest(self, release="25.12.5", target="x86/64", firmware="openwrt"):
        filename, digest = fetch_sdk.sdk_pin(release, target, firmware)
        (self.sdk / "adzero-sdk-origin.json").write_text(json.dumps({
            "firmware": firmware, "release": release, "target": target,
            "url": (f"{fetch_sdk.SDK_MIRRORS[firmware]}/releases/{release}"
                    f"/targets/{target}/{filename}"),
            "sha256": digest, "sdk": str(self.sdk.resolve()),
        }))
        return digest

    def compile(self, package_format):
        path = self.sdk / "bin/packages/x86_64/local" / ("luci-app-adzero_" + build_sdk.version() + "_all." + package_format)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"mock-sdk-package-" + package_format.encode())
        return path

    def test_prepare_preserves_other_packages_and_is_repeatable(self):
        other = self.sdk / "package/other"
        other.mkdir()
        (other / "keep").write_text("keep")
        first = build_sdk.prepare(self.sdk)
        self.assertEqual(first, build_sdk.prepare(self.sdk))
        self.assertEqual((other / "keep").read_text(), "keep")
        for name in ("ctl", "probe"):
            self.assertEqual((first / "root/usr/libexec/adzero" / name).stat().st_mode & 0o777, 0o755)
        for name in ("root/etc/config/adzero", "root/usr/libexec/adzero/rules.sh", "htdocs/luci-static/resources/view/adzero/overview.js"):
            self.assertEqual((first / name).stat().st_mode & 0o777, 0o644)

    def test_different_existing_sources_are_not_overwritten(self):
        destination = build_sdk.prepare(self.sdk)
        (destination / "Makefile").write_text("user changes")
        with self.assertRaisesRegex(ValueError, "different AdZero"):
            build_sdk.prepare(self.sdk)
        self.assertEqual((destination / "Makefile").read_text(), "user changes")

    def test_missing_feed_is_not_silently_replaced(self):
        (self.sdk / "feeds/luci/luci.mk").unlink()
        with self.assertRaisesRegex(ValueError, "matching feeds"):
            build_sdk.prepare(self.sdk)

    def test_ipk_and_apk_build_paths_and_provenance(self):
        for package_format in ("ipk", "apk"):
            with self.subTest(package_format=package_format):
                if package_format == "apk":
                    with (self.sdk / ".config").open("a") as stream:
                        stream.write("CONFIG_USE_APK=y\n")
                release = "24.10.8" if package_format == "ipk" else "25.12.5"
                digest = self.sdk_digest(release)
                artifact = self.compile(package_format)
                output = self.output / package_format
                with mock.patch.object(build_sdk.subprocess, "run") as run:
                    report = build_sdk.build(self.sdk, "openwrt", release, "x86/64", package_format, digest, output)
                self.assertEqual(run.call_count, 3)
                self.assertIn("CONFIG_PACKAGE_luci-app-adzero=m", (self.sdk / ".config").read_text())
                self.assertTrue(all(call.kwargs["check"] for call in run.call_args_list))
                self.assertEqual((output / artifact.name).read_bytes(), artifact.read_bytes())
                self.assertEqual(report["sha256"], hashlib.sha256(artifact.read_bytes()).hexdigest())
                self.assertEqual(report["package_arch_observed"], "x86_64")
                self.assertEqual(report["device_acceptance"], "not_run")
                self.assertEqual(json.loads((output / "build-manifest.json").read_text()), report)

    def test_incorrect_package_format_is_rejected(self):
        (self.sdk / ".config").write_text("CONFIG_USE_APK=y\n")
        with mock.patch.object(build_sdk.subprocess, "run"):
            with self.assertRaisesRegex(ValueError, "package format"):
                build_sdk.build(self.sdk, "openwrt", "25.12.5", "x86/64", "ipk", self.sdk_digest(), self.output)

    def test_missing_real_output_cannot_be_reported_as_passed(self):
        with mock.patch.object(build_sdk.subprocess, "run"):
            with self.assertRaisesRegex(ValueError, "Expected one"):
                build_sdk.build(self.sdk, "openwrt", "25.12.5", "x86/64", "ipk", self.sdk_digest(), self.output)

    def test_old_sdk_outputs_are_preserved_but_not_selected(self):
        current = self.compile("apk")
        old = current.with_name("luci-app-adzero-0.5.0-r1.apk")
        old.write_bytes(b"old-package")
        with mock.patch.object(build_sdk.subprocess, "run"):
            report = build_sdk.build(self.sdk, "openwrt", "25.12.5", "x86/64", "apk", self.sdk_digest(), self.output)
        self.assertEqual(report["package"], current.name)
        self.assertEqual(old.read_bytes(), b"old-package")

    def test_arm64_abi_drift_never_produces_a_verified_candidate(self):
        (self.sdk / '.config').write_text(
            'CONFIG_TARGET_BOARD="mediatek"\n'
            'CONFIG_TARGET_SUBTARGET="filogic"\n'
            'CONFIG_TARGET_ARCH_PACKAGES="aarch64_generic"\n'
            'CONFIG_USE_APK=y\n'
        )
        digest = self.sdk_digest('25.12.6', 'mediatek/filogic')
        with mock.patch.object(build_sdk.subprocess, 'run'):
            with self.assertRaisesRegex(ValueError, 'SDK package architecture'):
                build_sdk.build(self.sdk, 'openwrt', '25.12.6',
                                'mediatek/filogic', 'apk', digest, self.output)
        self.assertFalse((self.output / 'build-manifest.json').exists())

    def test_archive_checksum_is_required(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            build_sdk.build(self.sdk, "openwrt", "24.10.8", "x86/64", "ipk", "", self.output)

    def test_unpinned_or_cross_vendor_sdk_is_rejected_before_prepare(self):
        self.assertFalse((self.sdk / "package/luci-app-adzero").exists())
        with self.assertRaisesRegex(ValueError, "origin metadata missing"):
            build_sdk.build(self.sdk, "openwrt", "25.12.5", "x86/64", "apk",
                            fetch_sdk.sdk_pin("25.12.5")[1], self.output)
        digest = self.sdk_digest("25.12.5")
        with self.assertRaisesRegex(ValueError, "SDK vendor, firmware"):
            build_sdk.build(self.sdk, "immortalwrt", "25.12.2", "x86/64", "apk",
                            fetch_sdk.sdk_pin("25.12.2", "x86/64", "immortalwrt")[1], self.output)
        with self.assertRaisesRegex(ValueError, "SDK vendor, firmware"):
            build_sdk.build(self.sdk, "openwrt", "25.12.5", "x86/64", "apk",
                            "0" * 64, self.output)
        self.assertFalse((self.sdk / "package/luci-app-adzero").exists())
        self.assertEqual(self.sdk_digest("25.12.5"), digest)

    def test_matrix_is_an_explicit_candidate_list(self):
        matrix = json.loads((ROOT / "docs/compatibility-matrix.json").read_text())
        self.assertEqual({v["id"] for v in matrix["firmware"]}, {"openwrt", "immortalwrt", "istoreos"})
        self.assertIn("25.12.5", matrix["firmware"][0]["releases"])
        self.assertIn("mipsel", matrix["architectures"])
        self.assertIn("nikki", matrix["plugins"])
        self.assertEqual(matrix["status"], "candidates_not_device_certified")
