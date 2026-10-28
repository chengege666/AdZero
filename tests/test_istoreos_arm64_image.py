"""Original ARM64 firmware image check fixtures; never touches real routers."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import inspect_istoreos_arm64_image as check
from probe_istoreos_arm64 import PROFILES


class OriginalArm64FirmwareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.image = Path(self.tmp.name) / "original.img"
        self.image.write_bytes(b"example-original-image")
        self.pinned = {"bytes": self.image.stat().st_size,
                       "sha256": hashlib.sha256(self.image.read_bytes()).hexdigest(),
                       "squashfs_offset": 2048}

    def fake_run(self, profile, *, corrupt=None):
        spec = PROFILES[profile]
        release = {
            "DISTRIB_ID": "iStoreOS",
            "DISTRIB_RELEASE": "25.12.6",
            "DISTRIB_REVISION": "2026102312",
            "DISTRIB_TARGET": spec["target"],
            "DISTRIB_ARCH": spec["arch"],
        }
        if corrupt in release:
            release[corrupt] = "wrong"
        installed = ["luci-base", "rpcd", "tcpdump"] + [f"lib-test-{n}" for n in range(280)]
        if corrupt == "missing-tcpdump":
            installed.remove("tcpdump")
        if corrupt == "duplicate-package":
            installed.append("rpcd")
        def reader(args):
            self.assertEqual(args[:4], ["unsquashfs", "-offset", "2048", "-cat"])
            if args[-1] == "etc/openwrt_release":
                return ("".join(f"{k}='{v}'\n" for k, v in release.items())).encode()
            self.assertEqual(args[-1], "lib/apk/db/installed")
            return ("".join(f"P:{name}\nV:1.0\n\n" for name in installed)).encode()
        return reader

    def test_both_vendor_profiles_require_exact_identity(self):
        for profile in ("armsr", "rockchip-r6xs"):
            with self.subTest(profile=profile):
                with mock.patch.dict(check.RAW_IMAGES, {profile: self.pinned}):
                    names, evidence = check.inspect_image(
                        self.image, profile, run=self.fake_run(profile))
                self.assertEqual(evidence["target"], PROFILES[profile]["target"])
                self.assertEqual(evidence["arch"], "aarch64_generic")
                self.assertEqual(evidence["revision"], "2026102312")
                self.assertEqual(evidence["original_preinstalled_package_count"], 283)
                self.assertTrue(evidence["preinstalled_tcpdump_full"])
                self.assertFalse(evidence["publishable"])
                self.assertEqual(evidence["device_acceptance"], "not_run")
                self.assertIn("rpcd", names)

    def test_wrong_bytes_and_symlinks_are_rejected_before_reading(self):
        with mock.patch.dict(check.RAW_IMAGES, {"armsr": self.pinned}):
            self.image.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "SHA-256/length"):
                check.inspect_image(self.image, "armsr", run=lambda _: None)
            self.image.write_bytes(b"example-original-image")
            alias = self.image.parent / "symlink.img"
            alias.symlink_to(self.image)
            with self.assertRaisesRegex(ValueError, "symlink"):
                check.inspect_image(alias, "armsr", run=lambda _: None)

    def test_target_revision_and_package_database_must_match(self):
        with mock.patch.dict(check.RAW_IMAGES, {"rockchip-r6xs": self.pinned}):
            for corruption in ("DISTRIB_TARGET", "DISTRIB_REVISION",
                               "missing-tcpdump", "duplicate-package"):
                with self.subTest(corruption=corruption):
                    with self.assertRaisesRegex(ValueError, "differs|incomplete|duplicate"):
                        check.inspect_image(self.image, "rockchip-r6xs",
                            run=self.fake_run("rockchip-r6xs", corrupt=corruption))

    def test_unknown_profile_is_refused(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            check.inspect_image(self.image, "x86_64")


    def test_official_arm64_image_evidence_matches_pins(self):
        for profile, name in (("armsr", "armsr"), ("rockchip-r6xs", "r6xs")):
            with self.subTest(profile=profile):
                record = json.loads((ROOT / "docs/evidence/istoreos-25.12.6" /
                                    f"arm64-{name}-original-image.json").read_text())
                vendor, pinned = PROFILES[profile], check.RAW_IMAGES[profile]
                self.assertEqual(record["vendor_profile"], profile)
                self.assertEqual(record["release"], "25.12.6")
                self.assertEqual(record["revision"], "2026102312")
                self.assertEqual(record["target"], vendor["target"])
                self.assertEqual(record["arch"], vendor["arch"])
                self.assertEqual(record["official_image_archive"], vendor["image"])
                self.assertEqual(record["official_image_archive_sha256"], vendor["image_sha256"])
                self.assertEqual(record["verified_raw_image_sha256"], pinned["sha256"])
                self.assertEqual(record["verified_raw_image_bytes"], pinned["bytes"])
                self.assertEqual(record["squashfs_offset_bytes"], pinned["squashfs_offset"])
                self.assertGreater(record["original_preinstalled_package_count"], 900)
                self.assertTrue(record["preinstalled_tcpdump_full"])
                self.assertFalse(record["publishable"])
                self.assertEqual(record["device_acceptance"], "not_run")


if __name__ == "__main__":
    unittest.main()
