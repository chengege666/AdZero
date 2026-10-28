"""Menu install/upgrade/check/uninstall regressions using isolated router roots.

All package managers, controllers and root file systems are temporary fixtures.
No network requests or real router modifications are performed.
"""
import os
from pathlib import Path
import shlex
import subprocess
import unittest

import test_installer

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "scripts/install.sh"


class MenuInstallerTest(unittest.TestCase):
    def setUp(self):
        self.fixture = test_installer.InstallerTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture

    def run_menu(self, response, *args, success=True):
        shell = shlex.split(os.environ.get("ADZERO_TEST_SHELL", "sh"))
        result = subprocess.run(
            shell + [str(INSTALL), "--menu", "--local-dir", str(self.f.release), *args],
            input=response, env=self.f.env, text=True, capture_output=True, timeout=20
        )
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def installed_fixture(self, upgrade=True):
        self.f.write("etc/config/adzero", "config adzero 'main'\n\toption enabled '0'\n")
        if upgrade:
            return self.f.upgrade_fixture()

    def fresh_fixture(self):
        controller = self.f.root / "usr/libexec/adzero/ctl"
        ctl = self.f.base / "controller-after-install"
        ctl.write_text(controller.read_text())
        controller.unlink()
        config = self.f.base / "config-after-install"
        config.write_text("config adzero 'main'\n\toption enabled '0'\n")
        self.f.env.update(MOCK_CTL_TEMPLATE=str(ctl), MOCK_CONFIG_TEMPLATE=str(config))
        self.f.executable(self.f.bin / "opkg", """#!/bin/sh
if [ "$1" = print-architecture ]; then echo 'arch x86_64 10'; exit 0; fi
echo "opkg $1" >> "$MOCK_INSTALL_LOG"
if [ "$1" = install ]; then
    mkdir -p "$ADZERO_INSTALL_ROOT/usr/libexec/adzero" "$ADZERO_INSTALL_ROOT/etc/config"
    cp "$MOCK_CTL_TEMPLATE" "$ADZERO_INSTALL_ROOT/usr/libexec/adzero/ctl"
    chmod 755 "$ADZERO_INSTALL_ROOT/usr/libexec/adzero/ctl"
    cp "$MOCK_CONFIG_TEMPLATE" "$ADZERO_INSTALL_ROOT/etc/config/adzero"
fi
""")

    def test_menu_exit_displays_firmware_and_pinned_release(self):
        out = self.run_menu("0\n").stdout
        self.assertIn("AdZero 安装管理", out)
        self.assertIn("OpenWrt", out)
        self.assertIn("x86/64", out)
        self.assertIn("本地发行目录", out)
        self.assertIn("一键安装 / 自动升级", out)
        self.assertIn("安全卸载", out)
        self.assertIn("已退出", out)
        self.assertFalse(self.f.log.exists())

    def test_menu_invalid_choice_and_input_eof_are_safe(self):
        out = self.run_menu("maybe\n").stdout
        self.assertIn("请输入 0 至 4", out)
        self.assertIn("输入结束", out)
        self.assertFalse(self.f.log.exists())

    def test_menu_check_is_read_only(self):
        self.installed_fixture()
        out = self.run_menu("3\n0\n").stdout
        self.assertIn("通过 SHA-256 校验", out)
        self.assertIn("未安装软件包", out)
        self.assertIn("校验完成", out)
        self.assertFalse(self.f.log.exists())
        self.assertFalse((self.f.root / "etc/adzero-backups").exists())
        self.assertTrue((self.f.root / "etc/adzero/adapter.json").exists())

    def test_check_only_flag_does_not_install_or_overwrite_journal(self):
        journal = self.installed_fixture()
        r = self.f.run_installer("--check")
        self.assertIn("SDK 架构=x86_64", r.stdout)
        self.assertFalse(self.f.log.exists())
        self.assertEqual(journal.read_text(), "private-recovery-data")
        self.assertFalse((self.f.root / "tmp/adzero-install.lock").exists())

    def test_check_checksum_failure_has_no_system_mutations(self):
        self.f.row(sha="0" * 64)
        out = self.run_menu("3\n0\n").stdout
        self.assertIn("校验未通过", out)
        self.assertFalse(self.f.log.exists())
        self.assertFalse((self.f.root / "etc/adzero-backups").exists())

    def test_check_unsupported_target_is_safely_rejected(self):
        self.f.write(
            "etc/openwrt_release",
            "DISTRIB_ID='OpenWrt'\nDISTRIB_RELEASE='25.12.5'\n"
            "DISTRIB_TARGET='mediatek/filogic'\n"
        )
        out = self.run_menu("3\n0\n")
        self.assertIn("target=mediatek/filogic", out.stderr)
        self.assertIn("校验未通过", out.stdout)
        self.assertFalse(self.f.log.exists())

    def test_fresh_install_is_automatic_and_enables(self):
        self.fresh_fixture()
        out = self.run_menu("1\ny\n0\n").stdout
        self.assertIn("正在安装", out)
        self.assertIn("操作已完成", out)
        self.assertEqual(self.f.log.read_text().splitlines(),
                         ["opkg update", "opkg install", "ctl enable"])
        self.assertTrue((self.f.root / "etc/config/adzero").is_file())

    def test_fresh_install_without_auto_enable(self):
        self.fresh_fixture()
        out = self.run_menu("2\ny\n0\n").stdout
        self.assertIn("不自动开启", out)
        self.assertEqual(self.f.log.read_text().splitlines(),
                         ["opkg update", "opkg install"])

    def test_existing_install_is_automatically_upgraded(self):
        self.installed_fixture()
        out = self.run_menu("1\ny\n0\n").stdout
        self.assertIn("正在升级", out)
        self.assertEqual(self.f.log.read_text().splitlines(),
                         ["opkg update", "ctl disable", "opkg install", "ctl enable"])

    def test_upgrade_without_auto_enable_preserves_existing_protection_journal(self):
        journal = self.installed_fixture()
        out = self.run_menu("2\ny\n0\n").stdout
        self.assertIn("正在升级", out)
        self.assertEqual(self.f.log.read_text().splitlines(),
                         ["opkg update", "ctl disable", "opkg install"])
        self.assertFalse(journal.exists())

    def test_cancel_install_does_not_modify_root(self):
        self.fresh_fixture()
        out = self.run_menu("1\nn\n0\n").stdout
        self.assertIn("已取消", out)
        self.assertFalse(self.f.log.exists())
        self.assertFalse((self.f.root / "etc/adzero-backups").exists())

    def test_partial_install_refuses_install_upgrade_and_uninstall(self):
        self.f.write("etc/config/adzero", "config adzero 'main'\n")
        (self.f.root / "usr/libexec/adzero/ctl").unlink()
        out = self.run_menu("1\n4\n0\n").stdout
        self.assertIn("不完整", out)
        self.assertFalse(self.f.log.exists())

    def test_upgrade_repository_failure_does_not_disable_old_protection(self):
        journal = self.installed_fixture()
        self.f.env["MOCK_UPDATE_FAIL"] = "1"
        out = self.run_menu("1\ny\n0\n").stdout
        self.assertIn("操作失败", out)
        self.assertEqual(self.f.log.read_text().splitlines(), ["opkg update"])
        self.assertEqual(journal.read_text(), "private-recovery-data")

    def test_uninstall_requires_exact_confirmation(self):
        self.installed_fixture(upgrade=False)
        out = self.run_menu("4\nno\n0\n").stdout
        self.assertIn("已取消卸载", out)
        self.assertFalse(self.f.log.exists())

    def test_uninstall_disables_then_removes_package(self):
        self.installed_fixture(upgrade=False)
        out = self.run_menu("4\nYES\n0\n").stdout
        self.assertIn("卸载完成", out)
        self.assertEqual(self.f.log.read_text().splitlines(),
                         ["ctl disable", "opkg remove"])
        self.assertFalse((self.f.root / "tmp/adzero-install.lock").exists())

    def test_uninstall_controller_failure_preserves_package(self):
        self.installed_fixture(upgrade=False)
        self.f.executable(self.f.root / "usr/libexec/adzero/ctl", """#!/bin/sh
echo "ctl $1" >> "$MOCK_INSTALL_LOG"
[ "$1" != disable ] || exit 9
""")
        out = self.run_menu("4\nYES\n0\n").stdout
        self.assertIn("已停止卸载", out)
        self.assertEqual(self.f.log.read_text().splitlines(), ["ctl disable"])

        self.assertFalse((self.f.root / "tmp/adzero-install.lock").exists())

    def test_uninstall_refuses_unknown_or_ambiguous_package_manager(self):
        self.installed_fixture(upgrade=False)
        self.f.write("lib/apk/db/installed", "fixture")
        self.f.executable(self.f.bin / "apk", "#!/bin/sh\nexit 0\n")
        out = self.run_menu("4\n0\n").stdout
        self.assertIn("两个包管理器数据库", out)
        self.assertFalse(self.f.log.exists())

    def test_version_display_is_managed_by_source_not_user_input(self):
        shell = shlex.split(os.environ.get("ADZERO_TEST_SHELL", "sh"))
        result = subprocess.run(shell + [str(INSTALL), "--menu"],
                                input="0\n", text=True, capture_output=True,
                                env=self.f.env, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("v0.21.3", result.stdout)
        self.assertFalse(self.f.log.exists())


    def test_no_arguments_enter_menu_even_without_tty_and_eof_exits_safely(self):
        shell = shlex.split(os.environ.get("ADZERO_TEST_SHELL", "sh"))
        result = subprocess.run(shell + [str(INSTALL)],
                                input="", text=True, capture_output=True,
                                env=self.f.env, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("AdZero 安装管理", result.stdout)
        self.assertIn("输入结束", result.stdout)
        self.assertFalse(self.f.log.exists())
        self.assertFalse((self.f.root / "etc/adzero-backups").exists())

    def test_explicit_install_flag_preserves_headless_cli(self):
        result = self.f.run_installer("--install", "--no-enable")
        self.assertIn("安装完成", result.stdout)
        self.assertEqual(self.f.log.read_text().splitlines(),
                         ["opkg update", "opkg install"])

    def test_apk_upgrade_detected_without_manual_package_format(self):
        self.f.arm_apk()
        self.installed_fixture()
        out = self.run_menu("1\ny\n0\n").stdout
        self.assertIn("正在升级", out)
        self.assertIn("操作已完成", out)
        self.assertEqual(self.f.log.read_text().splitlines(),
                         ["apk check-local", "ctl disable", "apk add-local", "ctl enable"])

    def test_apk_check_is_read_only_and_uses_exact_arch(self):
        self.f.arm_apk()
        self.installed_fixture()
        out = self.run_menu("3\n0\n").stdout
        self.assertIn("SDK 架构=aarch64_generic", out)
        self.assertIn("包格式=apk", out)
        self.assertFalse(self.f.log.exists())

    def test_apk_uninstall_disables_before_package_removal(self):
        self.f.arm_apk()
        self.installed_fixture(upgrade=False)
        out = self.run_menu("4\nYES\n0\n").stdout
        self.assertIn("卸载完成", out)
        self.assertEqual(self.f.log.read_text().splitlines(),
                         ["ctl disable", "apk del"])

    def test_installed_unconfirmed_root_never_attempts_uninstall(self):
        self.installed_fixture(upgrade=False)
        out = self.run_menu("4\n0\n").stdout
        self.assertIn("已取消卸载", out)
        self.assertFalse(self.f.log.exists())

    def test_read_only_check_respects_package_hash_on_apk(self):
        self.f.arm_apk()
        release_file = self.f.release / "releases.tsv"
        rows = release_file.read_text().split("\t")
        rows[0] = "f" * 64
        release_file.write_text("\t".join(rows))
        out = self.run_menu("3\n0\n")
        self.assertIn("校验未通过", out.stdout)
        self.assertIn("SHA-256 不匹配", out.stderr)
        self.assertFalse(self.f.log.exists())

    def test_symlinked_controller_is_not_automatically_executed(self):
        controller = self.f.root / "usr/libexec/adzero/ctl"
        original = self.f.base / "untrusted-ctl"
        original.write_text(controller.read_text())
        original.chmod(0o755)
        controller.unlink()
        controller.symlink_to(original)
        self.f.write("etc/config/adzero", "config adzero 'main'\n")
        out = self.run_menu("1\n4\n0\n").stdout
        self.assertIn("不完整", out)
        self.assertFalse(self.f.log.exists())

    def test_uninstall_respects_install_lock_without_deleting_it(self):
        self.installed_fixture(upgrade=False)
        lock = self.f.root / "tmp/adzero-install.lock"
        lock.mkdir(parents=True)
        out = self.run_menu("4\nYES\n0\n").stdout
        self.assertIn("拒绝并行卸载", out)
        self.assertTrue(lock.is_dir())
        self.assertFalse(self.f.log.exists())

    def test_uninstall_respects_controller_lock_before_mutation(self):
        self.installed_fixture(upgrade=False)
        lock = self.f.root / "tmp/adzero.lock"
        lock.mkdir(parents=True)
        out = self.run_menu("4\nYES\n0\n").stdout
        self.assertIn("保护任务锁", out)
        self.assertTrue(lock.is_dir())
        self.assertFalse(self.f.log.exists())

    def test_uninstall_lock_is_released_when_opkg_remove_fails(self):
        self.installed_fixture(upgrade=False)
        self.f.executable(self.f.bin / "opkg", """#!/bin/sh
if [ "$1" = print-architecture ]; then echo 'arch x86_64 10'; exit 0; fi
echo "opkg $1" >> "$MOCK_INSTALL_LOG"
[ "$1" != remove ]
""")
        out = self.run_menu("4\nYES\n0\n").stdout
        self.assertIn("OPKG 卸载失败", out)
        self.assertEqual(self.f.log.read_text().splitlines(),
                         ["ctl disable", "opkg remove"])
        self.assertFalse((self.f.root / "tmp/adzero-install.lock").exists())

    def test_menu_rejects_direct_operation_flags_to_avoid_ambiguous_actions(self):
        for flag in ("--upgrade", "--check", "--no-enable"):
            with self.subTest(flag=flag):
                result = self.run_menu("1\ny\n0\n", flag, success=False)
                self.assertIn("菜单模式不能同时使用", result.stderr)
                self.assertFalse(self.f.log.exists())
                self.assertFalse((self.f.root / "etc/adzero-backups").exists())

if __name__ == "__main__":
    unittest.main()
