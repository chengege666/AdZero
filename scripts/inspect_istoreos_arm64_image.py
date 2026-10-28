#!/usr/bin/env python3
"""Inspect official iStoreOS ARM64 original images without mounting or booting.

Raw hashes and SquashFS offsets are independently pinned after verifying the
official compressed images in probe_istoreos_arm64.py. This only reads files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from probe_istoreos_arm64 import PROFILES, FIRMWARE_RELEASE, FIRMWARE_REVISION

RAW_IMAGES = {
    "armsr": {
        "bytes": 2550431744,
        "sha256": "c46658d6f9a4b1d6d45b2da25f0eee0d188a7a625cdc200a59eb7af1a4f78128",
        "squashfs_offset": 134479872,
    },
    "rockchip-r6xs": {
        "bytes": 354419200,
        "sha256": "c89326ee924f41d10921570d3da1b7caf22be13a275be7bd9bd830e0f21c8ec8",
        "squashfs_offset": 84934656,
    },
}
REQUIRED_PACKAGES = frozenset({"luci-base", "rpcd", "tcpdump"})
PACKAGE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]*")


def file_sha256(path):
    with Path(path).open("rb") as reader:
        return hashlib.file_digest(reader, "sha256").hexdigest()


def inspect_image(image, profile, *, run=subprocess.check_output):
    if profile not in PROFILES or profile not in RAW_IMAGES:
        raise ValueError("Unsupported iStoreOS ARM64 original-image profile")
    path = Path(image)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Pinned iStoreOS raw firmware image missing or symlinked")
    pinned = RAW_IMAGES[profile]
    if path.stat().st_size != pinned["bytes"] or file_sha256(path) != pinned["sha256"]:
        raise ValueError("iStoreOS raw firmware image SHA-256/length differs from pinned official image")
    spec = PROFILES[profile]
    args = ["unsquashfs", "-offset", str(pinned["squashfs_offset"]),
            "-cat", str(path.resolve())]
    release_raw = run([*args, "etc/openwrt_release"])
    database_raw = run([*args, "lib/apk/db/installed"])
    if not isinstance(release_raw, bytes) or not isinstance(database_raw, bytes):
        raise ValueError("Original firmware readers must return raw bytes")
    if len(release_raw) > 16 * 1024 or not 128 <= len(database_raw) <= 8 * 1024 * 1024:
        raise ValueError("Invalid official firmware release or APK database size")
    expected_keys = ("DISTRIB_ID", "DISTRIB_RELEASE", "DISTRIB_REVISION",
                     "DISTRIB_TARGET", "DISTRIB_ARCH")
    release = {}
    for line in release_raw.decode("utf-8").splitlines():
        for key in expected_keys:
            if line.startswith(key + "="):
                if key in release:
                    raise ValueError("Duplicate iStoreOS firmware identity field")
                value = line[len(key) + 1:]
                if len(value) < 2 or value[0] not in ("'", '"') or value[-1] != value[0]:
                    raise ValueError("Malformed original firmware identity")
                release[key] = value[1:-1]
    expected = {
        "DISTRIB_ID": "iStoreOS",
        "DISTRIB_RELEASE": FIRMWARE_RELEASE,
        "DISTRIB_REVISION": FIRMWARE_REVISION,
        "DISTRIB_TARGET": spec["target"],
        "DISTRIB_ARCH": spec["arch"],
    }
    if release != expected:
        raise ValueError("Official iStoreOS raw firmware identity/target/ABI differs")
    installed = set()
    for line in database_raw.decode("utf-8").splitlines():
        if line.startswith("P:"):
            name = line[2:]
            if not PACKAGE_NAME.fullmatch(name) or name in installed:
                raise ValueError("Invalid or duplicate installed firmware package")
            installed.add(name)
    if not 250 <= len(installed) <= 25000 or not REQUIRED_PACKAGES.issubset(installed):
        raise ValueError("Original firmware package database is incomplete")
    evidence = {
        "firmware": "istoreos",
        "release": FIRMWARE_RELEASE,
        "revision": FIRMWARE_REVISION,
        "vendor_profile": profile,
        "target": spec["target"],
        "arch": spec["arch"],
        "official_image_archive": spec["image"],
        "official_image_archive_sha256": spec["image_sha256"],
        "verified_raw_image_sha256": pinned["sha256"],
        "verified_raw_image_bytes": pinned["bytes"],
        "squashfs_offset_bytes": pinned["squashfs_offset"],
        "original_preinstalled_package_count": len(installed),
        "preinstalled_tcpdump_full": "tcpdump" in installed,
        "provenance_check": "passed_exact_official_firmware",
        "device_acceptance": "not_run",
        "publishable": False,
        "scope": "original immutable firmware image; not a device installation or LAN test",
    }
    return installed, evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(RAW_IMAGES), required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        _installed, report = inspect_image(args.image, args.profile)
        encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            if args.output.is_symlink() or args.output.exists():
                raise ValueError("Evidence output already exists or is a symlink")
            args.output.write_text(encoded, encoding="utf-8", newline="\n")
        print(encoded, end="")
    except (OSError, ValueError, UnicodeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"iStoreOS original-image inspection refused: {error}\n")


if __name__ == "__main__":
    main()
