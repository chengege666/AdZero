"""Private iStoreOS pilot bundles: exact original-vendor targets and no mutations."""
import hashlib
import json
import os
import shlex
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_sdk import PACKAGE, source_hash
from build_ipk import version
from probe_istoreos import SOURCE_COMMIT
from probe_istoreos_arm64 import PROFILES
from inspect_istoreos_arm64_image import RAW_IMAGES
import build_istoreos_pilot as pilot


class IstorePilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="adzero-istore-pilot-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "vendor"
        self.source.mkdir()
        self.image = self.root / "image.img"
        self.image.write_bytes(b"mock-original-firmware")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.router = self.root / "router"
        self.packages = ["adblock-fast", "conntrack", "coreutils-timeout",
                         "libnetfilter-cthelper0", "libnetfilter-cttimeout1",
                         "libnetfilter-queue1"]
        self.apk_log = self.root / "apk-operations"
        self.apk_bin = self.bin / "apk"
        self.apk_bin.write_text("""#!/bin/sh
if [ "$1" = --print-arch ]; then echo "$MOCK_APK_ARCH"; exit 0; fi
echo "$*" >> "$MOCK_APK_LOG"
for must in --simulate --no-network --allow-untrusted; do
  case " $* " in *" $must "*) ;; *) echo "unsafe APK invocation: missing $must" >&2; exit 98 ;; esac
done
echo '(1/7) Installing adblock-fast (1-r1)'
echo '(2/7) Installing conntrack (1-r1)'
echo '(3/7) Installing coreutils-timeout (1-r1)'
echo '(4/7) Installing libnetfilter-cthelper0 (1-r1)'
echo '(5/7) Installing libnetfilter-cttimeout1 (1-r1)'
echo '(6/7) Installing libnetfilter-queue1 (1-r1)'
echo '(7/7) Installing luci-app-adzero (0.21.5-r1)'
if [ -n "$MOCK_APK_EXTRA" ]; then echo '(8/8) Installing extra-device-package (1-r1)'; fi
echo 'OK: 520 MiB in 1025 packages'
""")
        self.apk_bin.chmod(0o755)

    def prepare_vendor(self, profile):
        spec = PROFILES[profile]
        arch = spec["arch"]
        folder = self.source / "bin/packages" / arch / "vendor"
        folder.mkdir(parents=True, exist_ok=True)
        app = f"luci-app-adzero-{version()}.apk"
        entries = {}
        for name in ["luci-app-adzero", *self.packages]:
            filename = app if name == "luci-app-adzero" else f"{name}-1-r1.apk"
            path = folder / filename
            path.write_bytes((name + ":" + profile + ":exact-vendor-bytes").encode())
            value = hashlib.sha256(path.read_bytes()).hexdigest()
            entries[name] = {"file": filename, "sha256": value,
                             "arch": ("noarch" if name in
                                      ("adblock-fast", "luci-app-adzero") else arch)}
        report = {
            "firmware": "istoreos", "release": "25.12.6", "revision": "2026102312",
            "vendor_profile": profile, "target": spec["target"], "arch": arch,
            "original_image_sha256": RAW_IMAGES[profile]["sha256"],
            "native_source_sha256": source_hash(PACKAGE),
            "vendor_source_commit": SOURCE_COMMIT, "offline_solver": "passed_no_network",
            "original_db_unchanged": True, "original_full_tcpdump_preserved": True,
            "existing_firmware_package_removals": 0,
            "device_acceptance": "not_run", "publishable": False,
            "native_apk_sha256": entries["luci-app-adzero"]["sha256"],
            "missing_vendor_dependencies": {name: entries[name] for name in self.packages},
            "packages_simulated": 7,
            "installed_packages_simulated": ["luci-app-adzero", *self.packages],
        }
        release = self.router / "etc/openwrt_release"
        release.parent.mkdir(parents=True, exist_ok=True)
        release.write_text(
            "DISTRIB_ID='iStoreOS'\nDISTRIB_RELEASE='25.12.6'\n"
            "DISTRIB_REVISION='2026102312'\n"
            f"DISTRIB_TARGET='{spec['target']}'\nDISTRIB_ARCH='{arch}'\n")
        db = self.router / "lib/apk/db/installed"
        db.parent.mkdir(parents=True, exist_ok=True)
        db.write_text("P:luci-base\nP:rpcd\nP:tcpdump\nP:curl\n")
        return report

    def generate(self, profile):
        report = self.prepare_vendor(profile)
        output = self.root / f"pilot-{profile}"
        result = pilot.bundle(self.source, self.image, profile, output,
                              solver=lambda _source, _image, _profile: report)
        return output, result

    def preflight(self, output, mode="--check", success=True, root=None, extra_env=None):
        env = {**os.environ, "PATH": str(self.bin) + ":" + os.environ["PATH"],
               "MOCK_APK_ARCH": "aarch64",
               "MOCK_APK_LOG": str(self.apk_log),
               "ADZERO_PILOT_ROOT": str(root or self.router)}
        env.update(extra_env or {})
        shell = shlex.split(os.environ.get("ADZERO_TEST_SHELL", "sh"))
        check = subprocess.run(shell + [str(output / "preflight.sh"), mode],
                               env=env, text=True, capture_output=True, timeout=18)
        self.assertEqual(check.returncode == 0, success, check.stdout + check.stderr)
        return check

    def test_both_native_vendor_profiles_produce_distinct_protected_archives(self):
        outputs = {}
        for profile in ("armsr", "rockchip-r6xs"):
            with self.subTest(profile=profile):
                output, result = self.generate(profile)
                self.assertEqual(result["package_count"], 7)
                self.assertFalse(result["public_release"])
                self.assertFalse(result["installation_enabled"])
                self.assertTrue((output / "SHA256SUMS").is_file())
                self.assertFalse((output / "install.sh").exists())
                self.assertFalse((output / "releases.tsv").exists())
                meta = json.loads((output / "pilot-manifest.json").read_text())
                self.assertEqual(meta["target"], PROFILES[profile]["target"])
                self.assertEqual(meta["vendor_profile"], profile)
                self.assertFalse(meta["publishable"])
                self.assertEqual(meta["device_acceptance"], "not_run")
                self.assertEqual(len(meta["packages"]), 7)
                self.assertEqual(len(list((output / "packages").glob("*.apk"))), 7)
                with zipfile.ZipFile(result["archive"]) as archive:
                    names = archive.namelist()
                    self.assertEqual(len(names), 12)
                    self.assertTrue(all(n.startswith(output.name + "/") for n in names))
                    self.assertFalse(any(n.endswith("releases.tsv") for n in names))
                self.preflight(output)
                self.assertFalse(self.apk_log.exists())
                self.preflight(output, "--solver")
                self.assertIn("--simulate", self.apk_log.read_text())
                self.apk_log.unlink()
                outputs[profile] = result["archive_sha256"]
        self.assertNotEqual(outputs["armsr"], outputs["rockchip-r6xs"])

    def test_corrupted_package_and_wrong_revision_target_refused_without_apk(self):
        output, _ = self.generate("armsr")
        package = next((output / "packages").glob("*.apk"))
        package.write_bytes(b"tampered")
        self.preflight(output, success=False)
        self.assertFalse(self.apk_log.exists())
        # Recreate clean output for target/revision tests.
        shutil.rmtree(output)
        output.with_suffix(".zip").unlink()
        output, _ = self.generate("armsr")
        release = self.router / "etc/openwrt_release"
        original = release.read_text()
        for key, value in (("2026102312", "2026102313"), ("armsr/armv8", "rockchip/armv8"),
                           ("iStoreOS", "OpenWrt"), ("aarch64_generic", "x86_64")):
            with self.subTest(key=key):
                release.write_text(original.replace(key, value))
                self.preflight(output, success=False)
                self.assertFalse(self.apk_log.exists())
        release.write_text(original)

    def test_reject_unknown_option_unverified_file_and_existing_adzero(self):
        output, _ = self.generate("rockchip-r6xs")
        self.preflight(output, "--install", success=False)
        self.assertFalse(self.apk_log.exists())
        extra = output / "packages/injected.apk"
        extra.write_bytes(b"foreign")
        self.preflight(output, success=False)
        extra.unlink()
        db = self.router / "lib/apk/db/installed"
        db.write_text(db.read_text() + "P:luci-app-adzero\n")
        self.preflight(output, "--solver", success=False)
        self.assertFalse(self.apk_log.exists())

    def test_fail_closed_reports_and_overwrite_refusal(self):
        report = self.prepare_vendor("armsr")
        out = self.root / "candidate"
        for key, value in (
            ("revision", "2026102313"),
            ("target", "rockchip/armv8"),
            ("offline_solver", "not_run"),
            ("publishable", True),
            ("original_image_sha256", "0" * 64),
        ):
            with self.subTest(key=key):
                invalid = {**report, key: value}
                with self.assertRaises(ValueError):
                    pilot.bundle(self.source, self.image, "armsr", out,
                                 solver=lambda *_: invalid)
                self.assertFalse(out.exists())
        pilot.bundle(self.source, self.image, "armsr", out,
                     solver=lambda *_: report)
        with self.assertRaisesRegex(ValueError, "exists"):
            pilot.bundle(self.source, self.image, "armsr", out,
                         solver=lambda *_: report)
        # A source APK symlink must never be included even with a valid digest.
        new = self.root / "pilot-other"
        app = next((self.source / "bin/packages/aarch64_generic/vendor").glob("luci-app-adzero*"))
        original = app.with_suffix(".genuine")
        app.rename(original)
        app.symlink_to(original)
        with self.assertRaisesRegex(ValueError, "Missing, duplicate"):
            pilot.bundle(self.source, self.image, "armsr", new,
                         solver=lambda *_: report)


    def test_official_firmware_snapshot_evidence_keeps_pilot_non_publishable(self):
        for profile, filename, expected_count in (
            ("armsr", "armsr-readonly-pilot-snapshot.json", 1018),
            ("rockchip-r6xs", "r6xs-readonly-pilot-snapshot.json", 940),
        ):
            with self.subTest(profile=profile):
                path = ROOT / "docs/evidence/istoreos-25.12.6" / filename
                proof = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(proof["profile"], profile)
                self.assertEqual(proof["target"], PROFILES[profile]["target"])
                self.assertEqual(proof["revision"], "2026102312")
                self.assertEqual(proof["original_installed_packages_examined"], expected_count)
                self.assertEqual(proof["official_image_sha256"], RAW_IMAGES[profile]["sha256"])
                self.assertEqual(proof["preflight_checks"],
                                 {"--check": "passed", "--solver": "passed"})
                self.assertTrue(proof["original_db_snapshot"])
                self.assertTrue(proof["used_real_vendor_apk_solver"])
                self.assertFalse(proof["network_access_allowed"])
                self.assertFalse(proof["host_or_router_packages_installed"])
                self.assertEqual(proof["device_acceptance"], "not_run")
                self.assertFalse(proof["publishable"])

    def test_extra_simulated_vendor_package_is_rejected(self):
        output, _ = self.generate("armsr")
        self.preflight(output, "--solver", success=False,
                       extra_env={"MOCK_APK_EXTRA": "1"})
        self.assertIn("--simulate", self.apk_log.read_text())
        self.assertNotIn(" --upgrade ", self.apk_log.read_text())

    def test_partial_archive_symlink_must_not_be_overwritten(self):
        report = self.prepare_vendor("armsr")
        target = self.root / "new-pilot"
        malicious_part = target.with_name(target.name + ".zip.partial")
        malicious_part.symlink_to(self.image)
        with self.assertRaisesRegex(ValueError, "exists"):
            pilot.bundle(self.source, self.image, "armsr", target,
                         solver=lambda *_: report)
        self.assertEqual(self.image.read_bytes(), b"mock-original-firmware")


if __name__ == "__main__":
    unittest.main()
