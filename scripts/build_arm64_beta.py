#!/usr/bin/env python3
"""Build opt-in, independently pinned OpenWrt/ImmortalWrt ARM64 test packages.

Only four APKs compiled by the matching official/vendor SDK are accepted.
Does not widen the stable sdk_verified matrix or modify existing Releases.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile

from build_ipk import version
from build_sdk import source_hash

ROOT = Path(__file__).resolve().parents[1]
TAG = "v0.21.5-arm64-beta.1"
SOURCE_SHA = "8df7589827fdc1adc418c3b83887097589b257a4a7654ac0dd91ddf878ee60c9"
PACKAGE = "luci-app-adzero-0.21.5-r1.apk"
EVIDENCE = ROOT / "docs/evidence/arm64-pr10-sdk-builds.json"
SDK_CANDIDATES = ROOT / ".sdk/arm64-firmware-verification"
HEX = re.compile(r"[a-f0-9]{64}\Z")
TARGETS = {
    "openwrt-rockchip": ("openwrt", "25.12.6", "rockchip/armv8", "aarch64_generic",
                         "adzero-openwrt-25.12.6-rockchip-armv8"),
    "openwrt-filogic": ("openwrt", "25.12.6", "mediatek/filogic", "aarch64_cortex-a53",
                        "adzero-openwrt-25.12.6-mediatek-filogic"),
    "immortalwrt-rockchip": ("immortalwrt", "25.12.2", "rockchip/armv8", "aarch64_generic",
                             "adzero-candidate-immortalwrt-25.12.2-rockchip-armv8"),
    "immortalwrt-filogic": ("immortalwrt", "25.12.2", "mediatek/filogic", "aarch64_cortex-a53",
                            "adzero-candidate-immortalwrt-25.12.2-mediatek-filogic"),
}
DEPENDENCIES = frozenset(("adblock-fast", "ca-bundle", "conntrack", "coreutils-timeout",
                          "curl", "libc", "luci-base", "rpcd-mod-file", "rpcd-mod-ucode",
                          "tcpdump", "ucode", "ucode-mod-fs", "ucode-mod-socket",
                          "ucode-mod-ubus", "ucode-mod-uci", "ucode-mod-uloop"))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def collect(profile, *, root=ROOT):
    if profile not in TARGETS:
        raise ValueError("Unknown exact ARM64 vendor SDK profile")
    if version() != "0.21.5-r1" or source_hash(root / "luci-app-adzero") != SOURCE_SHA:
        raise ValueError("Original source version or hash changed; rebuild candidate SDKs")
    fw, release, target, arch, artifact = TARGETS[profile]
    artifact_dir = root / ".sdk/arm64-firmware-verification" / artifact
    evidence = json.loads((root / "docs/evidence/arm64-pr10-sdk-builds.json").read_text(encoding="utf-8"))
    if (evidence.get("adzero_package_source_sha256") != SOURCE_SHA or
            evidence.get("device_acceptance") != "not_run" or
            evidence.get("public_release") is not False):
        raise ValueError("Untrusted CI metadata provenance")
    rows = [item for item in evidence.get("artifacts", [])
            if item.get("artifact_name") == artifact]
    if len(rows) != 1:
        raise ValueError("Missing or ambiguous exact verified vendor APK artifact")
    row = rows[0]
    if any((row.get(key) != expected) for key, expected in (
        ("firmware", fw), ("release", release), ("target", target),
        ("arch", arch), ("package", PACKAGE), ("sdk_build", "passed"),
        ("payload_checks", "passed"), ("sdk_origin_verified", True),
        ("artifact_package_checksum_match", True))):
        raise ValueError("CI artifact is not verified for the exact target SDK")
    if row.get("sdk_archive_sha256") is None or not HEX.fullmatch(row["sdk_archive_sha256"]):
        raise ValueError("Original SDK archive checksum missing")
    package = artifact_dir / PACKAGE
    manifest = artifact_dir / "build-manifest.json"
    if (package.is_symlink() or manifest.is_symlink()
            or not package.is_file() or not manifest.is_file()):
        raise ValueError("Verified compiled APK or build-manifest missing")
    m = json.loads(manifest.read_text(encoding="utf-8"))
    expected = {
        "firmware_declared": fw, "release_declared": release,
        "target_observed": target, "package_arch_observed": arch,
        "package_format": "apk", "source_sha256": SOURCE_SHA,
        "sdk_archive_sha256_supplied": row["sdk_archive_sha256"],
        "sdk_build": "passed", "package": PACKAGE, "sha256": row["apk_sha256"],
    }
    if any(m.get(k) != v for k, v in expected.items()):
        raise ValueError("SDK manifest target or build provenance mismatched")
    if m.get("target_declared") != target or not m.get("vendor_sdk_origin_verified"):
        raise ValueError("SDK manifest does not attest matching original vendor SDK")
    if not HEX.fullmatch(row["apk_sha256"]):
        raise ValueError("Compiled package SHA missing")
    data = package.read_bytes()
    if not 1000 < len(data) < 24 * 1024 * 1024 or sha(data) != row["apk_sha256"]:
        raise ValueError("Real SDK APK is missing or has changed")
    return {
        "profile": profile, "firmware": fw, "release": release,
        "target": target, "arch": arch, "format": "apk", "package": PACKAGE,
        "source_sha256": SOURCE_SHA, "sdk_archive_sha256": row["sdk_archive_sha256"],
        "sdk_apk_sha256": row["apk_sha256"], "verified_real_sdk": True,
        "expected_package_dependencies": sorted(DEPENDENCIES),
        "channel": "explicit_opt_in_public_arm64_beta",
        "default_enable": False, "physical_router_acceptance": "not_run",
        "production_sdk_verified": False,
    }, data


def archive(files):
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, compresslevel=9, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for path in sorted(files):
                contents = files[path]
                info = tarfile.TarInfo(path)
                info.size = len(contents)
                info.mtime = 0
                info.mode = 0o644
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                tar.addfile(info, io.BytesIO(contents))
    return buffer.getvalue()


def make_bundle(profile, *, root=ROOT):
    manifest, package = collect(profile, root=root)
    meta = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    profile_tsv = ("\t".join((manifest["firmware"], manifest["release"], manifest["target"],
                              manifest["arch"], manifest["profile"], manifest["format"]))+"\n").encode()
    items = {"packages/" + PACKAGE: package, "manifest.json": meta,
             "profile.tsv": profile_tsv}
    items["SHA256SUMS"] = "".join(f"{sha(items[key])}  {key}\n"
                                 for key in sorted(items)).encode()
    return archive(items)


def build(output, *, root=ROOT):
    output = Path(output)
    if output.is_symlink() or not output.is_dir():
        raise ValueError("Output must exist and not be a symlink")
    assets = {}
    for profile in TARGETS:
        name = f"adzero-{profile}-arm64-beta.tar.gz"
        content = make_bundle(profile, root=root)
        path = output / name
        if path.exists() or path.is_symlink():
            raise ValueError("Refusing to overwrite a released candidate package")
        path.write_bytes(content)
        assets[name] = sha(content)
    installer_text = (root / "scripts/install_arm64_beta.sh").read_text(encoding="utf-8")
    installer_text = installer_text.replace("@RELEASE_TAG@", TAG)
    for profile in TARGETS:
        installer_text = installer_text.replace("@SHA_"+profile.upper().replace("-", "_")+"@",
                                                assets[f"adzero-{profile}-arm64-beta.tar.gz"])
    if "@SHA_" in installer_text or "@RELEASE_TAG@" in installer_text:
        raise ValueError("Unresolved pinned beta installer checksum template")
    script = output / "install-arm64-beta.sh"
    if script.exists() or script.is_symlink():
        raise ValueError("Refusing to overwrite installer asset")
    script.write_text(installer_text, encoding="utf-8", newline="\n")
    script.chmod(0o755)
    assets[script.name] = sha(script.read_bytes())
    (output / "SHA256SUMS").write_text(
        "".join(f"{assets[name]}  {name}\n" for name in sorted(assets)),
        encoding="utf-8", newline="\n")
    return {"release_tag": TAG, "assets": assets,
            "four_original_vendor_sdk_candidates": True,
            "separate_from_stable_sdk_verified": True,
            "physical_router_acceptance": "not_run"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    opts = parser.parse_args()
    try:
        print(json.dumps(build(opts.output), indent=2, ensure_ascii=False))
    except (ValueError, OSError) as err:
        parser.exit(1, f"OpenWrt/ImmortalWrt ARM64 beta refused: {err}\n")
