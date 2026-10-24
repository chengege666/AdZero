#!/usr/bin/env python3
"""Build with an already downloaded, verified vendor SDK on Linux/WSL.

No router installation, feed replacement, firmware download or publishing.
Prepare the SDK's own feeds before invoking this entry point.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from build_ipk import version

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "luci-app-adzero"


def source_hash(directory):
    digest = hashlib.sha256()
    # WindowsPath sorts case-insensitively; use identical POSIX names everywhere.
    for path in sorted(directory.rglob("*"), key=lambda item: item.relative_to(directory).as_posix()):
        if path.is_symlink():
            raise ValueError("Package sources may not contain symlinks")
        if path.is_file():
            digest.update(path.relative_to(directory).as_posix().encode() + b"\0")
            digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def prepare(sdk, package=PACKAGE):
    sdk = sdk.resolve()
    if os.name == "nt":
        raise ValueError("Run the vendor SDK under Linux/WSL, outside /mnt/c for builds")
    for path in ("rules.mk", "Makefile", "scripts/config/Makefile", "feeds/luci/luci.mk",
                 "package/feeds/packages/adblock-fast/Makefile", "package/feeds/luci/luci-base/Makefile"):
        if not (sdk / path).is_file():
            raise ValueError(f"SDK prerequisite missing: {path}; prepare this SDK's matching feeds first")
    destination = sdk / "package/luci-app-adzero"
    ownership = sdk / "adzero-source-sha256.txt"
    if destination.is_symlink():
        raise ValueError("Refusing to replace a package symlink")
    if destination.exists():
        if source_hash(destination) != source_hash(package):
            if not ownership.exists() or ownership.read_text().strip() != source_hash(destination):
                raise ValueError("SDK contains different AdZero sources; use a fresh SDK or review that directory")
            old_files = {p.relative_to(destination) for p in destination.rglob("*") if p.is_file()}
            new_files = {p.relative_to(package) for p in package.rglob("*") if p.is_file()}
            if old_files - new_files:
                raise ValueError("Source files were removed; use a fresh SDK to avoid stale payloads")
            shutil.copytree(package, destination, dirs_exist_ok=True)
    else:
        # No recursive deletion or replacement of an existing SDK package.
        shutil.copytree(package, destination)
    # Windows mounts may expose every file as 0777; normalize the entire payload.
    destination.chmod(0o755)
    for path in destination.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    for name in ("ctl", "probe", "adapter", "backend", "watch", "policy", "sources", "job", "routing-data", "cache-curl/curl", "observe", "dns-handoff", "dns-enhance", "dns-native", "dns-guard"):
        (destination / "root/usr/libexec/adzero" / name).chmod(0o755)
    (destination / "root/etc/init.d/adzero").chmod(0o755)
    (destination / "root/etc/init.d/adzero-dns").chmod(0o755)
    ownership.write_text(source_hash(destination) + "\n")
    return destination


def read_config(sdk):
    result = {}
    for line in (sdk / ".config").read_text().splitlines():
        if line.startswith("CONFIG_") and "=" in line:
            key, value = line.split("=", 1)
            result[key] = value.strip('"')
    return result


def build(sdk, firmware, release, target, package_format, sdk_sha256, output):
    if not re.fullmatch(r"[a-fA-F0-9]{64}", sdk_sha256):
        raise ValueError("Provide the SHA-256 of the vendor SDK archive verified before extraction")
    sdk = sdk.resolve()
    destination = prepare(sdk)
    package_source_hash = source_hash(destination)
    # OpenWrt's scripts/config is Kconfig source, not Linux's scripts/config CLI.
    config_path = sdk / ".config"
    lines = config_path.read_text().splitlines() if config_path.exists() else []
    lines = [line for line in lines if not line.startswith(("CONFIG_PACKAGE_luci-app-adzero=", "# CONFIG_PACKAGE_luci-app-adzero "))]
    config_path.write_text("\n".join(lines + ["CONFIG_PACKAGE_luci-app-adzero=m"]) + "\n")
    for argv in (["make", "defconfig"], ["make", "package/feeds/luci/luci-base/host/compile", "V=s", "-j2"],
                 ["make", "package/luci-app-adzero/compile", "V=s", "-j2"]):
        subprocess.run(argv, cwd=sdk, check=True)
    config = read_config(sdk)
    if source_hash(destination) != package_source_hash:
        raise ValueError("SDK package sources changed during the build; repeat with a stable source tree")
    actual_target = "/".join(filter(None, (config.get("CONFIG_TARGET_BOARD"), config.get("CONFIG_TARGET_SUBTARGET"))))
    if actual_target and actual_target != target:
        raise ValueError(f"SDK target {actual_target} differs from requested {target}")
    use_apk = config.get("CONFIG_USE_APK")
    if use_apk is not None and (use_apk == "y") != (package_format == "apk"):
        raise ValueError("SDK package format differs from requested format")
    expected_version = re.escape(version())
    pattern = re.compile(r"^luci-app-adzero[_-]" + expected_version + r"(?:_[a-zA-Z0-9_+-]+)?\." + package_format + r"$")
    built = sorted(path for path in (sdk / "bin/packages").rglob("luci-app-adzero*." + package_format) if pattern.fullmatch(path.name))
    if len(built) != 1:
        raise ValueError(f"Expected one {package_format} package, found {len(built)}; use a clean SDK output")
    output = output.resolve()
    if output == sdk or output.is_relative_to(sdk):
        raise ValueError("Keep exported artifacts outside the SDK")
    output.mkdir(parents=True, exist_ok=True)
    package = built[0]
    content = package.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    final = output / package.name
    if final.exists() and final.read_bytes() != content:
        raise ValueError("Output package already exists with different contents")
    final.write_bytes(content)
    report = {
        "firmware_declared": firmware, "release_declared": release,
        "target_declared": target, "target_observed": actual_target or None,
        "package_arch_observed": config.get("CONFIG_TARGET_ARCH_PACKAGES"),
        "package_format": package_format, "sdk_archive_sha256_supplied": sdk_sha256.lower(),
        "source_sha256": package_source_hash, "package": package.name, "sha256": sha,
        "sdk_build": "passed", "device_acceptance": "not_run",
    }
    (output / "build-manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", required=True, type=Path)
    parser.add_argument("--firmware", choices=("openwrt", "immortalwrt", "istoreos"), required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--format", choices=("ipk", "apk"), required=True)
    parser.add_argument("--sdk-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = build(args.sdk, args.firmware, args.release, args.target, args.format, args.sdk_sha256, args.output)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
