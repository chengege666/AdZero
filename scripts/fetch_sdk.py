#!/usr/bin/env python3
"""Download and extract pinned official SDKs into an isolated Linux directory."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import urllib.request

PINS = {
    "24.10.8": ("openwrt-sdk-24.10.8-x86-64_gcc-13.3.0_musl.Linux-x86_64.tar.zst", "ac4a0405d2eea821b06f93c14ba13ffa90ad0457648903df7dde02570027ab21"),
    "25.12.5": ("openwrt-sdk-25.12.5-x86-64_gcc-14.3.0_musl.Linux-x86_64.tar.zst", "0c8df0151a1e88feb7c03d694d61f6a18d51872815b7c811d76e2b77504d5e9c"),
}
TARGET_PINS = {
    ("25.12.5", "rockchip/armv8"): ("openwrt-sdk-25.12.5-rockchip-armv8_gcc-14.3.0_musl.Linux-x86_64.tar.zst", "59194a023968398af64bfa7d8bc3eac322641f6dc9cdbade28a4d9dd41866eba"),
}

# Exact official ImmortalWrt SDK names and SHA-256 from the vendor's
# releases/<version>/targets/x86/64/sha256sums, never OpenWrt SDK aliases.
IMMORTALWRT_PINS = {
    ("24.10.6", "x86/64"): (
        "immortalwrt-sdk-24.10.6-x86-64_gcc-13.3.0_musl.Linux-x86_64.tar.zst",
        "709bea2ce466b7ad671ce00fdcb1eb69b2b3fa0f0921b12b620725d95cd8c0e5",
    ),
    ("25.12.2", "x86/64"): (
        "immortalwrt-sdk-25.12.2-x86-64_gcc-14.3.0_musl.Linux-x86_64.tar.zst",
        "4d4631f134c2f27215a91aa7ef5bf9a01ea96c2450d3b8a5c38048c32462ac60",
    ),
}

SDK_MIRRORS = {
    "openwrt": "https://downloads.openwrt.org",
    "immortalwrt": "https://downloads.immortalwrt.org",
}


def sdk_pin(release, target="x86/64", firmware="openwrt"):
    try:
        if firmware == "immortalwrt":
            return IMMORTALWRT_PINS[(release, target)]
        if firmware == "openwrt":
            return PINS[release] if target == "x86/64" else TARGET_PINS[(release, target)]
    except KeyError as error:
        raise ValueError(f"No pinned SDK for {firmware} {release} {target}") from error
    raise ValueError(f"No independently verified vendor SDK: {firmware} {release} {target}")


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(release, directory, cache, zstd, target_name="x86/64", firmware="openwrt"):
    filename, expected = sdk_pin(release, target_name, firmware)
    url = f"{SDK_MIRRORS[firmware]}/releases/{release}/targets/{target_name}/{filename}"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / filename
    if not archive.exists():
        staging = archive.with_suffix(".partial")
        with urllib.request.urlopen(url, timeout=60) as source, staging.open("wb") as output:
            downloaded = 0
            while chunk := source.read(4 * 1024 * 1024):
                output.write(chunk)
                downloaded += len(chunk)
                if downloaded % (32 * 1024 * 1024) == 0:
                    print(f"{release}: downloaded {downloaded // 1048576} MiB", flush=True)
        if sha256(staging) != expected:
            raise ValueError("SDK archive checksum mismatch")
        staging.replace(archive)
    if sha256(archive) != expected:
        raise ValueError("Cached SDK archive checksum mismatch")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename.removesuffix(".tar.zst")
    if not target.exists():
        entries = subprocess.check_output(["tar", "--use-compress-program", zstd, "-tf", str(archive)], text=True).splitlines()
        for name in entries:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != target.name:
                raise ValueError("SDK archive contains an unexpected path")
        subprocess.run(["tar", "--use-compress-program", zstd, "--no-same-owner", "-xf", str(archive), "-C", str(directory)], check=True)
    report = {"firmware": firmware, "release": release, "target": target_name, "url": url, "sha256": expected, "sdk": str(target.resolve())}
    (target / "adzero-sdk-origin.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware", choices=tuple(SDK_MIRRORS), default="openwrt")
    parser.add_argument("--release", required=True)
    parser.add_argument("--target", choices=("x86/64", "rockchip/armv8"), default="x86/64")
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--zstd", default=shutil.which("zstd") or "zstd")
    args = parser.parse_args()
    print(json.dumps(fetch(args.release, args.directory, args.cache, args.zstd, args.target, args.firmware), indent=2))


if __name__ == "__main__":
    main()
