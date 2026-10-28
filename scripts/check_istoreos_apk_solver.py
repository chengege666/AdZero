#!/usr/bin/env python3
"""Offline original-firmware APK solver. Never installs on host or router."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

from check_istoreos_dependencies import closure
from inspect_istoreos_arm64_image import RAW_IMAGES
from probe_istoreos_arm64 import PROFILES

INSTALL = re.compile(r"^\(\d+/\d+\) Installing ([a-zA-Z0-9_.+-]+) \(([^)]+)\)$", re.M)
CHANGES = re.compile(r"\b(Removing|Purging|Upgrading|Downgrading|Reinstalling)\b", re.I)
DATABASE = ("lib/apk/db/installed", "lib/apk/db/scripts.tar.gz",
            "lib/apk/db/triggers", "etc/apk/world", "etc/apk/arch")


def digest(path):
    with Path(path).open("rb") as reader:
        return hashlib.file_digest(reader, "sha256").hexdigest()


def parse_changes(output, expected):
    if CHANGES.search(output):
        raise ValueError("APK would change an already-installed firmware package")
    installed = [match.group(1) for match in INSTALL.finditer(output)]
    if (len(installed) != len(expected) or len(installed) != len(set(installed))
            or set(installed) != set(expected) or "OK:" not in output):
        raise ValueError(f"APK simulation changed expected dependency set: {installed!r} versus {sorted(expected)!r}")
    return installed


def verify(source, image, profile):
    if profile not in PROFILES:
        raise ValueError("Only exact iStoreOS ARM64 vendor profiles are supported")
    source, image = Path(source), Path(image)
    report = closure(source, image, profile=profile)
    if (report.get("publishable") is not False or
            report.get("closure") != "passed_vendor_builds_only" or
            report.get("vendor_profile") != profile):
        raise ValueError("Original native dependency closure is incomplete")
    packages = {report["apk"]: report["apk_sha256"],
                **{entry["file"]: entry["sha256"]
                   for entry in report["missing_from_original_firmware"].values()}}
    if len(packages) != 1 + len(report["missing_from_original_firmware"]):
        raise ValueError("Vendor package name conflict")
    source = source.resolve()
    source_packages = source / "bin/packages" / report["arch"]
    local = []
    for name, sha in sorted(packages.items()):
        if not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise ValueError("Invalid source package checksum")
        matches = [path for path in source_packages.glob(f"*/{name}")
                   if path.is_file() and not path.is_symlink()
                   and not path.parent.is_symlink()]
        if len(matches) != 1 or digest(matches[0]) != sha:
            raise ValueError(f"Missing, duplicate or modified vendor dependency {name}")
        local.append(str(matches[0].resolve()))
    with tempfile.TemporaryDirectory(prefix="adzero-istore-solver-") as temp:
        root = Path(temp)
        for item in DATABASE:
            dest = root / item
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(subprocess.check_output([
                "unsquashfs", "-offset", str(RAW_IMAGES[profile]["squashfs_offset"]),
                "-cat", str(image.resolve()), item], timeout=90))
        db = root / "lib/apk/db/installed"
        before = digest(db)
        host_apk = source / "staging_dir/host/bin/apk"
        if not host_apk.is_file() or host_apk.is_symlink():
            raise ValueError("Official vendor host apk-tools executable missing")
        args = [str(host_apk), "--root", str(root), "--arch", report["arch"],
                "add", "--simulate", "--no-network",
                "--repositories-file", "/dev/null", "--allow-untrusted", *local]
        result = subprocess.run(args, text=True, capture_output=True, timeout=120)
        if result.returncode:
            raise ValueError(f"Offline APK solver failed: {result.stderr[-600:]}")
        planned = parse_changes(result.stdout,
                                set(report["missing_from_original_firmware"]) | {"luci-app-adzero"})
        if digest(db) != before:
            raise ValueError("APK simulation modified installed firmware database")
    return {
        "firmware": "istoreos", "release": report["release"],
        "revision": report["revision"], "vendor_profile": profile,
        "target": report["target"], "arch": report["arch"],
        "original_image_sha256": report["image_raw_sha256"],
        "native_apk_sha256": report["apk_sha256"],
        "native_source_sha256": report["source_sha256"],
        "vendor_source_commit": report["vendor_source_commit"],
        "missing_vendor_dependencies": report["missing_from_original_firmware"],
        "installed_packages_simulated": planned,
        "packages_simulated": len(planned),
        "offline_solver": "passed_no_network",
        "existing_firmware_package_removals": 0,
        "original_full_tcpdump_preserved": True,
        "original_db_unchanged": True,
        "device_acceptance": "not_run", "publishable": False,
        "scope": "host apk-tools --simulate on disposable original firmware database; no actual router install or LAN DNS test",
    }


def main():
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("--source", type=Path, required=True)
    arg.add_argument("--image", type=Path, required=True)
    arg.add_argument("--profile", choices=tuple(PROFILES), required=True)
    arg.add_argument("--output", type=Path)
    a = arg.parse_args()
    try:
        raw = json.dumps(verify(a.source, a.image, a.profile), ensure_ascii=False, indent=2) + "\n"
        if a.output:
            if a.output.exists() or a.output.is_symlink():
                raise ValueError("Refuse to overwrite existing solver evidence")
            a.output.write_text(raw, encoding="utf-8", newline="\n")
        print(raw, end="")
    except (ValueError, OSError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired) as error:
        arg.exit(1, f"iStoreOS original APK solver refused: {error}\n")


if __name__ == "__main__":
    main()
