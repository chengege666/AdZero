#!/usr/bin/env python3
"""Verify iStoreOS 24.10.8 native OPKG IPK install against original image DB.

Runs the ACTUAL OPKG and musl libraries extracted from the SHA-pinned factory
x86 image, against disposable installed status and all original .list files
for the requested target. Installs nothing. Does not modify any router.
Requires three native vendor Buildroot packages to have completed first.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from build_istoreos_24108_beta import (
    ROOT, PROFILES, APP_NAME, SOURCE_SHA, TAG, validated_bundle,
    ipk_control, digest,
)

OFFSETS = {"x86_64": 134742016, "armsr": 134479872, "r6xs": 84934656}
INFO_TOOL_LIBS = (
    ("bin/opkg", "opkg"),
    ("lib/libc.so", "ld-musl-x86_64.so.1"),
    ("lib/libubox.so.20240329", "libubox.so.20240329"),
    ("lib/libgcc_s.so.1", "libgcc_s.so.1"),
)
# Original iStoreOS OPKG version names legitimately contain ~ (ucode).
NAME = re.compile(r"[a-zA-Z0-9_.+~-]+\Z")


def run_original(*argv, timeout=95, **kwargs):
    return subprocess.run(argv, check=True, timeout=timeout, **kwargs)


def unpack_original(root, image, offset, paths):
    args = ("unsquashfs", "-offset", str(offset), "-d", str(root), str(image), *paths)
    run_original(*args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)


def read_original(image, offset, path):
    result = run_original("unsquashfs", "-offset", str(offset), "-cat",
                          str(image), path, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=45)
    if not result.stdout:
        raise ValueError(f"Original factory image is missing {path}")
    return result.stdout


def validate(profile, *, root=ROOT):
    if profile not in PROFILES:
        raise ValueError("Unsupported factory original-image profile")
    profile_spec = PROFILES[profile]
    # Compiled IPK MUST come from original pinned 24.10 Buildroot, not a
    # developer preview, a 25.12 APK or a different target vendor SDK.
    original_files = validated_bundle(profile, root=root)
    if len(original_files) != 11 or "packages/" + APP_NAME not in original_files:
        raise ValueError("Expected original native one IPK + seven vendor dependencies")
    package_set = {}
    for key, blob in original_files.items():
        if not key.startswith("packages/"):
            continue
        name = key.removeprefix("packages/")
        control = ipk_control_bytes(blob)
        if not NAME.fullmatch(name.removesuffix(".ipk")) or not name.endswith(".ipk"):
            raise ValueError("Unexpected native OPKG package filename")
        if control.get("Architecture") not in ("all", profile_spec["arch"]):
            raise ValueError("Original vendor IPK has incompatible architecture")
        pkg = control.get("Package")
        if not pkg or not NAME.fullmatch(pkg) or pkg in package_set:
            raise ValueError("Duplicate or malformed native OPKG package")
        if name != f"{pkg}_{control.get('Version')}_{control.get('Architecture')}.ipk":
            raise ValueError("Native OPKG filename, header and package version differ")
        package_set[pkg] = (name, blob)
    deps = ("adblock-fast", "conntrack", "coreutils-timeout",
            "libnetfilter-cthelper0", "libnetfilter-cttimeout1",
            "libnetfilter-queue1", "ucode-mod-socket")
    expected_names = {"luci-app-adzero", *deps}
    if set(package_set) != expected_names:
        raise ValueError("Vendor native OPKG dependency closure incomplete")
    images = root / ".sdk/istoreos-24108-official-images"
    manifest = json.loads((images / "original-image-report.json").read_text())
    original = manifest[profile]
    image = images / original["raw_filename"]
    if (original["raw_sha256"] != profile_spec["raw_sha"] or
            original["gzip_sha256"] != profile_spec["image_sha"] or
            original["squashfs_offsets"] != [OFFSETS[profile]]):
        raise ValueError("Factory image provenance mismatch")

    x86_report = manifest["x86_64"]
    x86_image = images / x86_report["raw_filename"]
    with tempfile.TemporaryDirectory(prefix="adzero-original-opkg-solver-") as scratch:
        work = Path(scratch)
        program = work / "tools"
        program.mkdir()
        for origin, name in INFO_TOOL_LIBS:
            data = read_original(x86_image, OFFSETS["x86_64"], origin)
            path = program / name
            path.write_bytes(data)
            path.chmod(0o755 if name in ("opkg", "ld-musl-x86_64.so.1") else 0o644)
        system = work / "original-firmware-snapshot"
        system.mkdir()
        unpack_original(system, image, OFFSETS[profile], ("usr/lib/opkg/info",))
        installed_db = system / "usr/lib/opkg/status"
        installed_db.parent.mkdir(parents=True, exist_ok=True)
        original_db = read_original(image, OFFSETS[profile], "usr/lib/opkg/status")
        installed_db.write_bytes(original_db)
        (system / "var/lock").mkdir(parents=True)
        (system / "tmp/lists").mkdir(parents=True)
        original_info_count = len(list((system / "usr/lib/opkg/info").glob("*.list")))
        if original_info_count < profile_spec["original_installed"] - 60:
            raise ValueError("Original file-list database incomplete")
        config = work / "offline.conf"
        config.write_text(
            f"dest root {system}\nlists_dir ext {system}/tmp/lists\n"
            f"arch all 1\narch {profile_spec['arch']} 10\n",
            encoding="utf-8",
        )
        release_packages = work / "packages"
        release_packages.mkdir()
        for filename, blob in package_set.values():
            (release_packages / filename).write_bytes(blob)
        env = {**os.environ, "LD_LIBRARY_PATH": str(program)}
        cmd = [
            str(program / "ld-musl-x86_64.so.1"), str(program / "opkg"),
            "-f", str(config), "-t", str(system / "tmp"), "--noaction",
            "install", *[str(release_packages / item[0]) for item in package_set.values()],
        ]
        result = subprocess.run(cmd, env=env, capture_output=True,
                                text=True, timeout=120)
        if result.returncode != 0:
            raise ValueError(f"Original OPKG offline dependency plan rejected: {result.stderr[-700:]}")
        matches = re.findall(r"^Installing ([a-zA-Z0-9_.+-]+) \(", result.stdout, re.M)
        if (set(matches) != expected_names or
                any(term in result.stdout for term in (
                    "Upgrading", "Removing", "Downgrading", "Reinstalling")) or
                result.stderr.strip()):
            raise ValueError("Original vendor OPKG plans non-candidate package changes or warnings")
        if installed_db.read_bytes() != original_db:
            raise ValueError("OPKG --noaction modified original installed package database")
        if b"Package: tcpdump\n" not in original_db:
            raise ValueError("Original full tcpdump is not preserved")
        return {
            "schema_version": 1,
            "firmware": "istoreos", "release": "24.10.8", "revision": "2026073111",
            "vendor_profile": profile, "target": profile_spec["target"],
            "arch": profile_spec["arch"], "package_manager": "opkg",
            "release_tag": TAG, "original_image_sha256": profile_spec["image_sha"],
            "original_image_raw_sha256": profile_spec["raw_sha"],
            "adzero_package_source_sha256": SOURCE_SHA,
            "original_firmware_packages": profile_spec["original_installed"],
            "original_opkg_file_lists": original_info_count,
            "original_opkg_binary_sha256": digest((program / "opkg").read_bytes()),
            "original_opkg_libc_sha256": digest((program / "ld-musl-x86_64.so.1").read_bytes()),
            "original_db_sha256": digest(original_db),
            "original_db_unchanged": True,
            "native_ipk_sha256": digest(package_set["luci-app-adzero"][1]),
            "dependency_sha256": {key: digest(package_set[key][1]) for key in deps},
            "no_network_repos": True,
            "original_full_tcpdump_preserved": True,
            "new_install_names": sorted(expected_names),
            "packages_simulated": 8,
            "existing_package_upgrades": 0,
            "existing_package_removals": 0,
            "device_acceptance": "not_run",
            "stable_sdk_verified": False,
            "historical_source_commit_exactly_attested": False,
        }


def ipk_control_bytes(content):
    from io import BytesIO
    from tarfile import open as taropen
    with taropen(fileobj=BytesIO(content), mode="r:gz") as archive:
        data = archive.extractfile("control.tar.gz") if "control.tar.gz" in archive.getnames() else archive.extractfile("./control.tar.gz")
        if data is None:
            raise ValueError("Missing OPKG control.tar.gz")
        with taropen(fileobj=BytesIO(data.read()), mode="r:gz") as inner:
            control_file = inner.extractfile("control") if "control" in inner.getnames() else inner.extractfile("./control")
            if control_file is None:
                raise ValueError("Missing native OPKG control header")
            text = control_file.read().decode("utf-8")
    return dict(re.findall(r"^([A-Za-z0-9-]+): ([^\n]+)$", text, re.M))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILES), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(args.profile)
    if args.output:
        path = args.output
        if path.exists() or path.is_symlink():
            parser.exit(1, "Refusing to overwrite iStoreOS OPKG solver evidence\n")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
