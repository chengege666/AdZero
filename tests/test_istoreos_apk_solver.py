"""Never install packages: test only solver output validation."""
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_istoreos_apk_solver as solver


class SolverSafetyTests(unittest.TestCase):
    def test_exact_additions_only(self):
        output = "(1/2) Installing conntrack (1.4.8-r1)\n(2/2) Installing luci-app-adzero (0.21.5-r1)\nOK: 526.2 MiB in 1025 packages\n"
        self.assertEqual(solver.parse_changes(output, ["conntrack", "luci-app-adzero"]),
                         ["conntrack", "luci-app-adzero"])

    def test_existing_package_changes_or_unexpected_additions_refused(self):
        scenarios = (
            ("(1/2) Installing conntrack (1-r1)\n(2/2) Installing extra (1-r1)\nOK: done", ["conntrack", "luci-app-adzero"]),
            ("(1/2) Installing conntrack (1-r1)\n(2/2) Removing tcpdump (4-r1)\nOK: done", ["conntrack"]),
            ("(1/1) Upgrading tcpdump (4-r1)\nOK: done", []),
            ("(1/1) Installing conntrack (1-r1)", ["conntrack"]),
        )
        for output, expected in scenarios:
            with self.subTest(output=output):
                with self.assertRaises(ValueError):
                    solver.parse_changes(output, expected)


if __name__ == "__main__":
    unittest.main()
