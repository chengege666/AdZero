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
