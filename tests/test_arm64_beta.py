"""Public OpenWrt/ImmortalWrt ARM64 beta: isolated install lifecycle and guardrails.

No tests execute a real package manager operation on the host or a router.
The four true SDK binary checks happen separately in maintainer build release.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_arm64_beta as beta


class Arm64BetaInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="adzero-owrt-imm-arm64-beta-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.release = self.base / "release"
        self.release.mkdir()
        self.router = self.base / "router"
        for path in ("etc/config", "etc/apk/repositories.d", "lib/apk/db", "tmp"):
            (self.router / path).mkdir(parents=True, exist_ok=True)
        self.network = self.router / "etc/config/network"
        self.network.write_text("original-network-untouched")
        self.db = self.router / "lib/apk/db/installed"
        self.db.write_text("P:rpcd\nP:luci-base\nP:tcpdump-mini\nP:curl\n")
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.operations = self.base / "apk-operations.log"
        self.ctl_log = self.base / "ctl.log"
        self.curl_log = self.base / "curl.log"
        self.apkmock = self.bin / "apk"
        self.apkmock.write_text("""#!/bin/sh
if [ "$1" = --print-arch ]; then echo "$MOCK_ARCH"; exit 0; fi
echo "$*" >> "$MOCK_APK_LOG"
case " $* " in
  *" update "*)
    case "$*" in *" --repositories-file "*) ;; *) echo unpinned-repo-update >&2; exit 97 ;; esac
    [ "$MOCK_UPDATE_FAIL" != 1 ] || exit 4
    echo 'OK: official vendor signed indices refreshed'; exit 0 ;;
  *" add --simulate --no-network "*)
    [ "$MOCK_NEED_REPO" != 1 ] || exit 3 ;;
  *" add --simulate --allow-untrusted "*)
    case "$*" in *" --repositories-file "*) ;; *) echo unpinned-repo-use >&2; exit 96 ;; esac ;;
  *" add --no-network "*)
    mkdir -p "$MOCK_ROOT/usr/libexec/adzero"
    echo 'P:luci-app-adzero' >> "$MOCK_ROOT/lib/apk/db/installed"
    cat > "$MOCK_ROOT/usr/libexec/adzero/ctl" <<'EOCTL'
#!/bin/sh
echo "ctl:$1" >> "$MOCK_CTL_LOG"
EOCTL
    chmod +x "$MOCK_ROOT/usr/libexec/adzero/ctl"; exit 0 ;;
  *" add --allow-untrusted "*)
    case "$*" in *" --repositories-file "*) ;; *) echo unpinned-install >&2; exit 96 ;; esac
    mkdir -p "$MOCK_ROOT/usr/libexec/adzero"
    echo 'P:luci-app-adzero' >> "$MOCK_ROOT/lib/apk/db/installed"
    cat > "$MOCK_ROOT/usr/libexec/adzero/ctl" <<'EOCTL'
#!/bin/sh
echo "ctl:$1" >> "$MOCK_CTL_LOG"
EOCTL
    chmod +x "$MOCK_ROOT/usr/libexec/adzero/ctl"; exit 0 ;;
  *" del luci-app-adzero "*)
    sed -i '/^P:luci-app-adzero$/d' "$MOCK_ROOT/lib/apk/db/installed"; exit 0 ;;
  *) echo unexpected-command >&2; exit 98 ;;
esac
echo '(1/3) Installing adblock-fast (1.2.4-r4)'
echo '(2/3) Installing conntrack (1.4.8-r1)'
echo '(3/3) Installing luci-app-adzero (0.21.5-r1)'
if [ "$MOCK_EXTRA" = 1 ]; then echo '(4/4) Installing unknown-external-package (1-r1)'; fi
if [ "$MOCK_UPGRADE" = 1 ]; then echo 'Upgrading tcpdump-mini (5.0)'; fi
echo 'OK: 520 MiB in 1025 packages'
""")
        self.apkmock.chmod(0o755)
        curl = self.bin / "curl"
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
[ -n "$url" ] && [ -n "$out" ] || exit 5
cp "$MOCK_RELEASE/$(basename "$url")" "$out"
""")
        curl.chmod(0o755)

        def fixture(profile, root=ROOT):
            fw, release, target, arch, _artifact = beta.TARGETS[profile]
            content = (profile + "-sdk-bytecode").encode() * 88
            package = "luci-app-adzero-0.21.5-r1.apk"
            manifest = {
                "firmware": fw, "release": release, "target": target, "arch": arch,
                "profile": profile, "format": "apk", "package": package,
                "source_sha256": beta.SOURCE_SHA, "sdk_archive_sha256": "f"*64,
                "sdk_apk_sha256": beta.sha(content), "verified_real_sdk": True,
                "expected_package_dependencies": sorted(beta.DEPENDENCIES),
                "channel": "explicit_opt_in_public_arm64_beta",
                "default_enable": False, "physical_router_acceptance": "not_run",
                "production_sdk_verified": False,
            }
            data = {
                "packages/" + package: content,
                "manifest.json": (json.dumps(manifest)+"\n").encode(),
                "profile.tsv": ("\t".join((fw,release,target,arch,profile,"apk"))+"\n").encode(),
            }
            data["SHA256SUMS"] = "".join(f"{beta.sha(data[n])}  {n}\n" for n in sorted(data)).encode()
            return beta.archive(data)
        with mock.patch.object(beta, "make_bundle", side_effect=fixture):
            self.built = beta.build(self.release, root=ROOT)
        self.installer = self.release / "install-arm64-beta.sh"

    def configure(self, profile):
        fw, release, target, arch, _ = beta.TARGETS[profile]
        id_name = "OpenWrt" if fw == "openwrt" else "ImmortalWrt"
        (self.router / "etc/openwrt_release").write_text(
            f"DISTRIB_ID='{id_name}'\nDISTRIB_RELEASE='{release}'\n"
            f"DISTRIB_TARGET='{target}'\nDISTRIB_ARCH='{arch}'\n"
        )
        domain = "downloads.openwrt.org" if fw == "openwrt" else "downloads.immortalwrt.org"
        (self.router / "etc/apk/repositories.d/distfeeds.list").write_text(
            f"https://{domain}/releases/25.12/targets/{target}/packages/packages.adb\n"
            f"https://{domain}/releases/25.12/packages/{arch}/base/packages.adb\n"
        )

    def run_cli(self, profile, *args, ok=True, answers="", options=None):
        env = {
            **os.environ, "PATH": str(self.bin)+":"+os.environ["PATH"],
            "MOCK_ROOT": str(self.router),
            "ADZERO_ARM64_BETA_TEST_ROOT": str(self.router),
            "ADZERO_ARM64_BETA_TEST_MODE": "1",
            "MOCK_ARCH": "aarch64",
            "MOCK_APK_LOG": str(self.operations),
            "MOCK_CTL_LOG": str(self.ctl_log),
            "MOCK_CURL_LOG": str(self.curl_log),
            "MOCK_RELEASE": str(self.release),
            **(options or {}),
        }
        shell = shlex.split(os.environ.get("ADZERO_TEST_SHELL", "sh"))
        completed = subprocess.run(
            shell+[str(self.installer), *args], input=answers,
            capture_output=True, text=True, env=env, timeout=35
        )
        self.assertEqual(completed.returncode == 0, ok, completed.stdout+completed.stderr)
        return completed

    def test_four_profiles_menu_install_defaults_disabled_then_uninstall(self):
        for profile in beta.TARGETS:
            with self.subTest(profile=profile):
                self.configure(profile)
                result = self.run_cli(profile, "--check", "--local-dir", str(self.release))
                self.assertIn("检查通过", result.stdout)
                self.assertFalse(self.ctl_log.exists())
                self.run_cli(profile, "--local-dir", str(self.release), answers="2\ny\n0\n")
                marker = self.router/"etc/adzero-arm64-beta/installed"
                self.assertTrue(marker.is_file())
                self.assertFalse(self.ctl_log.exists(), "First beta install must not control DNS")
                self.assertTrue(list((self.router/"etc/adzero-backups").glob("*/config.tar.gz")))
                self.assertEqual(self.network.read_text(), "original-network-untouched")
                self.run_cli(profile, "--uninstall")
                self.assertIn("ctl:disable", self.ctl_log.read_text())
                self.assertFalse(marker.exists())
                self.assertIn(" del luci-app-adzero\n", self.operations.read_text())
                (self.router/"usr/libexec/adzero/ctl").unlink()
                self.operations.unlink()
                self.ctl_log.unlink()
                shutil.rmtree(self.router/"etc/adzero-backups")

    def test_wrong_firmware_release_target_arch_refuses_before_fetch(self):
        self.configure("openwrt-rockchip")
        file = self.router/"etc/openwrt_release"
        raw = file.read_text()
        for old,new in (("25.12.6","25.12.5"), ("OpenWrt","ImmortalWrt"),
                        ("rockchip/armv8","mediatek/filogic"),
                        ("aarch64_generic","x86_64")):
            with self.subTest(old=old):
                file.write_text(raw.replace(old,new))
                self.run_cli("openwrt-rockchip", "--check", ok=False)
                self.assertFalse(self.curl_log.exists())
                self.assertFalse(self.operations.exists())
        file.write_text(raw)

    def test_official_repo_only_and_unknown_archive_digest_refused(self):
        profile = "immortalwrt-filogic"
        self.configure(profile)
        file = self.router/"etc/apk/repositories.d/distfeeds.list"
        original = file.read_text()
        for feed in (original+"\nhttps://evil.com/packages.adb\n",
                     original.replace("downloads.immortalwrt.org","downloads.openwrt.org"),
                     original.replace("25.12","24.10"),
                     original.replace("aarch64_cortex-a53","x86_64")):
            with self.subTest(feed=feed[-40:]):
                file.write_text(feed)
                self.run_cli(profile, "--check", "--local-dir", str(self.release),
                             ok=False, options={"MOCK_NEED_REPO":"1"})
                if self.operations.exists():
                    self.assertNotIn(" update ", self.operations.read_text())
                    self.operations.unlink()
        file.write_text(original)
        self.run_cli(profile, "--check", "--local-dir", str(self.release),
                     options={"MOCK_NEED_REPO":"1"})
        self.assertIn(" update\n", self.operations.read_text())
        self.assertIn("--repositories-file", self.operations.read_text())

        bundle = self.release/"adzero-immortalwrt-filogic-arm64-beta.tar.gz"
        digest = bundle.read_bytes()
        bundle.write_bytes(digest+b"tampered")
        self.operations.unlink()
        self.run_cli(profile, "--install", "--local-dir", str(self.release), ok=False)
        self.assertFalse(self.operations.exists())

    def test_simulator_rejects_removal_upgrade_and_repository_errors(self):
        profile = "openwrt-filogic"
        self.configure(profile)
        for settings in ({"MOCK_UPGRADE":"1"}, {"MOCK_EXTRA":"1"}):
            # Extra installs from an otherwise trusted repository are allowed;
            # any attempt to replace tcpdump or an existing package is refused.
            ok = "MOCK_EXTRA" in settings
            self.run_cli(profile, "--check", "--local-dir", str(self.release), ok=ok,
                         options=settings)
            self.assertFalse((self.router/"etc/adzero-arm64-beta/installed").exists())
            self.operations.unlink()

        self.run_cli(profile, "--check", "--local-dir", str(self.release),
                     ok=False, options={"MOCK_NEED_REPO":"1","MOCK_UPDATE_FAIL":"1"})
        self.assertFalse((self.router/"etc/adzero-arm64-beta/installed").exists())

    def test_enable_requires_explicit_ack_and_retains_restore_guard(self):
        profile = "openwrt-rockchip"
        self.configure(profile)
        self.run_cli(profile, "--install", "--enable", "--local-dir", str(self.release),ok=False)
        self.assertFalse(self.ctl_log.exists())
        init = self.router/"etc/init.d/adzero"
        init.parent.mkdir(parents=True, exist_ok=True)
        init.write_text("#!/bin/sh\necho init:$1 >> \"$MOCK_CTL_LOG\"\n")
        init.chmod(0o755)
        self.run_cli(profile, "--install", "--enable", "--accept-network-risk",
                     "--local-dir", str(self.release))
        self.assertIn("ctl:enable",self.ctl_log.read_text())
        self.assertIn("init:enable",self.ctl_log.read_text())
        marker = self.router/"etc/adzero-arm64-beta/installed"
        marker.write_text("tag=old\nprofile=wrong\n")
        self.run_cli(profile, "--uninstall",ok=False)
        marker.write_text(f"tag={beta.TAG}\nprofile={profile}\ntarget=rockchip/armv8\n")
        (self.router/"etc/adzero").mkdir(exist_ok=True)
        (self.router/"etc/adzero/managed").write_text("managed")
        self.run_cli(profile, "--uninstall",ok=False)
        (self.router/"etc/adzero/managed").unlink()
        self.run_cli(profile, "--uninstall")
        self.assertFalse(marker.exists())

    def test_https_asset_selects_correct_firmware_and_preserves_stable_updates(self):
        profile = "immortalwrt-rockchip"
        self.configure(profile)
        self.run_cli(profile,"--check")
        log = self.curl_log.read_text()
        self.assertIn("https://github.com/slobys/AdZero/releases/download/",log)
        self.assertIn("--proto =https",log)
        (self.router/"etc/config/adzero").write_text("older-owner")
        self.run_cli(profile,"--install",ok=False)
        self.assertFalse(self.ctl_log.exists())
        self.assertFalse((self.router/"etc/adzero-arm64-beta/installed").exists())

    def test_deterministic_source_record_and_public_release_exclusion(self):
        self.assertEqual(self.built["release_tag"], beta.TAG)
        self.assertEqual(beta.TAG, "v0.21.5-arm64-beta.2")
        self.assertRegex(beta.TAG,r"^v0\.21\.5-arm64-beta\.\d+$")
        self.assertFalse(self.built["physical_router_acceptance"] != "not_run")
        code = self.installer.read_text()
        self.assertNotIn("@SHA_",code)
        self.assertNotIn("@RELEASE_TAG@",code)
        for name, digest in self.built["assets"].items():
            self.assertEqual(hashlib.sha256((self.release/name).read_bytes()).hexdigest(),digest)
        matrix = json.loads((ROOT/"docs/compatibility-matrix.json").read_text())
        self.assertEqual(len(matrix["sdk_verified"]),5)
        self.assertTrue(all(row["firmware"]!="istoreos" for row in matrix["sdk_verified"]))


    def test_beta2_assets_exact_hashes_and_previous_release_unchanged(self):
        record = json.loads((ROOT / "docs/evidence/arm64-public-beta-0.21.5-beta2-assets.json").read_text())
        previous = json.loads((ROOT / "docs/evidence/arm64-public-beta-0.21.5-assets.json").read_text())
        self.assertEqual(record["release_tag"], beta.TAG)
        self.assertEqual(record["supersedes_beta"], previous["release_tag"])
        self.assertEqual(record["installer"]["name"], "install-arm64-beta.sh")
        self.assertTrue(record["installer"]["sha256"].isalnum())
        self.assertFalse(record["production_sdk_verified_modified"])
        self.assertTrue(record["stable_release_v0_21_5_unmodified"])
        self.assertEqual(record["physical_router_acceptance"], "not_run")
        self.assertEqual(
            {x["profile"]: x["asset_sha256"] for x in record["vendor_artifacts"]},
            {x["profile"]: x["asset_sha256"] for x in previous["vendor_artifacts"]},
            "Original SDK-native APK archive bytes must not change")
        with self.subTest(release=beta.TAG):
            self.assertIn("v0.21.5-arm64-beta.2", self.installer.read_text())

    def test_four_public_beta_asset_records_match_original_sdk_build_evidence(self):
        recorded=json.loads((ROOT/"docs/evidence/arm64-public-beta-0.21.5-assets.json").read_text())
        ci=json.loads((ROOT/"docs/evidence/arm64-pr10-sdk-builds.json").read_text())
        # Keep the already published beta.1 evidence immutable while building beta.2.
        self.assertEqual(recorded["release_tag"],"v0.21.5-arm64-beta.1")
        self.assertEqual(recorded["physical_router_acceptance"],"not_run")
        self.assertFalse(recorded["production_sdk_verified_modified"])
        self.assertTrue(recorded["stable_release_v0_21_5_unmodified"])
        self.assertEqual(len(recorded["vendor_artifacts"]),4)
        self.assertEqual(ci["adzero_package_source_sha256"],beta.SOURCE_SHA)
        matches={p["profile"]:p for p in recorded["vendor_artifacts"]}
        self.assertEqual(set(matches),set(beta.TARGETS))
        for profile,(fw,version,target,arch,ci_name) in beta.TARGETS.items():
            with self.subTest(profile=profile):
                entry=matches[profile]
                original=next(x for x in ci["artifacts"] if x["artifact_name"]==ci_name)
                self.assertEqual(entry["firmware"],fw)
                self.assertEqual(entry["release"],version)
                self.assertEqual(entry["target"],target)
                self.assertEqual(entry["arch"],arch)
                self.assertEqual(entry["sdk_archive_sha256"],original["sdk_archive_sha256"])
                self.assertEqual(entry["sdk_apk_sha256"],original["apk_sha256"])
                self.assertEqual(entry["asset"],f"adzero-{profile}-arm64-beta.tar.gz")
                self.assertRegex(entry["asset_sha256"],r"^[0-9a-f]{64}$")
                self.assertTrue(original["sdk_origin_verified"])
                self.assertEqual(original["sdk_build"],"passed")
                self.assertEqual(original["payload_checks"],"passed")


    def test_official_and_ustc_repositories_match_exact_firmware_and_abi(self):
        """Real-world Chinese mirrors are safe only for the same vendor/target."""
        for profile, (fw, release, target, arch, _) in beta.TARGETS.items():
            with self.subTest(profile=profile):
                self.configure(profile)
                feeds = self.router / "etc/apk/repositories.d/distfeeds.list"
                source = feeds.read_text()
                official = ("downloads.openwrt.org" if fw == "openwrt"
                            else "downloads.immortalwrt.org")
                mirror = "mirrors.ustc.edu.cn/" + fw
                paths = (
                    source,
                    source.replace("https://" + official, "https://" + mirror),
                    source.replace("/releases/25.12/", "/releases/" + release + "/"),
                )
                for selected in paths:
                    with self.subTest(feed=selected.splitlines()[0]):
                        feeds.write_text(selected)
                        self.operations.unlink(missing_ok=True)
                        self.run_cli(profile, "--check", "--local-dir", str(self.release),
                                     options={"MOCK_NEED_REPO": "1"})
                        self.assertIn(" update\n", self.operations.read_text())
                        self.assertNotIn(" add --no-network ", self.operations.read_text())
                        self.assertEqual(self.network.read_text(), "original-network-untouched")
                bad = (
                    source.replace("/releases/25.12/", "/releases/25.12.1/"),
                    source.replace("/releases/25.12/", "/releases/25.12.0-rc3/"),
                    source.replace("/releases/25.12/", "/snapshots/"),
                    source.replace(official, "unknown.invalid"),
                    source.replace(official, "downloads.openwrt.org" if fw != "openwrt"
                                   else "downloads.immortalwrt.org"),
                    source.replace("https://" + official, "https://mirrors.ustc.edu.cn/"
                                   + ("immortalwrt" if fw == "openwrt" else "openwrt")),
                    source.replace("/releases/25.12/", "/releases/25.12/../"),
                    source.replace("/releases/25.12/", "/releases/25.12//"),
                    source.replace("packages/" + arch + "/base", "packages/x86_64/base"),
                    source.splitlines()[0] + "\n" + source.splitlines()[0] + "\n",
                    source.splitlines()[1] + "\n" + source.splitlines()[1] + "\n",
                    source.splitlines()[0] + "\n"
                        + source.splitlines()[1].replace("/releases/25.12/",
                                                          "/releases/" + release + "/") + "\n",
                )
                for selected in bad:
                    with self.subTest(rejected=selected[:90]):
                        feeds.write_text(selected)
                        self.operations.unlink(missing_ok=True)
                        self.run_cli(profile, "--check", "--local-dir", str(self.release),
                                     ok=False, options={"MOCK_NEED_REPO": "1"})
                        self.assertNotIn(" update\n", self.operations.read_text())
                feeds.write_text(source)

    def test_prior_beta_installation_can_be_safely_uninstalled(self):
        profile = "immortalwrt-filogic"
        self.configure(profile)
        self.run_cli(profile, "--install", "--local-dir", str(self.release))
        marker = self.router / "etc/adzero-arm64-beta/installed"
        marker.write_text(
            "tag=v0.21.5-arm64-beta.1\n"
            "profile=immortalwrt-filogic\n"
            "target=mediatek/filogic\n"
        )
        self.run_cli(profile, "--uninstall")
        self.assertFalse(marker.exists())
        self.assertIn("ctl:disable", self.ctl_log.read_text())


if __name__ == "__main__":
    unittest.main()
