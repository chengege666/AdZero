"""Offline provenance guards for immutable OpenWrt native CI fixture URLs.

This test never downloads packages or modifies a router. Online SHA and
package-index consistency are independently verified in CI preparation.
"""
import json
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
PREFIX="https://archive.openwrt.org/releases/24.10.8/packages/x86_64/"

class ArchivePinTests(unittest.TestCase):
    def test_official_openwrt_ci_archive_pins_and_current_consumers(self):
        report=json.loads((ROOT/"docs/evidence/ci-openwrt-24108-official-archive-pins.json").read_text())
        self.assertEqual(report["immutable_release_archive"],PREFIX)
        by_name={item["name"]:item for item in report["packages"]}
        self.assertEqual(len(by_name),7)
        for name,row in by_name.items():
            self.assertIn(row["feed"],("base","packages"))
            self.assertRegex(row["sha256"],r"^[0-9a-f]{64}$")
            self.assertTrue(name.endswith("_x86_64.ipk"))
        socket=(ROOT/"scripts/prepare_dns_socket.py").read_text()
        timeout=by_name["coreutils-timeout_9.7-r1_x86_64.ipk"]["sha256"]
        self.assertIn(by_name["ucode-mod-socket_2025.07.18~3f64c808-r1_x86_64.ipk"]["sha256"],socket)
        self.assertIn(PREFIX+"base/",socket)
        for filename in ("check_passwall_runtime.py","check_dns_pool_runtime.py"):
            script=(ROOT/"scripts"/filename).read_text()
            self.assertIn(PREFIX,script)
            self.assertIn(timeout,script)
        for filename in ("check_openclash_runtime.py","check_observe_runtime.py"):
            script=(ROOT/"scripts"/filename).read_text()
            self.assertIn(PREFIX,script)
        self.assertEqual(report["physical_device_acceptance"],"not_run")
        self.assertNotEqual(timeout,"145a99ab15600f4634df00d4a08c7c55ae05b274ae1d9afff3d96fed2f75f686")

if __name__=="__main__":
    unittest.main()
