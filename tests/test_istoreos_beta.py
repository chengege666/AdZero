"""All beta install paths tested against isolated fake package manager and router."""
import hashlib
import json
import os
import shlex
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_istoreos_beta as beta


class BetaInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="adzero-beta-")
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.release=self.base/"release"; self.release.mkdir()
        self.router=self.base/"router"
        for f in ("etc/config","lib/apk/db","tmp/sysinfo"):
            (self.router/f).mkdir(parents=True)
        (self.router/"etc/config/network").write_text("original-untouched")
        (self.router/"lib/apk/db/installed").write_text("P:base-files\nP:tcpdump\nP:rpcd\nP:luci-base\nP:curl\n")
        self.bin=self.base/"bin";self.bin.mkdir()
        self.apks=self.base/"apk.log";self.ctls=self.base/"ctl.log";self.curls=self.base/"curl.log"
        shim=self.bin/"apk"
        shim.write_text("""#!/bin/sh
if [ "$1" = --print-arch ]; then echo "$MOCK_ARCH"; exit 0; fi
echo "$*" >> "$MOCK_APK_LOG"
case " $* " in
  *" info -e "*)
    [ "$MOCK_FORCE_APK_QUERY_FAIL" != 1 ] || exit 1
    while [ "$#" -gt 0 ] && [ "$1" != info ]; do shift; done
    [ "$#" -ge 3 ] && [ "$2" = -e ] || exit 91
    shift 2
    for package do
      grep -qx "P:$package" "$MOCK_APK_DB" || exit 1
    done
    exit 0 ;;
  *" list --installed --manifest luci-app-adzero "*)
    grep -qx 'P:luci-app-adzero' "$MOCK_APK_DB" || exit 1
    echo "luci-app-adzero ${MOCK_APP_VERSION:-0.21.5-r1}"
    exit 0 ;;
  *" info -W /usr/libexec/adzero/ctl "*)
    [ "$MOCK_FOREIGN_OWNER" != 1 ] || { echo 'owned by another-package-1-r1'; exit 0; }
    grep -qx 'P:luci-app-adzero' "$MOCK_APK_DB" || exit 1
    echo "/usr/libexec/adzero/ctl is owned by luci-app-adzero-${MOCK_APP_VERSION:-0.21.5-r1}"
    exit 0 ;;
  *" add --simulate --force-reinstall "*)
    [ "$MOCK_REINSTALL_FAIL" != 1 ] || exit 3
    echo '(1/1) Reinstalling luci-app-adzero (0.21.5-r1)'
    if [ "$MOCK_REINSTALL_EXTRA" = 1 ]; then echo '(2/2) Upgrading tcpdump (4.1)'; fi
    echo 'OK: 520 MiB in 1025 packages'
    exit 0 ;;
  *" add --simulate --no-network "*)
    [ "$MOCK_FAIL_PLAN" != 1 ] || exit 3
    echo '(1/7) Installing adblock-fast (1.2.4-r4)'
    echo '(2/7) Installing libnetfilter-cthelper0 (1-r2)'
    echo '(3/7) Installing libnetfilter-cttimeout1 (1-r2)'
    echo '(4/7) Installing libnetfilter-queue1 (1-r4)'
    echo '(5/7) Installing conntrack (1-r1)'
    echo '(6/7) Installing coreutils-timeout (9-r2)'
    echo '(7/7) Installing luci-app-adzero (0.21.5-r1)'
    if [ "$MOCK_EXTRA" = 1 ]; then echo '(8/8) Installing unknown-package (1-r1)'; fi
    if [ "$MOCK_UPGRADE" = 1 ]; then echo 'Upgrading tcpdump (4.1)'; fi
    echo 'OK: 520 MiB in 1025 packages'
    exit 0 ;;
  *" add --force-reinstall --no-network "*|*" add --no-network "*)
    [ "$MOCK_FAIL_INSTALL" != 1 ] || exit 4
    mkdir -p "$MOCK_ROOT/usr/libexec/adzero"
    grep -qx 'P:luci-app-adzero' "$MOCK_APK_DB" ||
      echo "P:luci-app-adzero" >> "$MOCK_APK_DB"
    [ -f "$MOCK_ROOT/etc/config/adzero" ] ||
      printf "config adzero 'main'\\n\\toption enabled '0'\\n" > "$MOCK_ROOT/etc/config/adzero"
    cat > "$MOCK_ROOT/usr/libexec/adzero/ctl" <<'EOCTL'
#!/bin/sh
echo "ctl:$1" >> "$MOCK_CTL_LOG"
if [ "$1" = disable ]; then
  [ "$MOCK_CTL_FAIL_DISABLE" != 1 ] || exit 1
  rm -f "$MOCK_ROOT/etc/adzero/managed" "$MOCK_ROOT/etc/adzero/adapter.json"
fi
EOCTL
    chmod +x "$MOCK_ROOT/usr/libexec/adzero/ctl"; exit 0 ;;
  *" del --simulate --no-network "*)
    echo '(1/1) Purging luci-app-adzero (0.21.5-r1)'
    if [ "$MOCK_DEL_EXTRA" = 1 ]; then echo '(2/2) Purging another-package (1-r1)'; fi
    echo 'OK: 520 MiB in 1024 packages'
    exit 0 ;;
  *" del --no-network "*)
    [ "$MOCK_FAIL_DELETE" != 1 ] || exit 5
    sed -i '/^P:luci-app-adzero$/d' "$MOCK_APK_DB"
    rm -f "$MOCK_ROOT/usr/libexec/adzero/ctl"
    exit 0 ;;
  *) echo "unexpected apk" >&2; exit 97 ;;
esac
""");shim.chmod(0o755)
        curl=self.bin/"curl"
        curl.write_text("""#!/bin/sh
echo "$*" >> "$MOCK_CURL_LOG"
out=
url=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output) out=$2; shift 2 ;;
    https://*) url=$1; shift ;;
    *) shift ;;
  esac
done
[ -n "$out" ] && [ -n "$url" ] || exit 8
cp "$MOCK_RELEASE/$(basename "$url")" "$out"
""");curl.chmod(0o755)
        def collect(profile,root=ROOT):
            cfg=beta.TARGETS[profile]
            data={}
            packages=[]
            for name in ("luci-app-adzero",*beta.NAMES):
                file=("luci-app-adzero-0.21.5-r1.apk" if name=="luci-app-adzero" else name+"-1-r1.apk")
                data["packages/"+file]=(profile+":"+name).encode()
                packages.append({"name":name,"file":file,
                                 "sha256":beta.sha256(data["packages/"+file]),
                                 "arch":"noarch" if name in ("luci-app-adzero","adblock-fast") else cfg["arch"]})
            data["profile.tsv"]=(f"istoreos\t25.12.6\t2026102312\t{cfg['target']}\t{cfg['arch']}\t{profile}\tapk\n").encode()
            data["manifest.json"]=(json.dumps({"release_tag":beta.RELEASE_TAG,
                "target":cfg["target"],"arch":cfg["arch"],"stable_approved":False,
                "default_enable":False,"packages":packages})+"\n").encode()
            data["SHA256SUMS"]="".join(f"{beta.sha256(data[n])}  {n}\n" for n in sorted(data)).encode()
            return data
        with mock.patch.object(beta,"collect",side_effect=collect):
            self.assets=beta.build(self.release,root=ROOT)
        self.script=self.release/"install-istoreos-beta.sh"

    def configure(self,profile):
        t=beta.TARGETS[profile]
        (self.router/"etc/openwrt_release").write_text(
            "DISTRIB_ID='iStoreOS'\nDISTRIB_RELEASE='25.12.6'\n"
            "DISTRIB_REVISION='2026102312'\n"
            f"DISTRIB_TARGET='{t['target']}'\nDISTRIB_ARCH='{t['arch']}'\n")
        if profile=="rockchip-r6xs":
            (self.router/"tmp/sysinfo/board_name").write_text("fastrhino,r6xs\n")

    def invoke(self,profile,*args,success=True,answers="",options=None):
        env={**os.environ,"PATH":str(self.bin)+":"+os.environ["PATH"],
            "ADZERO_BETA_TEST_ROOT":str(self.router),"ADZERO_BETA_TEST_MODE":"1",
            "MOCK_ROOT":str(self.router),
            "MOCK_ARCH":"x86_64" if profile=="x86_64" else "aarch64",
            "MOCK_APK_DB":str(self.router/"lib/apk/db/installed"),
            "MOCK_APK_LOG":str(self.apks),"MOCK_CTL_LOG":str(self.ctls),
            "MOCK_CURL_LOG":str(self.curls),"MOCK_RELEASE":str(self.release),
            **(options or {})}
        shell=shlex.split(os.environ.get("ADZERO_TEST_SHELL","sh"))
        r=subprocess.run(shell+[str(self.script),*args],input=answers,
                         env=env,capture_output=True,text=True,timeout=25)
        self.assertEqual(r.returncode==0,success,r.stdout+r.stderr)
        return r

    def test_three_profiles_menu_one_click_disabled_default_and_uninstall(self):
        for profile in beta.TARGETS:
            with self.subTest(profile=profile):
                self.configure(profile)
                self.assertIn("预检通过",self.invoke(profile,"--check","--local-dir",str(self.release)).stdout)
                self.assertFalse(self.ctls.exists())
                self.invoke(profile,"--local-dir",str(self.release),answers="2\ny\n0\n")
                self.assertTrue((self.router/"etc/adzero-beta/installed").exists())
                self.assertFalse(self.ctls.exists(), "Fresh beta install must not touch DNS controller")
                self.assertEqual((self.router/"etc/config/network").read_text(),"original-untouched")
                self.assertTrue(list((self.router/"etc/adzero-backups").glob("*/config.tar.gz")))
                self.invoke(profile,"--uninstall")
                self.assertIn("ctl:disable",self.ctls.read_text())
                self.assertFalse((self.router/"etc/adzero-beta/installed").exists())
                (self.router/"usr/libexec/adzero/ctl").unlink(missing_ok=True)
                (self.router/"etc/config/adzero").unlink(missing_ok=True)
                shutil.rmtree(self.router/"etc/adzero-beta")
                shutil.rmtree(self.router/"etc/adzero-backups")
                self.apks.unlink();self.ctls.unlink()

    def seed_untagged_apk(self, profile="x86_64"):
        self.configure(profile)
        self.invoke(profile, "--install", "--local-dir", str(self.release))
        (self.router / "etc/adzero-beta/installed").unlink()
        self.apks.unlink(missing_ok=True)
        self.ctls.unlink(missing_ok=True)

    def test_untagged_same_version_is_repaired_in_one_click_without_removing_old_package(self):
        for profile in beta.TARGETS:
            with self.subTest(profile=profile):
                self.seed_untagged_apk(profile)
                self.assertIn("无 Beta 标记", self.invoke(profile, "--status").stdout)
                result = self.invoke(profile, "--local-dir", str(self.release), answers="2\ny\n0\n")
                self.assertIn("安全修复完成", result.stdout)
                self.assertIn("ctl:disable", self.ctls.read_text())
                self.assertTrue((self.router/"etc/adzero-beta/installed").exists())
                actions = self.apks.read_text()
                self.assertIn("add --simulate --force-reinstall", actions)
                self.assertIn("add --force-reinstall --no-network", actions)
                # Exactly one app APK must be supplied to the reinstall path;
                # none of the six shared dependencies may be forcibly reinstalled.
                line = next(x for x in actions.splitlines() if " add --force-reinstall --no-network " in x)
                self.assertEqual(line.count(".apk"), 1)
                self.assertIn("luci-app-adzero-0.21.5-r1.apk", line)
                self.assertEqual((self.router/"etc/config/network").read_text(), "original-untouched")
                self.assertEqual((self.router/"lib/apk/db/installed").read_text().count("P:luci-app-adzero"), 1)
                self.invoke(profile, "--uninstall")
                (self.router/"etc/config/adzero").unlink(missing_ok=True)
                shutil.rmtree(self.router/"etc/adzero-beta")
                shutil.rmtree(self.router/"etc/adzero-backups")
                self.apks.unlink(missing_ok=True)
                self.ctls.unlink(missing_ok=True)

    def test_untagged_old_apk_can_be_safely_uninstalled_then_reinstalled_from_same_menu(self):
        self.seed_untagged_apk()
        result = self.invoke("x86_64", "--local-dir", str(self.release), answers="4\ny\n2\ny\n0\n")
        self.assertIn("安全卸载", result.stdout)
        self.assertIn("安装或安全修复完成", result.stdout)
        self.assertTrue((self.router/"etc/adzero-beta/installed").exists())
        self.assertFalse((self.router/"etc/adzero-beta/removed").exists())
        self.assertIn("ctl:disable", self.ctls.read_text())
        self.assertEqual((self.router/"etc/config/network").read_text(), "original-untouched")
        self.assertGreaterEqual(len(list((self.router/"etc/adzero-backups").glob("*/config.tar.gz"))), 3)

    def test_legacy_migration_fails_closed_on_unknown_owner_version_or_changed_dependency_plan(self):
        self.seed_untagged_apk()
        for extra in ({"MOCK_FOREIGN_OWNER":"1"},
                      {"MOCK_APP_VERSION":"0.22.0-r1"},
                      {"MOCK_REINSTALL_EXTRA":"1"},
                      {"MOCK_REINSTALL_FAIL":"1"}):
            with self.subTest(extra=extra):
                self.ctls.unlink(missing_ok=True)
                self.invoke("x86_64","--install","--local-dir",str(self.release),success=False,options=extra)
                self.assertFalse(self.ctls.exists(), "Failed read-only preflight must not disable prior DNS")
                self.assertFalse((self.router/"etc/adzero-beta/installed").exists())
        self.assertIn("P:luci-app-adzero",(self.router/"lib/apk/db/installed").read_text())

    def test_legacy_restore_failure_keeps_old_app_and_does_not_reinstall(self):
        self.seed_untagged_apk()
        (self.router/"etc/adzero").mkdir(exist_ok=True)
        (self.router/"etc/adzero/managed").write_text("active")
        result = self.invoke("x86_64","--install","--local-dir",str(self.release),
                             success=False,options={"MOCK_CTL_FAIL_DISABLE":"1"})
        self.assertIn("恢复 DNS/代理失败",result.stderr)
        self.assertTrue((self.router/"etc/adzero/managed").exists())
        self.assertIn("P:luci-app-adzero",(self.router/"lib/apk/db/installed").read_text())
        self.assertNotIn(" add --force-reinstall --no-network ",self.apks.read_text())
        self.assertFalse((self.router/"etc/adzero-beta/installed").exists())
        self.assertTrue(list((self.router/"etc/adzero-backups").glob("*/state.tar.gz")))

    def test_legacy_safe_uninstall_rejects_foreign_plan_and_keeps_network_untouched(self):
        self.seed_untagged_apk()
        self.invoke("x86_64","--uninstall",success=False,options={"MOCK_DEL_EXTRA":"1"})
        self.assertFalse(self.ctls.exists())
        self.assertIn("P:luci-app-adzero",(self.router/"lib/apk/db/installed").read_text())
        self.assertFalse((self.router/"etc/adzero-beta/removed").exists())

    def test_untagged_cross_version_cannot_upgrade_but_can_uninstall_with_owned_controller(self):
        self.seed_untagged_apk()
        self.invoke("x86_64","--install","--local-dir",str(self.release),
                    success=False,options={"MOCK_APP_VERSION":"0.20.3-r1"})
        result=self.invoke("x86_64","--uninstall",
                           options={"MOCK_APP_VERSION":"0.20.3-r1"})
        self.assertIn("已安全卸载",result.stdout)
        self.assertTrue((self.router/"etc/adzero-beta/removed").exists())

    def test_markerless_orphan_config_wrong_owner_and_broken_marker_never_get_removed(self):
        self.configure("x86_64")
        cfg=self.router/"etc/config/adzero"
        cfg.write_text("orphan-config")
        self.invoke("x86_64","--uninstall",success=False)
        self.invoke("x86_64","--install","--local-dir",str(self.release),success=False)
        self.assertFalse(self.ctls.exists())
        cfg.unlink()
        self.seed_untagged_apk()
        self.invoke("x86_64","--uninstall",success=False,options={"MOCK_FOREIGN_OWNER":"1"})
        marker=self.router/"etc/adzero-beta/installed"
        marker.write_text("tag=untrusted\nprofile=x86_64\ntarget=x86/64\n")
        self.invoke("x86_64","--uninstall",success=False)
        self.invoke("x86_64","--install","--local-dir",str(self.release),success=False)
        self.assertFalse(self.ctls.exists())

    def test_status_requires_no_download_and_old_beta_marker_is_not_overwritten(self):
        self.configure("x86_64")
        s=self.invoke("x86_64","--status")
        self.assertIn("未安装",s.stdout)
        self.assertFalse(self.curls.exists())
        self.invoke("x86_64","--install","--local-dir",str(self.release))
        marker=self.router/"etc/adzero-beta/installed"
        marker.write_text("tag=v0.21.5-istoreos-beta.3\nprofile=x86_64\ntarget=x86/64\n")
        self.apks.unlink(missing_ok=True)
        result=self.invoke("x86_64","--install","--local-dir",str(self.release))
        self.assertIn("无需重复安装",result.stdout)
        self.assertEqual(marker.read_text().splitlines()[0],"tag=v0.21.5-istoreos-beta.3")
        self.assertNotIn(" add ",self.apks.read_text())
        self.assertNotIn(" del ",self.apks.read_text())
    def test_stale_marker_temp_symlinks_cannot_overwrite_router_configuration(self):
        self.configure("x86_64")
        net=self.router/"etc/config/network"
        markdir=self.router/"etc/adzero-beta"
        markdir.mkdir(parents=True,exist_ok=True)
        (markdir/"installed.new").symlink_to(net)
        self.invoke("x86_64","--install","--local-dir",str(self.release))
        self.assertEqual(net.read_text(),"original-untouched")
        self.assertTrue((markdir/"installed").exists())
        self.curls.unlink(missing_ok=True)
        already=self.invoke("x86_64","--check")
        self.assertIn("未重新下载",already.stdout)
        self.assertFalse(self.curls.exists())
        (markdir/"removed.new").symlink_to(net)
        self.invoke("x86_64","--uninstall")
        self.assertEqual(net.read_text(),"original-untouched")
        self.assertTrue((markdir/"removed").exists())
        self.assertTrue((markdir/"installed.new").is_symlink())
        self.assertTrue((markdir/"removed.new").is_symlink())

    def test_wrong_revision_vendor_target_arch_and_r6xs_board_fail_closed(self):
        self.configure("armsr")
        path=self.router/"etc/openwrt_release"
        original=path.read_text()
        for needle,wrong in (("2026102312","2026102313"),("iStoreOS","ImmortalWrt"),
                             ("armsr/armv8","rockchip/armv8"),("aarch64_generic","x86_64")):
            with self.subTest(needle=needle):
                path.write_text(original.replace(needle,wrong))
                self.invoke("armsr","--check",success=False)
                self.assertFalse(self.curls.exists())
        path.write_text(original)
        self.configure("rockchip-r6xs")
        (self.router/"tmp/sysinfo/board_name").write_text("unrecognized,rockchip\n")
        self.invoke("rockchip-r6xs","--check",success=False)

    def test_mutated_tar_and_unsafe_dependency_simulation_rejected_before_install(self):
        self.configure("armsr")
        tar=self.release/"adzero-istoreos-armsr-beta.tar.gz"
        raw=tar.read_bytes()
        tar.write_bytes(raw+b"tampered")
        self.invoke("armsr","--install","--local-dir",str(self.release),success=False)
        self.assertFalse(self.ctls.exists())
        tar.write_bytes(raw)
        for extra in ("MOCK_EXTRA","MOCK_UPGRADE"):
            self.invoke("armsr","--install","--local-dir",str(self.release),
                        success=False,options={extra:"1"})
            self.assertFalse((self.router/"etc/adzero-beta/installed").exists())

    def test_explicit_enable_requires_ack_and_uninstall_requires_marker(self):
        self.configure("x86_64")
        self.invoke("x86_64","--install","--enable","--local-dir",str(self.release),success=False)
        init=self.router/"etc/init.d/adzero"
        init.parent.mkdir(parents=True,exist_ok=True)
        init.write_text("#!/bin/sh\necho init:$1 >> \"$MOCK_CTL_LOG\"\n")
        init.chmod(0o755)
        self.invoke("x86_64","--install","--enable","--accept-network-risk",
                    "--local-dir",str(self.release))
        self.assertIn("ctl:enable",self.ctls.read_text())
        self.assertIn("init:enable",self.ctls.read_text())
        self.assertIn("init:start",self.ctls.read_text())
        marker=self.router/"etc/adzero-beta/installed"
        marker.write_text("tag=wrong\nprofile=x86_64\n")
        self.invoke("x86_64","--uninstall",success=False)
        marker.write_text(f"tag={beta.RELEASE_TAG}\nprofile=x86_64\ntarget=x86/64\n")
        (self.router/"etc/adzero").mkdir(exist_ok=True)
        (self.router/"etc/adzero/managed").write_text("active")
        self.invoke("x86_64","--uninstall",success=False,
                    options={"MOCK_CTL_FAIL_DISABLE":"1"})
        self.assertTrue((self.router/"etc/adzero/managed").exists())
        self.assertIn("P:luci-app-adzero",(self.router/"lib/apk/db/installed").read_text())
        self.invoke("x86_64","--uninstall")
        self.assertFalse(marker.exists())

    def test_https_root_source_and_installed_app_barrier(self):
        self.configure("x86_64")
        self.invoke("x86_64","--check")
        self.assertIn("https://github.com/slobys/AdZero/releases/download/",self.curls.read_text())
        self.assertIn("--proto =https",self.curls.read_text())
        (self.router/"etc/config/adzero").write_text("already-in-use")
        self.invoke("x86_64","--install",success=False)
        self.assertFalse(self.ctls.exists())

    def test_beta2_archive_and_factory_source_evidence_preserves_prior_release(self):
        old = json.loads((ROOT/"docs/evidence/istoreos-25.12.6/public-beta-0.21.5-assets.json").read_text())
        new = json.loads((ROOT/"docs/evidence/istoreos-25.12.6/public-beta-0.21.5-beta2-assets.json").read_text())
        self.assertEqual(old["release_tag"], "v0.21.5-istoreos-beta.1")
        self.assertEqual(new["release_tag"], "v0.21.5-istoreos-beta.2")
        self.assertEqual(new["supersedes_beta"], old["release_tag"])
        self.assertEqual(new["app_apk_sha256"], old["app_apk_sha256"])
        self.assertEqual(new["app_package_source_sha256"], old["app_package_source_sha256"])
        self.assertFalse(new["public_stable_sdk_verified_matrix_changed"])
        self.assertFalse(new["automatic_enable"])
        self.assertEqual(new["physical_router_acceptance"], "not_run")
        self.assertEqual(len(new["archives"]), 3)
        self.assertNotEqual(new["installer"]["sha256"], old["installer"]["sha256"])
        self.assertEqual(len({x["sha256"] for x in new["archives"]}), 3)

    def test_beta3_apk_source_and_deps_remain_identical_to_beta2(self):
        old=json.loads((ROOT/"docs/evidence/istoreos-25.12.6/public-beta-0.21.5-beta2-assets.json").read_text())
        new=json.loads((ROOT/"docs/evidence/istoreos-25.12.6/public-beta-0.21.5-beta3-assets.json").read_text())
        self.assertEqual(old["release_tag"],"v0.21.5-istoreos-beta.2")
        self.assertEqual(new["release_tag"],"v0.21.5-istoreos-beta.3")
        self.assertEqual(new["supersedes_beta"],old["release_tag"])
        self.assertEqual(new["app_apk_sha256"],old["app_apk_sha256"])
        self.assertEqual(new["app_package_source_sha256"],old["app_package_source_sha256"])
        self.assertEqual(new["vendor_source_commit"],old["vendor_source_commit"])
        self.assertEqual(new["physical_device_test"],"not_run")
        self.assertFalse(new["public_stable_sdk_verified_matrix_changed"])
        self.assertFalse(new["automatic_enable"])
        self.assertRegex(new["installer"]["sha256"],r"^[a-f0-9]{64}$")
        self.assertNotEqual(new["installer"]["sha256"],old["installer"]["sha256"])
        previous={row["profile"]:row for row in old["archives"]}
        self.assertEqual(set(previous),{row["profile"] for row in new["archives"]})
        for item in new["archives"]:
            prev=previous[item["profile"]]
            self.assertEqual(item["factory_image_sha256"],prev["factory_image_sha256"])
            self.assertEqual(item["dependency_count"],prev["dependency_count"])
            self.assertRegex(item["sha256"],r"^[a-f0-9]{64}$")
            self.assertNotEqual(item["sha256"],prev["sha256"])
    def test_beta4_release_evidence_pinned_to_only_new_install_channel(self):
        previous=json.loads((ROOT/"docs/evidence/istoreos-25.12.6/public-beta-0.21.5-beta3-assets.json").read_text())
        new=json.loads((ROOT/"docs/evidence/istoreos-25.12.6/public-beta-0.21.5-beta4-assets.json").read_text())
        auto=(ROOT/"scripts/install-auto.sh").read_text()
        guide=(ROOT/"docs/RELEASE_ISTOREOS_BETA_0.21.5_BETA4.md").read_text()
        self.assertEqual(new["release_tag"],beta.RELEASE_TAG)
        self.assertEqual(new["supersedes_beta"],previous["release_tag"])
        self.assertEqual((new["release"],new["revision"]),("25.12.6","2026102312"))
        self.assertEqual(new["app_apk_sha256"],previous["app_apk_sha256"])
        self.assertEqual(new["app_package_source_sha256"],previous["app_package_source_sha256"])
        self.assertEqual(new["old_beta_installer_sha256"],previous["installer"]["sha256"])
        self.assertEqual({row["profile"] for row in new["archives"]},set(beta.TARGETS))
        for row in new["archives"]:
            spec=beta.TARGETS[row["profile"]]
            self.assertEqual((row["target"],row["arch"]),(spec["target"],spec["arch"]))
            self.assertEqual(row["dependency_count"],6)
            self.assertRegex(row["sha256"],r"^[0-9a-f]{64}$")
        self.assertRegex(new["installer"]["sha256"],r"^[0-9a-f]{64}$")
        self.assertIn(new["installer"]["sha256"],auto)
        self.assertIn(new["release_tag"]+"/install-istoreos-beta.sh",auto)
        self.assertNotIn(previous["installer"]["sha256"],auto)
        self.assertTrue(new["security"]["stable_sdk_verified_unchanged"])
        self.assertTrue(new["security"]["cross_version_upgrade_forbidden"])
        self.assertFalse(new["security"]["default_filtering_enabled"])
        self.assertEqual(new["physical_router_acceptance"],"not_run")
        guest=new["real_factory_guest"]
        self.assertEqual(guest["status"],"passed_real_offline_guest_install_reinstall_uninstall")
        self.assertTrue(guest["new_beta4_single_app_real_force_reinstall_passed"])
        self.assertTrue(guest["new_beta4_real_apk_uninstall_passed"])
        self.assertFalse(guest["guest_reboot_tested"])
        self.assertFalse(guest["guest_live_dns_proxy_tested"])
        self.assertIn("Beta.4",guide)

    def test_archive_pins_deterministic_and_non_semver_beta(self):
        self.assertEqual(self.assets["release_tag"],"v0.21.5-istoreos-beta.4")
        self.assertTrue(self.assets["production_verified_matrix_unchanged"])
        code=self.script.read_text()
        self.assertNotIn("@SHA_",code)
        self.assertNotIn("@RELEASE_TAG@",code)
        for name,digest in self.assets["assets"].items():
            self.assertEqual(hashlib.sha256((self.release/name).read_bytes()).hexdigest(),digest)


    def test_old_beta1_install_still_allows_safe_uninstall_from_beta2(self):
        for profile in ("x86_64", "armsr", "rockchip-r6xs"):
            with self.subTest(profile=profile):
                self.configure(profile)
                self.invoke(profile, "--install", "--local-dir", str(self.release))
                marker = self.router / "etc/adzero-beta/installed"
                marker.write_text(
                    "tag=v0.21.5-istoreos-beta.1\n"
                    f"profile={profile}\n"
                    f"target={beta.TARGETS[profile]['target']}\n")
                self.invoke(profile, "--uninstall")
                self.assertFalse(marker.exists())
                self.assertIn("ctl:disable", self.ctls.read_text())
                (self.router / "usr/libexec/adzero/ctl").unlink(missing_ok=True)
                (self.router / "etc/config/adzero").unlink(missing_ok=True)
                shutil.rmtree(self.router / "etc/adzero-beta")
                shutil.rmtree(self.router / "etc/adzero-backups")
                self.apks.unlink()
                self.ctls.unlink()

    def test_stale_opkg_and_relocated_apk_db_still_allow_safe_preflight(self):
        # Actual report came from iStoreOS 25.12.6 at the auto-installer
        # gate. The real APK query, not stale OPKG file names, is decisive.
        self.configure("x86_64")
        old = self.router/"usr/lib/opkg/status"
        old.parent.mkdir(parents=True)
        old.write_text("Package: old-opkg-remnant\n")
        live_db = self.router/"tmp/real-apk-installed"
        (self.router/"lib/apk/db/installed").replace(live_db)
        result = self.invoke(
            "x86_64", "--check", "--local-dir", str(self.release),
            options={"MOCK_APK_DB":str(live_db)})
        self.assertIn("预检通过", result.stdout)
        self.assertTrue(old.exists())
        self.assertEqual(live_db.read_text().count("P:tcpdump"),1)
        self.assertFalse(self.ctls.exists())
        self.assertFalse((self.router/"etc/adzero-beta/installed").exists())
        live_db.write_text(live_db.read_text().replace("P:tcpdump\n",""))
        denied = self.invoke(
            "x86_64","--check","--local-dir",str(self.release),success=False,
            options={"MOCK_APK_DB":str(live_db)})
        self.assertIn("原厂组件 tcpdump",denied.stderr)

    def test_beta2_previous_install_marker_uninstalls_safely_from_beta3(self):
        self.configure("x86_64")
        self.invoke("x86_64", "--install", "--local-dir", str(self.release))
        marker=self.router/"etc/adzero-beta/installed"
        marker.write_text("tag=v0.21.5-istoreos-beta.2\nprofile=x86_64\ntarget=x86/64\n")
        self.invoke("x86_64","--uninstall")
        self.assertFalse(marker.exists())
        self.assertIn("ctl:disable",self.ctls.read_text())

    def test_r6xs_symlinked_board_name_is_not_device_attestation(self):
        profile = "rockchip-r6xs"
        self.configure(profile)
        board = self.router / "tmp/sysinfo/board_name"
        board.unlink()
        original = self.router / "tmp/sysinfo/fake-board"
        original.write_text("fastrhino,r6xs\n")
        board.symlink_to(original)
        self.invoke(profile, "--check", success=False)
        self.assertFalse(self.curls.exists())
        self.assertFalse(self.apks.exists())


if __name__=="__main__":
    unittest.main()
