"""Installer safety boundaries with fake package managers and an isolated root."""
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="adzero-install-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "root"
        self.bin = self.base / "bin"
        self.release = self.base / "release"
        self.bin.mkdir()
        self.release.mkdir()
        self.log = self.base / "operations"
        self.env = {**os.environ, "PATH": str(self.bin) + ":" + os.environ["PATH"], "ADZERO_INSTALL_ROOT": str(self.root), "MOCK_INSTALL_LOG": str(self.log)}
        self.write("etc/openwrt_release", "DISTRIB_ID='OpenWrt'\nDISTRIB_RELEASE='24.10.8'\nDISTRIB_TARGET='x86/64'\n")
        self.write("etc/config/keep", "private=original\n")
        self.write("usr/lib/opkg/status", "fixture")
        self.executable(self.bin / "id", "#!/bin/sh\necho 0\n")
        self.executable(self.bin / "opkg", '#!/bin/sh\nif [ "$1" = print-architecture ]; then echo "arch x86_64 10"; else echo "opkg $1" >> "$MOCK_INSTALL_LOG"; fi\n')
        self.executable(self.root / "usr/libexec/adzero/ctl", '#!/bin/sh\necho "ctl $1" >> "$MOCK_INSTALL_LOG"\n')
        package = self.release / "adzero-test.ipk"
        package.write_bytes(b"not executed - package manager fixture")
        self.sum = hashlib.sha256(package.read_bytes()).hexdigest()
        self.row()

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target

    def executable(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        path.chmod(0o755)

    def row(self, sha=None, name="adzero-test.ipk"):
        (self.release / "releases.tsv").write_text(f"{sha or self.sum}\t{name}\topenwrt\t24.10.8\tx86/64\tx86_64\tipk\n")

    def run_installer(self, *extra, success=True):
        command = shlex.split(os.environ.get("ADZERO_TEST_SHELL", "sh"))
        result = subprocess.run(command + [str(ROOT / "scripts/install.sh"), "--local-dir", str(self.release), *extra], env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def test_exact_matrix_checksum_backup_install_then_enable(self):
        self.run_installer()
        self.assertEqual(self.log.read_text().splitlines(), ["opkg update", "opkg install", "ctl enable"])
        self.assertTrue(list((self.root / "etc/adzero-backups").glob("*/config.tar.gz")))
        self.assertEqual((self.root / "etc/config/keep").read_text(), "private=original\n")

    def test_unsupported_version_and_vendor_do_not_install(self):
        for value in ("DISTRIB_ID='ImmortalWrt'\nDISTRIB_RELEASE='24.10.8'\nDISTRIB_TARGET='x86/64'\n", "DISTRIB_ID='OpenWrt'\nDISTRIB_RELEASE='24.10.9'\nDISTRIB_TARGET='x86/64'\n"):
            self.write("etc/openwrt_release", value)
            self.run_installer(success=False)
            self.assertFalse(self.log.exists())

    def test_corrupt_package_or_path_traversal_do_not_install(self):
        self.row(sha="0" * 64)
        self.run_installer(success=False)
        self.row(name="../../untrusted.ipk")
        self.run_installer(success=False)
        self.assertFalse(self.log.exists())

    def test_ambiguous_catalog_is_rejected(self):
        path = self.release / "releases.tsv"
        path.write_text(path.read_text() * 2)
        self.run_installer(success=False)
        self.assertFalse(self.log.exists())

    def test_existing_adapter_journal_is_not_overwritten(self):
        self.write("etc/adzero/adapter.json", "recovery-data")
        self.run_installer(success=False)
        self.assertEqual((self.root / "etc/adzero/adapter.json").read_text(), "recovery-data")
        self.assertFalse(self.log.exists())

    def test_no_enable_option(self):
        self.run_installer("--no-enable")
        self.assertNotIn("ctl enable", self.log.read_text())

    def test_other_target_is_reported_even_with_x86_package_manager_fixture(self):
        self.write("etc/openwrt_release", "DISTRIB_ID='OpenWrt'\nDISTRIB_RELEASE='25.12.5'\nDISTRIB_TARGET='mediatek/filogic'\n")
        result = self.run_installer(success=False)
        self.assertIn("target=mediatek/filogic", result.stderr)
        self.assertIn("x86/64", result.stderr)
        self.assertFalse(self.log.exists())
        self.assertFalse((self.root / "etc/adzero-backups").exists())

    def test_missing_target_is_reported_separately_without_installing(self):
        self.write("etc/openwrt_release", "DISTRIB_ID='OpenWrt'\nDISTRIB_RELEASE='25.12.5'\n")
        result = self.run_installer(success=False)
        self.assertIn("缺少 DISTRIB_TARGET", result.stderr)
        self.assertFalse(self.log.exists())
        self.assertFalse((self.root / "etc/adzero-backups").exists())

    def arm_apk(self, arch="aarch64", declared="aarch64_generic"):
        self.write("etc/openwrt_release", "DISTRIB_ID='OpenWrt'\nDISTRIB_RELEASE='25.12.5'\nDISTRIB_REVISION='r33051-f5dae5ece4'\nDISTRIB_TARGET='rockchip/armv8'\nDISTRIB_ARCH='" + declared + "'\n")
        (self.root / "usr/lib/opkg/status").unlink()
        self.write("lib/apk/db/installed", "fixture")
        self.executable(self.bin / "apk", '#!/bin/sh\nif [ "$1" = --print-arch ]; then echo "' + arch + '"; else echo "apk $1" >> "$MOCK_INSTALL_LOG"; fi\n')
        package = self.release / "arm-test.apk"
        package.write_bytes(b"ARM SDK package fixture, not executed")
        sha = hashlib.sha256(package.read_bytes()).hexdigest()
        (self.release / "releases.tsv").write_text(f"{sha}\tarm-test.apk\topenwrt\t25.12.5\trockchip/armv8\taarch64_generic\tapk\n")

    def test_user_rockchip_metadata_selects_arm_apk_and_enables(self):
        self.arm_apk()
        result = self.run_installer()
        self.assertIn("arm-test.apk", result.stdout)
        self.assertEqual(self.log.read_text().splitlines(), ["apk update", "apk add", "ctl enable"])

    def test_apk_repository_arch_spelling_is_accepted_for_exact_target(self):
        self.arm_apk(arch="aarch64_generic")
        self.run_installer("--no-enable")
        self.assertEqual(self.log.read_text().splitlines(), ["apk update", "apk add"])

    def test_rockchip_mismatched_apk_cpu_is_rejected_before_install(self):
        self.arm_apk(arch="x86_64")
        self.run_installer(success=False)
        self.assertFalse(self.log.exists())

    def test_rockchip_mismatched_declared_abi_is_rejected(self):
        self.arm_apk(declared="aarch64_cortex-a53")
        self.run_installer(success=False)
        self.assertFalse(self.log.exists())

    def test_rockchip_cannot_select_x86_or_other_release_catalog(self):
        self.arm_apk()
        (self.release / "releases.tsv").write_text(f"{self.sum}\tadzero-test.ipk\topenwrt\t25.12.5\tx86/64\tx86_64\tapk\n")
        self.run_installer(success=False)
        self.assertFalse(self.log.exists())

    def upgrade_fixture(self, mode="success"):
        journal = self.write("etc/adzero/adapter.json", "private-recovery-data")
        self.env.update(MOCK_UPGRADE_MODE=mode, MOCK_UPGRADE_JOURNAL=str(journal), MOCK_UPGRADE_BUSY=str(self.base / "busy"))
        self.executable(self.bin / "sleep", '#!/bin/sh\necho "wait $1" >> "$MOCK_INSTALL_LOG"\nrm -f "$MOCK_UPGRADE_BUSY"\n')
        self.executable(self.root / "usr/libexec/adzero/ctl", '''#!/bin/sh
echo "ctl $1" >> "$MOCK_INSTALL_LOG"
if [ "$1" = disable ]; then
    if [ "$MOCK_UPGRADE_MODE" = busy_forever ] || [ -e "$MOCK_UPGRADE_BUSY" ]; then
        echo 'AdZero: 另一项操作正在进行；若异常断电可检查临时锁。' >&2
        exit 1
    fi
    if [ "$MOCK_UPGRADE_MODE" = restore_failure ]; then echo '恢复失败，保留记录' >&2; exit 1; fi
    if [ "$MOCK_UPGRADE_MODE" != false_success ]; then rm -f "$MOCK_UPGRADE_JOURNAL"; fi
fi
''')
        return journal

    def test_upgrade_verifies_package_and_backs_up_state_before_restore(self):
        import tarfile
        self.upgrade_fixture()
        self.run_installer("--upgrade")
        self.assertEqual(self.log.read_text().splitlines(), ["ctl disable", "opkg update", "opkg install", "ctl enable"])
        backups = list((self.root / "etc/adzero-backups").glob("*/state.tar.gz"))
        self.assertEqual(len(backups), 1)
        with tarfile.open(backups[0]) as archive:
            self.assertEqual(archive.extractfile("adzero/adapter.json").read(), b"private-recovery-data")
        self.assertEqual(backups[0].stat().st_mode & 0o077, 0)

    def test_upgrade_bad_checksum_does_not_disable_current_protection(self):
        journal = self.upgrade_fixture()
        self.row(sha="0" * 64)
        self.run_installer("--upgrade", success=False)
        self.assertTrue(journal.exists())
        self.assertFalse(self.log.exists())

    def test_upgrade_retries_only_legacy_busy_then_installs(self):
        self.upgrade_fixture()
        Path(self.env["MOCK_UPGRADE_BUSY"]).touch()
        result = self.run_installer("--upgrade")
        self.assertIn("最多等待 30 秒", result.stdout)
        self.assertEqual(self.log.read_text().splitlines(), ["ctl disable", "wait 5", "ctl disable", "opkg update", "opkg install", "ctl enable"])

    def test_upgrade_persistent_busy_preserves_lock_and_recovery(self):
        journal = self.upgrade_fixture("busy_forever")
        lock = self.root / "tmp/adzero.lock"
        lock.mkdir(parents=True)
        result = self.run_installer("--upgrade", success=False)
        self.assertIn("没有删除锁或安装新包", result.stderr)
        self.assertTrue(journal.exists())
        self.assertTrue(lock.is_dir())
        operations = self.log.read_text().splitlines()
        self.assertEqual(operations.count("ctl disable"), 7)
        self.assertFalse(any(x.startswith("opkg") for x in operations))

    def test_upgrade_restore_failure_is_not_retried_or_installed(self):
        journal = self.upgrade_fixture("restore_failure")
        self.run_installer("--upgrade", success=False)
        self.assertTrue(journal.exists())
        self.assertEqual(self.log.read_text().splitlines(), ["ctl disable"])

    def test_upgrade_exit_zero_with_remaining_journal_is_rejected(self):
        journal = self.upgrade_fixture("false_success")
        self.run_installer("--upgrade", success=False)
        self.assertTrue(journal.exists())
        self.assertEqual(self.log.read_text().splitlines(), ["ctl disable"])

    def test_upgrade_no_enable_leaves_protection_off(self):
        self.upgrade_fixture()
        self.run_installer("--upgrade", "--no-enable")
        self.assertEqual(self.log.read_text().splitlines(), ["ctl disable", "opkg update", "opkg install"])
