"""Vendor SDK trust boundaries; no network requests or router modifications."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_sdk
import build_release


class VendorSDKPinTests(unittest.TestCase):
    def test_immortalwrt_pins_are_vendor_distinct_and_exact(self):
        known = {
            ("24.10.6", "x86/64"): (
                "immortalwrt-sdk-24.10.6-x86-64_gcc-13.3.0_musl.Linux-x86_64.tar.zst",
                "709bea2ce466b7ad671ce00fdcb1eb69b2b3fa0f0921b12b620725d95cd8c0e5"
            ),
            ("25.12.2", "x86/64"): (
                "immortalwrt-sdk-25.12.2-x86-64_gcc-14.3.0_musl.Linux-x86_64.tar.zst",
                "4d4631f134c2f27215a91aa7ef5bf9a01ea96c2450d3b8a5c38048c32462ac60"
            )
        }
        self.assertEqual(fetch_sdk.IMMORTALWRT_PINS, known)
        for (release, target), expected in known.items():
            with self.subTest(release=release):
                self.assertEqual(fetch_sdk.sdk_pin(release, target, "immortalwrt"), expected)
                self.assertNotEqual(fetch_sdk.sdk_pin(release, target, "immortalwrt"),
                                    fetch_sdk.PINS.get(release))

    def test_wrong_firmware_sdk_never_falls_back_to_openwrt(self):
        for firmware, release, target in (
            ("immortalwrt", "25.12.5", "x86/64"),
            ("istoreos", "25.12.6", "x86/64"),
            ("istoreos", "24.10.8", "x86/64"),
            ("immortalwrt", "25.12.2", "rockchip/armv8"),
            ("openwrt", "24.10.6", "x86/64"),
            ("other", "25.12.2", "x86/64"),
        ):
            with self.subTest(firmware=firmware, release=release):
                with self.assertRaises(ValueError):
                    fetch_sdk.sdk_pin(release, target, firmware)

    def test_old_official_openwrt_pin_contract_is_unchanged(self):
        self.assertEqual(fetch_sdk.sdk_pin("24.10.8", "x86/64"),
                         fetch_sdk.PINS["24.10.8"])
        self.assertEqual(fetch_sdk.sdk_pin("25.12.5", "rockchip/armv8"),
                         fetch_sdk.TARGET_PINS[("25.12.5", "rockchip/armv8")])

    def test_download_source_and_manifest_provenance_come_from_selected_vendor(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            output = folder / "out"
            cache = folder / "cache"
            firmware, release = "immortalwrt", "25.12.2"
            filename, digest = fetch_sdk.sdk_pin(release, "x86/64", firmware)
            mock_binary = b"official-vendor-sdk-placeholder"
            # Exercise extraction/report without network and use the SHA from
            # the placeholder only inside the mocked pin.
            with mock.patch.object(fetch_sdk, "sdk_pin", return_value=(
                filename, hashlib.sha256(mock_binary).hexdigest()
            )), mock.patch.object(fetch_sdk.urllib.request, "urlopen") as urlopen, \
                 mock.patch.object(fetch_sdk.subprocess, "check_output") as listing, \
                 mock.patch.object(fetch_sdk.subprocess, "run") as extraction:
                source = urlopen.return_value.__enter__.return_value
                source.read.side_effect = [mock_binary, b""]
                target_name = filename.removesuffix(".tar.zst")
                listing.return_value = (target_name + "/\n").encode().decode()
                def simulate_extract(argv, **_kwargs):
                    (output / target_name).mkdir(parents=True, exist_ok=True)
                    return subprocess.CompletedProcess(argv, 0)
                extraction.side_effect = simulate_extract
                report = fetch_sdk.fetch(release, output, cache, "zstd",
                                         "x86/64", firmware)
                requested = urlopen.call_args.args[0]
                self.assertEqual(requested,
                    f"https://downloads.immortalwrt.org/releases/{release}/targets/x86/64/{filename}")
                self.assertEqual(report["firmware"], firmware)
                self.assertEqual(report["url"], requested)
                self.assertTrue((cache / filename).is_file())
                self.assertEqual(json.loads((output / target_name /
                    "adzero-sdk-origin.json").read_text()), report)

    def test_bad_sdk_hash_never_extracts_or_promotes_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            filename = "immortalwrt-sdk-25.12.2-x86-64_gcc-14.3.0_musl.Linux-x86_64.tar.zst"
            with mock.patch.object(fetch_sdk, "sdk_pin",
                      return_value=(filename, "0" * 64)), \
                 mock.patch.object(fetch_sdk.urllib.request, "urlopen") as urlopen, \
                 mock.patch.object(fetch_sdk.subprocess, "run") as run:
                urlopen.return_value.__enter__.return_value.read.side_effect = [b"tampered", b""]
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    fetch_sdk.fetch("25.12.2", root / "sdk", root / "cache",
                                    "zstd", "x86/64", "immortalwrt")
                self.assertFalse((root / "cache" / filename).exists())
                run.assert_not_called()

    def test_download_progress_is_on_stderr_not_json_stdout(self):
        # The CLI redirects stdout to a JSON file for automatic SDK location.
        # A 32 MiB progress event must never contaminate that file.
        import io
        from contextlib import redirect_stdout, redirect_stderr
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            chunk = b"p" * (32 * 1024 * 1024)
            filename = fetch_sdk.sdk_pin("24.10.6", "x86/64", "immortalwrt")[0]
            expected_hash = hashlib.sha256(chunk).hexdigest()
            topdir = filename.removesuffix(".tar.zst")
            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(fetch_sdk, "sdk_pin", return_value=(filename, expected_hash)), \
                 mock.patch.object(fetch_sdk.urllib.request, "urlopen") as urlopen, \
                 mock.patch.object(fetch_sdk.subprocess, "check_output",
                                   return_value=topdir + "/\n"), \
                 mock.patch.object(fetch_sdk.subprocess, "run") as extraction:
                urlopen.return_value.__enter__.return_value.read.side_effect = [chunk, b""]
                def unpack(*_args, **_kw):
                    (folder / "sdk" / topdir).mkdir(parents=True, exist_ok=True)
                extraction.side_effect = unpack
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    fetch_sdk.fetch("24.10.6", folder / "sdk",
                                    folder / "cache", "zstd", "x86/64", "immortalwrt")
                self.assertEqual(stdout.getvalue(), "")
                self.assertIn("downloaded 32 MiB", stderr.getvalue())

    def test_vendor_builds_are_not_prematurely_published(self):
        matrix = json.loads((ROOT / "docs/compatibility-matrix.json").read_text())
        actual = build_release.verified_builds()
        for row in matrix["sdk_verified"]:
            self.assertEqual(row["sdk_build"], "passed")
            self.assertIn((row["firmware"], row["release"],
                           row["target"], row["format"]), actual)
        for vendor in ("istoreos", "immortalwrt"):
            self.assertNotIn(vendor, {identity[0] for identity in actual},
                             "A candidate is not an SDK-verified release")


if __name__ == "__main__":
    unittest.main()
