"""Offline, mocked GitHub updater. Never downloads or installs real packages."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
UPDATE = ROOT / "luci-app-adzero/root/usr/libexec/adzero/update"

CURL = r'''#!/bin/sh
dest=; url=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output) dest=$2; shift 2 ;;
    --connect-timeout|--max-time|--max-filesize|--proto|--proto-redir) shift 2 ;;
    --*) shift ;;
    *) url=$1; shift ;;
  esac
done
printf '%s\n' "$url" >> "$MOCK_URLS"
case "$url" in
  'https://api.github.com/repos/slobys/AdZero/releases?per_page=20')
     [ ! -f "$MOCK_FAIL_NETWORK" ] || exit 6
     printf '[{"tag_name":"v0.21.4"}]\n' > "$dest" ;;
  https://github.com/slobys/AdZero/releases/download/v0.21.4/install.sh)
     [ ! -f "$MOCK_FAIL_NETWORK" ] || exit 6
     cp "$MOCK_INSTALLER" "$dest" ;;
  *) echo 'wrong remote URL' >&2; exit 7 ;;
esac
'''
UCODE = r'''#!/bin/sh
printf '%s %s\n' "$MOCK_TAG" "$MOCK_DIGEST"
'''
INSTALLER = r'''#!/bin/sh
printf '%s\n' "$*" >> "$MOCK_ACTIONS"
case " $* " in
  *' --check '*) [ ! -f "$MOCK_FAIL_COMPAT" ] ;;
  *' --upgrade '*) [ ! -f "$MOCK_FAIL_UPGRADE" ] ;;
  *) exit 9 ;;
esac
'''


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="adzero-updater-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / "update-state"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.urls = self.root / "urls"
        self.actions = self.root / "actions"
        self.installer = self.root / "release-installer"
        self.installer.write_text(INSTALLER)
        self.installer.chmod(0o700)
        self.version = self.root / "version"
        self.version.write_text("0.21.3\n")
        self.curl = self.bin / "mock-curl"
        self.ucode = self.bin / "mock-ucode"
        self.curl.write_text(CURL)
        self.ucode.write_text(UCODE)
        self.curl.chmod(0o700)
        self.ucode.chmod(0o700)
        self.fail_network = self.root / "fail-network"
        self.fail_compat = self.root / "fail-compat"
        self.fail_upgrade = self.root / "fail-upgrade"
        self.digest = hashlib.sha256(self.installer.read_bytes()).hexdigest()
        self.env = {
            **os.environ,
            "ADZERO_UPDATE_STATE": str(self.state),
            "ADZERO_UPDATE_VERSION_FILE": str(self.version),
            "ADZERO_UPDATE_UCODE": str(self.ucode),
            "ADZERO_UPDATE_CURL": str(self.curl),
            "ADZERO_UPDATE_PARSER": str(self.root / "unused-mock-parser"),
            "MOCK_TAG": "v0.21.4",
            "MOCK_DIGEST": self.digest,
            "MOCK_URLS": str(self.urls),
            "MOCK_ACTIONS": str(self.actions),
            "MOCK_INSTALLER": str(self.installer),
            "MOCK_FAIL_NETWORK": str(self.fail_network),
            "MOCK_FAIL_COMPAT": str(self.fail_compat),
            "MOCK_FAIL_UPGRADE": str(self.fail_upgrade),
        }

    def call(self, *args, success=True):
        out = subprocess.run(["sh", str(UPDATE), *args], env=self.env,
                             text=True, capture_output=True, timeout=15)
        if success:
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        else:
            self.assertNotEqual(out.returncode, 0, out.stdout + out.stderr)
        return out

    def test_missing_downloader_fails_before_lock_with_clear_diagnostic(self):
        # Trap cleanup must be safe even if prepare fails before acquire().
        self.env["ADZERO_UPDATE_CURL"] = "/nonexistent/adzero-curl"
        result = self.call("check", success=False)
        self.assertIn("缺少 curl", result.stderr)
        self.assertNotIn("lock_owned", result.stderr)
        self.assertFalse((self.state / "lock").exists())
        self.assertFalse(self.urls.exists())

    def test_up_to_date_never_launches_install(self):
        self.env["MOCK_TAG"] = "v0.21.3"
        reply = json.loads(self.call("check").stdout)
        self.assertTrue(reply["ok"])
        self.assertFalse(reply["available"])
        self.assertFalse(self.actions.exists())
        self.assertFalse((self.state / "approved").exists())

    def test_current_version_greater_than_release_is_not_update(self):
        self.version.write_text("0.22.0\n")
        reply = json.loads(self.call("check").stdout)
        self.assertFalse(reply["available"])

    def test_new_release_checks_hash_and_firmware_before_approval(self):
        result = json.loads(self.call("check").stdout)
        self.assertEqual(result["latest"], "v0.21.4")
        self.assertTrue(result["available"])
        self.assertTrue(result["compatible"])
        self.assertTrue((self.state / "approved").exists())
        self.assertEqual(self.actions.read_text().count("--check"), 1)
        urls = self.urls.read_text().splitlines()
        self.assertEqual(urls, [
            "https://api.github.com/repos/slobys/AdZero/releases?per_page=20",
            "https://github.com/slobys/AdZero/releases/download/v0.21.4/install.sh",
        ])

    def test_wrong_asset_digest_must_not_mark_compatible(self):
        self.env["MOCK_DIGEST"] = "0" * 64
        result = json.loads(self.call("check").stdout)
        self.assertTrue(result["available"])
        self.assertFalse(result["compatible"])
        self.assertFalse(self.actions.exists())
        self.assertFalse((self.state / "approved").exists())

    def test_missing_compatible_package_never_approves_update(self):
        self.fail_compat.touch()
        result = json.loads(self.call("check").stdout)
        self.assertTrue(result["available"])
        self.assertFalse(result["compatible"])
        self.assertFalse((self.state / "approved").exists())
        self.assertNotIn("--upgrade", self.actions.read_text())

    def test_offline_check_reports_error_without_launch(self):
        self.fail_network.touch()
        result = json.loads(self.call("check").stdout)
        self.assertFalse(result["ok"])
        self.assertFalse(self.actions.exists())
        self.assertFalse((self.state / "approved").exists())

    def test_upgrade_requires_prior_approval(self):
        self.call("upgrade", "v0.21.4", success=False)
        self.assertFalse(self.actions.exists())

    def test_upgrade_rechecks_hash_and_uses_pinned_release(self):
        self.call("check")
        self.call("upgrade", "v0.21.4")
        actions = self.actions.read_text().splitlines()
        self.assertEqual(len(actions), 3)
        self.assertIn("--check", actions[0])
        self.assertIn("--check", actions[1])
        self.assertIn("--upgrade", actions[2])
        self.assertNotIn("--no-enable", actions[2])
        self.assertTrue(all("https://github.com/slobys/AdZero/releases/download/v0.21.4" in entry for entry in actions))
        self.assertFalse((self.state / "approved").exists())
        self.call("upgrade", "v0.21.4", success=False)
        self.assertEqual(self.actions.read_text().splitlines(), actions)

    def test_disallow_change_of_approved_version(self):
        self.call("check")
        self.call("upgrade", "v0.21.9", success=False)
        self.assertEqual(len(self.actions.read_text().splitlines()), 1)
        self.assertTrue((self.state / "approved").exists())

    def test_disallow_dangerous_user_supplied_versions(self):
        self.call("check")
        for bad in ("../0.21.4", "v0.21.4;id", "https://bad.site/a", ""):
            with self.subTest(bad=bad):
                self.call("upgrade", bad, success=False)
        self.assertEqual(len(self.actions.read_text().splitlines()), 1)

    def test_expired_approval_rejected_before_network_call(self):
        self.call("check")
        (self.state / "approved").write_text(f"v0.21.4 {self.digest} {int(time.time()) - 3600}\n")
        self.call("upgrade", "v0.21.4", success=False)
        self.assertEqual(len(self.actions.read_text().splitlines()), 1)

    def test_upgrade_download_sha_mismatch_preserves_protection(self):
        self.call("check")
        self.env["MOCK_DIGEST"] = "0" * 64
        # Simulate modified downloaded installer after approval, without
        # altering the approved SHA-256: detection must fail before --upgrade.
        self.installer.write_text(INSTALLER + "\n# changed\n")
        self.call("upgrade", "v0.21.4", success=False)
        self.assertEqual(len(self.actions.read_text().splitlines()), 1)
        self.assertFalse((self.state / "approved").exists())

    def test_upgrade_failure_no_retry(self):
        self.call("check")
        self.fail_upgrade.touch()
        self.call("upgrade", "v0.21.4", success=False)
        self.assertEqual(len(self.actions.read_text().splitlines()), 3)
        self.assertFalse((self.state / "approved").exists())

    def test_incompatible_check_clears_previous_approval(self):
        self.call("check")
        self.assertTrue((self.state / "approved").exists())
        self.fail_network.touch()
        result = json.loads(self.call("check").stdout)
        self.assertFalse(result["ok"])
        self.assertFalse((self.state / "approved").exists())

    def test_path_guard_blocks_symlink_state(self):
        self.state.symlink_to(self.bin, target_is_directory=True)
        self.call("check", success=False)
        self.assertFalse(self.urls.exists())

    def test_installed_version_marker_must_be_semver(self):
        self.version.write_text("../0.21.3\n")
        self.call("check", success=False)
        self.assertFalse(self.urls.exists())


    def test_existing_update_lock_rejects_concurrent_checks(self):
        self.state.mkdir()
        lock = self.state / "lock"
        lock.mkdir()
        self.call("check", success=False)
        self.assertTrue(lock.is_dir())
        self.assertFalse(self.urls.exists())

    def test_existing_update_lock_rejects_concurrent_upgrades(self):
        self.call("check")
        lock = self.state / "lock"
        lock.mkdir()
        self.call("upgrade", "v0.21.4", success=False)
        self.assertTrue(lock.is_dir())
        self.assertEqual(len(self.actions.read_text().splitlines()), 1)
        self.assertTrue((self.state / "approved").exists())

    def test_check_cleans_its_lock_on_success_and_failure(self):
        self.call("check")
        self.assertFalse((self.state / "lock").exists())
        self.fail_network.touch()
        self.call("check")
        self.assertFalse((self.state / "lock").exists())

    def test_upgrade_cleans_its_lock_after_failure(self):
        self.call("check")
        self.fail_upgrade.touch()
        self.call("upgrade", "v0.21.4", success=False)
        self.assertFalse((self.state / "lock").exists())

if __name__ == "__main__":
    unittest.main()
