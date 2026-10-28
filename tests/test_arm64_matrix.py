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

    def test_public_matrix_still_only_has_five_original_release_rows(self):
        matrix = json.loads((ROOT / "docs/compatibility-matrix.json").read_text())
        self.assertEqual(len(matrix["sdk_verified"]), 5)
        self.assertEqual(len(build_release.SUPPORTED_BUILDS), 5)
        self.assertFalse(any(row["firmware"] == "istoreos"
                             for row in matrix["sdk_verified"]))


if __name__ == "__main__":
    unittest.main()
