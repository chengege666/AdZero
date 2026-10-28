"""ARM64 candidate list must not authorize unverified firmware packages."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_sdk
import build_release
import probe_istoreos_arm64 as istore_arm


class Arm64MatrixTests(unittest.TestCase):
    def test_vendor_pins_are_exact_and_candidates_never_authorize_install(self):
        matrix = json.loads((ROOT / "docs/compatibility-matrix.json").read_text())
        rows = matrix["arm64_candidates"]
        self.assertEqual(len(rows), 6)
        seen = set()
        for row in rows:
            key = (row["firmware"], row["release"], row["target"], row["format"])
            with self.subTest(key=key):
                self.assertNotIn(key, seen)
                seen.add(key)
                self.assertNotIn(key, build_release.SUPPORTED_BUILDS)
                self.assertEqual(row["device_acceptance"], "not_run")
                self.assertNotEqual(row["sdk_build"], "passed")
                if row["firmware"] == "istoreos":
                    self.assertEqual(row["revision"], "2026102312")
                    profile = istore_arm.profile_spec(row["vendor_profile"])
                    self.assertEqual(profile["target"], row["target"])
                    self.assertEqual(profile["arch"], row["arch_expected"])
                else:
                    _name, digest = fetch_sdk.sdk_pin(
                        row["release"], row["target"], row["firmware"])
                    self.assertEqual(row["sdk_archive_sha256"], digest)

    def test_ci_verified_arm64_artifacts_remain_unpublished_candidates(self):
        matrix = json.loads((ROOT / "docs/compatibility-matrix.json").read_text())
        evidence = json.loads((ROOT / "docs/evidence/arm64-pr10-sdk-builds.json").read_text())
        self.assertFalse(evidence["public_release"])
        self.assertEqual(evidence["device_acceptance"], "not_run")
        self.assertEqual(evidence["head_commit"], "61e1334f6caaecb425d394e58afcb8fc44e1d4d4")
        candidates = {(row["firmware"], row["release"], row["target"]): row
                      for row in matrix["arm64_candidates"]}
        self.assertEqual(len(evidence["artifacts"]), 4)
        for item in evidence["artifacts"]:
            key = (item["firmware"], item["release"], item["target"])
            with self.subTest(key=key):
                row = candidates[key]
                self.assertEqual(row["sdk_build"], "ci_passed_unreleased")
                self.assertEqual(row["sdk_evidence"], "evidence/arm64-pr10-sdk-builds.json")
                self.assertEqual(row["sdk_archive_sha256"], item["sdk_archive_sha256"])
                self.assertEqual(row["arch_expected"], item["arch"])
                self.assertEqual(item["format"], "apk")
                self.assertEqual(item["sdk_build"], "passed")
                self.assertTrue(item["sdk_origin_verified"])
                self.assertTrue(item["artifact_package_checksum_match"])
                self.assertRegex(item["apk_sha256"], r"^[a-f0-9]{64}$")
                self.assertNotIn((*key, "apk"), build_release.SUPPORTED_BUILDS)
        self.assertEqual({row["sdk_build"] for row in matrix["arm64_candidates"]
                          if row["firmware"] == "istoreos"},
                         {"native_apk_offline_solver_passed_unreleased"})

    def test_native_istoreos_arm64_solver_evidence_is_target_pinned_and_not_a_release(self):
        matrix = json.loads((ROOT / "docs/compatibility-matrix.json").read_text())
        vendor = [row for row in matrix["arm64_candidates"] if row["firmware"] == "istoreos"]
        self.assertEqual(len(vendor), 2)
        original_hashes, native_dep_hashes = set(), set()
        for row in vendor:
            with self.subTest(profile=row["vendor_profile"]):
                original = json.loads((ROOT / "docs" / row["original_firmware_evidence"]).read_text())
                native = json.loads((ROOT / "docs" / row["native_evidence"]).read_text())
                closure_name = ("arm64-armsr-native-closure.json"
                                if row["vendor_profile"] == "armsr"
                                else "arm64-r6xs-native-closure.json")
                closure = json.loads((ROOT / "docs/evidence/istoreos-25.12.6" /
                                      closure_name).read_text())
                self.assertEqual(row["sdk_build"], "native_apk_offline_solver_passed_unreleased")
                self.assertEqual(row["target"], native["target"])
                self.assertEqual(row["arch_expected"], native["arch"])
                self.assertEqual(row["vendor_profile"], native["vendor_profile"])
                self.assertEqual(row["revision"], native["revision"])
                self.assertEqual(original["verified_raw_image_sha256"], native["original_image_sha256"])
                self.assertEqual(native["native_apk_sha256"], closure["apk_sha256"])
                self.assertRegex(native["native_apk_sha256"], r"^[a-f0-9]{64}$")
                self.assertEqual(native["offline_solver"], "passed_no_network")
                self.assertEqual(native["packages_simulated"], 7)
                self.assertEqual(len(native["missing_vendor_dependencies"]), 6)
                self.assertTrue(native["original_full_tcpdump_preserved"])
                self.assertTrue(native["original_db_unchanged"])
                self.assertEqual(native["existing_firmware_package_removals"], 0)
                self.assertEqual(native["device_acceptance"], "not_run")
                self.assertFalse(native["publishable"])
                self.assertNotIn(("istoreos", row["release"], row["target"], "apk"),
                                 build_release.SUPPORTED_BUILDS)
                original_hashes.add(native["original_image_sha256"])
                native_dep_hashes.add(native["missing_vendor_dependencies"]["adblock-fast"]["sha256"])
        self.assertEqual(len(original_hashes), 2)
        self.assertEqual(len(native_dep_hashes), 2)

    def test_public_matrix_still_only_has_five_original_release_rows(self):
        matrix = json.loads((ROOT / "docs/compatibility-matrix.json").read_text())
        self.assertEqual(len(matrix["sdk_verified"]), 5)
        self.assertEqual(len(build_release.SUPPORTED_BUILDS), 5)
        self.assertFalse(any(row["firmware"] == "istoreos"
                             for row in matrix["sdk_verified"]))


if __name__ == "__main__":
    unittest.main()
