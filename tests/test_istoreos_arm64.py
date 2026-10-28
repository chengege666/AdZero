"""ARM64 iStoreOS exact official profile and vendor APK candidate boundaries.

Fixtures have fake bytes; only explicit SDK/build validation can authorize a
public release, never these tests or firmware metadata alone.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import probe_istoreos_arm64 as probe
import prepare_istoreos_source as prepare
import inspect_istoreos_candidate as inspect
import build_istoreos_native as builder
from build_sdk import PACKAGE
from build_ipk import version


class IstoreArm64ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self, profile):
        original = probe.PROFILES[profile]
        names = ["packages", "luci", "routing", "telephony"] + [
            f"vendor_{i}" for i in range(original["feeds"] - 4)
        ]
        feeds = {name: f"{i + 1:040x}" for i, name in enumerate(names)}
        data = {
            "commit.buildinfo": (original["commit_prefix"] + "\n").encode(),
            "config.buildinfo": (
                'CONFIG_VERSION_DIST="iStoreOS"\n' +
                "\n".join(original["target_config"]) + "\n"
            ).encode(),
            "feeds.buildinfo": ("".join(
                f"src-git {name} https://github.com/jjm2473/{name}.git^{sha}\n"
                for name, sha in feeds.items()
            )).encode(),
            "feeds.conf": b"src-include defaults feeds.conf.default\n",
            "version.latest.v2": (
                f'[{original["image"]}]({original["image"]})\n'
                f'SHA256: {original["image_sha256"]}\n'
            ).encode(),
        }
        spec = {**original, "metadata_sha256": {
            name: hashlib.sha256(raw).hexdigest() for name, raw in data.items()
        }}
        def read(url):
            self.assertTrue(url.startswith(spec["origin"]))
            return data[url.removeprefix(spec["origin"])]
        return spec, data, feeds, read

    def test_exact_vendor_profiles_are_unique_and_never_publishable(self):
        for profile in probe.PROFILES:
            with self.subTest(profile=profile):
                spec, data, feeds, read = self.fixture(profile)
                with mock.patch.dict(probe.PROFILES, {profile: spec}):
                    result = probe.validate_metadata(profile, read)
                    self.assertEqual(result["vendor_profile"], profile)
                    self.assertEqual(result["target"], spec["target"])
                    self.assertEqual(result["vendor_feed_count"], spec["feeds"])
                    self.assertFalse(result["publishable"])
                    self.assertEqual(result["sdk_build"], "not_run")
                    self.assertEqual(result["device_acceptance"], "not_run")
                    self.assertEqual(len(feeds), spec["feeds"])

    def test_drift_or_cross_profile_metadata_is_rejected(self):
        for profile in probe.PROFILES:
            with self.subTest(profile=profile):
                spec, data, _, read = self.fixture(profile)
                with mock.patch.dict(probe.PROFILES, {profile: spec}):
                    def bad_feeds(url):
                        value = read(url)
                        return value + b"tampered" if url.endswith("feeds.buildinfo") else value
                    with self.assertRaisesRegex(ValueError, "checksum"):
                        probe.validate_metadata(profile, bad_feeds)
                    def wrong_target(url):
                        value = read(url)
                        return value.replace(b'CONFIG_VERSION_DIST="iStoreOS"',
                                             b'CONFIG_VERSION_DIST="OpenWrt"') if url.endswith("config.buildinfo") else value
                    # Even after updating a forged digest, target identity still fails.
                    forged = dict(spec)
                    forged["metadata_sha256"] = {**spec["metadata_sha256"],
                        "config.buildinfo": hashlib.sha256(wrong_target(spec["origin"] + "config.buildinfo")).hexdigest()}
                    with mock.patch.dict(probe.PROFILES, {profile: forged}):
                        with self.assertRaisesRegex(ValueError, "target configuration"):
                            probe.validate_metadata(profile, wrong_target)
        with self.assertRaisesRegex(ValueError, "Unrecognized"):
            probe.profile_spec("r6xs-as-x86")

    def test_preparation_uses_only_its_own_vendor_feeds(self):
        for profile in probe.PROFILES:
            with self.subTest(profile=profile):
                spec, data, feeds, read = self.fixture(profile)
                dest = self.root / profile
                calls = []
                def git(argv, check):
                    self.assertTrue(check)
                    calls.append(argv)
                    if "checkout" in argv:
                        (dest / "scripts").mkdir(parents=True, exist_ok=True)
                        (dest / "rules.mk").write_text("rules")
                        (dest / "scripts/feeds").write_text("fixture")
                with mock.patch.dict(probe.PROFILES, {profile: spec}):
                    report = prepare.prepare(dest, profile=profile, fetch=read,
                        run=git, check_output=lambda *_a, **_kw: probe.SOURCE_COMMIT)
                self.assertEqual(report["vendor_feed_count"], len(feeds))
                self.assertEqual(report["vendor_profile"], profile)
                self.assertEqual((dest / ".config").read_bytes(), data["config.buildinfo"])
                self.assertEqual(len((dest / "feeds.conf").read_text().splitlines()), len(feeds))
                self.assertEqual(len(calls), 3)
                self.assertFalse(report["publishable"])

    def test_native_arm64_candidate_requires_correct_target_and_provenance(self):
        profile = "rockchip-r6xs"
        spec, data, feeds, read = self.fixture(profile)
        source = self.root / "rockchip"
        source.mkdir()
        for name, commit in feeds.items():
            (source / "feeds" / name).mkdir(parents=True)
        (source / "feeds.conf").write_bytes(data["feeds.buildinfo"])
        with mock.patch.dict(probe.PROFILES, {profile: spec}):
            evidence = probe.validate_metadata(profile, read)
        (source / "adzero-source-provenance.json").write_text(json.dumps(evidence))
        (source / ".config").write_text(
            'CONFIG_VERSION_DIST="iStoreOS"\n'
            f'CONFIG_TARGET_BOARD="{spec["target"].split("/")[0]}"\n'
            f'CONFIG_TARGET_SUBTARGET="{spec["target"].split("/")[1]}"\n'
            f'CONFIG_TARGET_ARCH_PACKAGES="{spec["arch"]}"\n'
            'CONFIG_USE_APK=y\nCONFIG_PACKAGE_luci-app-adzero=m\n'
        )
        shutil.copytree(PACKAGE, source / "package/luci-app-adzero")
        apktool = source / "staging_dir/host/bin/apk"
        apktool.parent.mkdir(parents=True)
        apktool.write_text("#!/bin/sh\nexit 0\n")
        apktool.chmod(0o755)
        native = source / "bin/packages" / spec["arch"] / "vendor" / f"luci-app-adzero-{version()}.apk"
        native.parent.mkdir(parents=True)
        native.write_bytes(b"arm64 candidate fixture")
        def git(argv, text):
            self.assertTrue(text)
            if argv[2] == str(source):
                return probe.SOURCE_COMMIT
            return feeds[Path(argv[2]).name]
        inspect_payload = lambda *_args, **_kw: {
            "runtime_source_and_modes": "passed",
            "luci_delivered_ui_regressions": "passed",
        }
        with mock.patch.dict(probe.PROFILES, {profile: spec}):
            result = inspect.validate(source, run=git, package_inspector=inspect_payload)
            self.assertEqual(result["target_observed"], "rockchip/armv8")
            self.assertEqual(result["package_arch_observed"], "aarch64_generic")
            self.assertEqual(result["vendor_feeds_checked"]["feed_count"], 15)
            self.assertFalse(result["publishable"])
            self.assertNotEqual(result["sdk_build"], "passed")
            output = self.root / "candidate"
            exported = inspect.export(source, output, run=git,
                                      package_inspector=inspect_payload)
            self.assertEqual(exported["sha256"], hashlib.sha256(native.read_bytes()).hexdigest())
            # A different ARM64 ABI is not interchangeable with this vendor target.
            config = source / ".config"
            config.write_text(config.read_text().replace("aarch64_generic", "aarch64_cortex-a53"))
            with self.assertRaisesRegex(ValueError, "configuration"):
                inspect.validate(source, run=git, package_inspector=inspect_payload)
            # A valid source cannot authorize another firmware profile.
            config.write_text(config.read_text().replace("aarch64_cortex-a53", "aarch64_generic"))
            evidence["vendor_profile"] = "armsr"
            (source / "adzero-source-provenance.json").write_text(json.dumps(evidence))
            with self.assertRaisesRegex(ValueError, "ARM64 vendor provenance"):
                inspect.validate(source, run=git, package_inspector=inspect_payload)


if __name__ == "__main__":
    unittest.main()
