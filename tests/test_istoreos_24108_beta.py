"""Isolated tests for the exact iStoreOS 24.10.8 OPKG beta menu.

All package-manager calls are fake processes using a disposable rootfs. No
router is accessed; actual OPKG/full device acceptance remains outstanding.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_istoreos_24108_beta as beta


class Istore24108Test(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="adzero-24108-fixture-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.router = self.root / "router"
        for part in ("usr/lib/opkg", "etc/config", "tmp/sysinfo"):
            (self.router / part).mkdir(parents=True)
        self.db = self.router / "usr/lib/opkg/status"
        self.db.write_text("Package: opkg\nPackage: luci-base\nPackage: rpcd\nPackage: tcpdump\n")
        (self.router / "etc/config/network").write_text("never-touch-existing-network")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.logs = self.root / "opkg.log"
        self.ctls = self.root / "ctl.log"
        self.curls = self.root / "curl.log"
        opkg = self.bin / "opkg"
        opkg.write_text("""#!/bin/sh
echo "$*" >> "$MOCK_OPKG_LOG"
case " $* " in
 *" --noaction install "*)
   [ "$MOCK_FAIL_PLAN" != 1 ] || exit 3
   if [ "$MOCK_UPGRADE" = 1 ]; then echo 'Upgrading tcpdump'; exit 0; fi
   echo 'Installing adblock-fast (1.2.4-r4) to root...'
   echo 'Installing luci-app-adzero (0.21.5-r1) to root...'
   exit 0 ;;
 *" install "*)
   echo 'Package: luci-app-adzero' >> "$MOCK_ROOT/usr/lib/opkg/status"
   mkdir -p "$MOCK_ROOT/usr/libexec/adzero"
   cat > "$MOCK_ROOT/usr/libexec/adzero/ctl" <<'EOCTL'
#!/bin/sh
echo "ctl:$1" >> "$MOCK_CTL_LOG"
EOCTL
   chmod 755 "$MOCK_ROOT/usr/libexec/adzero/ctl"
   exit 0 ;;
 *" remove luci-app-adzero "*)
   sed -i '/^Package: luci-app-adzero$/d' "$MOCK_ROOT/usr/lib/opkg/status"
   exit 0 ;;
 *) exit 99 ;;
esac
""")
        opkg.chmod(0o755)
        curl = self.bin / "curl"
        curl.write_text("""#!/bin/sh
out=
url=
while [ "$#" -gt 0 ]; do
 case "$1" in
 --output) out=$2;shift 2 ;;
 https://*) url=$1;shift ;;
 *) shift ;;
 esac
done
[ -n "$out" ] && [ -n "$url" ] || exit 91
echo "$url" >> "$MOCK_CURL_LOG"
cp "$MOCK_RELEASE/$(basename "$url")" "$out"
""")
        curl.chmod(0o755)
        self.release = self.root / "release"
        self.release.mkdir()
        def fixture(profile, *, root=ROOT):
            spec = beta.PROFILES[profile]
            files = {}
            files["packages/" + beta.APP_NAME] = b"native-adzero-opkg-placeholder" * 30
            for name in ("adblock-fast", "conntrack", "coreutils-timeout",
                         "libnetfilter-cthelper0", "libnetfilter-cttimeout1",
                         "libnetfilter-queue1", "ucode-mod-socket"):
                name_ipk = name + "_1-r1_" + spec["arch"] + ".ipk"
                files["packages/" + name_ipk] = (name + "-" + profile).encode() * 15
            files["profile.tsv"] = (
                f"istoreos\t24.10.8\t2026073111\t{spec['target']}\t"
                f"{spec['arch']}\t{profile}\tipk\n").encode()
            files["manifest.json"] = (json.dumps({"release_tag": beta.TAG,
                "profile": profile, "physical_router_acceptance": "not_run"})+"\n").encode()
            files["SHA256SUMS"] = "".join(
                beta.digest(files[k]) + "  " + k + "\n" for k in sorted(files)).encode()
            return files
        with mock.patch.object(beta, "validated_bundle", side_effect=fixture):
            self.assets = beta.build(self.release, root=ROOT)
        self.script = self.release / "install-istoreos-24108-beta.sh"

    def setup_profile(self, profile):
        spec = beta.PROFILES[profile]
        (self.router / "etc/openwrt_release").write_text(
            "DISTRIB_ID='iStoreOS'\nDISTRIB_RELEASE='24.10.8'\n"
            "DISTRIB_REVISION='2026073111'\n"
            f"DISTRIB_TARGET='{spec['target']}'\nDISTRIB_ARCH='{spec['arch']}'\n"
        )
        board = self.router / "tmp/sysinfo/board_name"
        board.unlink(missing_ok=True)
        if profile == "r6xs":
            board.write_text("fastrhino,r6xs\n")

    def run_cli(self, profile, *args, stdin="", success=True, extra=None):
        env = {**os.environ,
               "PATH": str(self.bin) + ":" + os.environ["PATH"],
               "ADZERO_24108_TEST_MODE": "1", "ADZERO_24108_TEST_ROOT": str(self.router),
               "MOCK_ROOT": str(self.router), "MOCK_OPKG_LOG": str(self.logs),
               "MOCK_CTL_LOG": str(self.ctls), "MOCK_CURL_LOG": str(self.curls),
               "MOCK_RELEASE": str(self.release), **(extra or {})}
        shell = os.environ.get("ADZERO_TEST_SHELL", "sh").split()
        result = subprocess.run(shell + [str(self.script), *args], env=env,
                                input=stdin, text=True, capture_output=True, timeout=25)
        self.assertEqual(result.returncode == 0, success, result.stdout+result.stderr)
        return result

    def test_three_exact_profiles_have_readonly_check_install_off_and_safe_uninstall(self):
        for profile in beta.PROFILES:
            with self.subTest(profile=profile):
                self.setup_profile(profile)
                before = self.db.read_bytes()
                self.run_cli(profile, "--check", "--local-dir", str(self.release))
                self.assertEqual(before, self.db.read_bytes())
                self.assertFalse(self.ctls.exists())
                self.run_cli(profile, "--local-dir", str(self.release), stdin="2\ny\n0\n")
                self.assertTrue((self.router/"etc/adzero-24108-beta/installed").exists())
                self.assertFalse(self.ctls.exists(), "Fresh install must not enable DNS")
                self.assertEqual((self.router/"etc/config/network").read_text(),
                                 "never-touch-existing-network")
                self.run_cli(profile, "--uninstall")
                self.assertFalse((self.router/"etc/adzero-24108-beta/installed").exists())
                self.assertIn("ctl:disable", self.ctls.read_text())
                (self.router/"usr/libexec/adzero/ctl").unlink()
                shutil.rmtree(self.router/"etc/adzero-backups")
                self.logs.unlink()
                self.ctls.unlink()

    def test_wrong_firmware_rev_arch_or_target_fail_before_download(self):
        self.setup_profile("armsr")
        path = self.router/"etc/openwrt_release"
        original = path.read_text()
        for first,second in (("iStoreOS","OpenWrt"),("24.10.8","24.10.7"),
                             ("2026073111","2026070313"),("armsr/armv8","x86/64"),
                             ("aarch64_generic","x86_64")):
            with self.subTest(first=first):
                path.write_text(original.replace(first, second))
                self.run_cli("armsr", "--check", success=False)
                self.assertFalse(self.curls.exists())
        path.write_text(original)
        (self.router/"lib/apk/db").mkdir(parents=True)
        (self.router/"lib/apk/db/installed").write_text("P:luci-base\n")
        self.run_cli("armsr","--check",success=False)

    def test_r6xs_symlink_and_foreign_board_are_rejected(self):
        self.setup_profile("r6xs")
        board = self.router/"tmp/sysinfo/board_name"
        board.write_text("unknown,rockchip\n")
        self.run_cli("r6xs", "--check", success=False)
        board.unlink()
        malicious = self.router/"tmp/sysinfo/attacker"
        malicious.write_text("fastrhino,r6xs\n")
        board.symlink_to(malicious)
        self.run_cli("r6xs", "--check", success=False)
        self.assertFalse(self.curls.exists())

    def test_bad_checksum_or_upgrading_tcpdump_is_blocked_before_install(self):
        self.setup_profile("x86_64")
        path = self.release/"adzero-istoreos-24108-x86_64-beta.tar.gz"
        content = path.read_bytes()
        path.write_bytes(content + b"tampered")
        self.run_cli("x86_64", "--install", "--local-dir", str(self.release), success=False)
        self.assertFalse(self.logs.exists())
        path.write_bytes(content)
        self.run_cli("x86_64", "--install", "--local-dir", str(self.release),
                     success=False, extra={"MOCK_UPGRADE":"1"})
        self.assertFalse((self.router/"etc/adzero-24108-beta/installed").exists())

    def test_enable_requires_explicit_ack_and_uninstall_marker(self):
        self.setup_profile("x86_64")
        self.run_cli("x86_64", "--install", "--enable", "--local-dir",str(self.release),
                     success=False)
        self.run_cli("x86_64", "--install", "--enable", "--accept-network-risk",
                     "--local-dir",str(self.release))
        self.assertIn("ctl:enable",self.ctls.read_text())
        marker = self.router/"etc/adzero-24108-beta/installed"
        marker.write_text("tag=unknown\nprofile=x86_64\n")
        self.run_cli("x86_64","--uninstall",success=False)
        marker.write_text(f"tag={beta.TAG}\nprofile=x86_64\ntarget=x86/64\n")
        self.run_cli("x86_64","--uninstall")
        self.assertFalse(marker.exists())

    def test_native_original_opkg_package_format_is_gzip_tar_not_debian_ar(self):
        import gzip
        import io
        import tarfile

        def tar_gzip_members(files):
            data = io.BytesIO()
            with gzip.GzipFile(fileobj=data, mode="wb", mtime=0, filename="") as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as outer:
                    for name, contents in files.items():
                        info = tarfile.TarInfo("./" + name)
                        info.size = len(contents)
                        info.mode = 0o644
                        outer.addfile(info, io.BytesIO(contents))
            return data.getvalue()

        control = tar_gzip_members({
            "control": (
                b"Package: luci-app-adzero\nVersion: 0.21.5-r1\n"
                b"Architecture: all\nDepends: luci-base, adblock-fast\n"
            ),
        })
        native = tar_gzip_members({
            "debian-binary": b"2.0\n",
            "data.tar.gz": tar_gzip_members({"usr/share/test": b"fixture"}),
            "control.tar.gz": control,
        })
        path = self.root / "native-opkg-fixture.ipk"
        path.write_bytes(native)
        parsed = beta.ipk_control(path)
        self.assertEqual(parsed["Package"], "luci-app-adzero")
        self.assertEqual(parsed["Version"], "0.21.5-r1")
        path.write_bytes(b"!<arch>\n" + b"\x00" * 64)
        with self.assertRaises(tarfile.ReadError):
            beta.ipk_control(path)

    def test_binary_builder_remains_unapproved_without_original_native_ipks(self):
        with self.assertRaises(ValueError):
            beta.validated_bundle("unknown-architecture")
        self.assertEqual(self.assets["targets"], 3)
        self.assertEqual(self.assets["format"], "ipk")
        self.assertFalse(self.assets["historical_source_exact_firmware_attested"])
        self.assertEqual(self.assets["release_tag"], beta.TAG)
        self.assertNotIn("@SHA_", self.script.read_text())
        for file, sha in self.assets["assets"].items():
            self.assertEqual(hashlib.sha256((self.release/file).read_bytes()).hexdigest(),sha)


if __name__ == "__main__":
    unittest.main()
