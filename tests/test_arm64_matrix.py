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
                         {"native_source_metadata_verified_build_pending"})

    def test_public_matrix_still_only_has_five_original_release_rows(self):
        matrix = json.loads((ROOT / "docs/compatibility-matrix.json").read_text())
        self.assertEqual(len(matrix["sdk_verified"]), 5)
        self.assertEqual(len(build_release.SUPPORTED_BUILDS), 5)
        self.assertFalse(any(row["firmware"] == "istoreos"
                             for row in matrix["sdk_verified"]))


if __name__ == "__main__":
    unittest.main()
