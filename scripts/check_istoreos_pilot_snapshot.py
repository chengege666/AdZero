#!/usr/bin/env python3
"""Verify a PRIVATE pilot's actual preflight and apk solver against official rootfs.

Uses a disposable temporary copy of original firmware APK database and the
original vendor Buildroot host apk binary. No router, real host package DB or
network is touched. This is not a physical-device install or DNS test.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

from check_istoreos_apk_solver import DATABASE
from inspect_istoreos_arm64_image import RAW_IMAGES, inspect_image
from probe_istoreos_arm64 import PROFILES


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def snapshot_check(source, image, profile, pilot):
    if profile not in PROFILES:
        raise ValueError("Unsupported original iStoreOS ARM64 profile")
    source, image, pilot = Path(source), Path(image), Path(pilot)
    if source.is_symlink() or image.is_symlink() or pilot.is_symlink():
        raise ValueError("Symlinked original vendor input rejected")
    if not pilot.is_dir() or not (pilot / "SHA256SUMS").is_file():
        raise ValueError("Pilot bundle is incomplete")
    installed, image_report = inspect_image(image, profile)
    manifest = json.loads((pilot / "pilot-manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("vendor_profile") != profile
            or manifest.get("target") != PROFILES[profile]["target"]
            or manifest.get("arch") != PROFILES[profile]["arch"]
            or manifest.get("original_image_sha256") != RAW_IMAGES[profile]["sha256"]
            or manifest.get("installation_enabled") is not False
            or manifest.get("publishable") is not False
            or len(manifest.get("packages", [])) != 7):
        raise ValueError("Pilot manifest cannot authorize an unverified target")
    source, image, pilot = source.resolve(), image.resolve(), pilot.resolve()
    host_apk = source / "staging_dir/host/bin/apk"
    if host_apk.is_symlink() or not host_apk.is_file() or not (host_apk.stat().st_mode & 0o111):
        raise ValueError("Exact vendor host apk-tools binary is unavailable")
    with tempfile.TemporaryDirectory(prefix="adzero-istore-snapshot-") as temp:
        temp = Path(temp)
        root = temp / "root"
        for path in ("etc/openwrt_release", *DATABASE):
            destination = root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(subprocess.check_output(
                ["unsquashfs", "-offset", str(RAW_IMAGES[profile]["squashfs_offset"]),
                 "-cat", str(image), path], timeout=90))
        # This narrowly adapts only the host apk's --print-arch query. Every
        # solver operation executes the actual official host apk-tools binary.
        tools = temp / "bin"
        tools.mkdir()
        shim = tools / "apk"
        shim.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = --print-arch ]; then echo aarch64; exit 0; fi\n"
            f"exec {shlex.quote(str(host_apk))} \"$@\"\n", encoding="utf-8")
        shim.chmod(0o700)
        env = {**os.environ,
               "PATH": str(tools) + ":" + os.environ.get("PATH", "/usr/bin:/bin"),
               "ADZERO_PILOT_ROOT": str(root)}
        observations = {}
        for mode in ("--check", "--solver"):
            result = subprocess.run(["sh", str(pilot / "preflight.sh"), mode],
                                    text=True, capture_output=True, timeout=120, env=env)
            if result.returncode:
                raise ValueError(f"Pilot {mode} against official system failed: {result.stderr[-700:]}")
            if ("预检通过" not in result.stdout or
                    (mode == "--solver" and "离线依赖模拟通过" not in result.stdout)):
                raise ValueError("Pilot did not produce the expected readonly verification")
            observations[mode] = "passed"
    return {
        "firmware": "istoreos", "profile": profile, "release": "25.12.6",
        "revision": "2026102312", "target": PROFILES[profile]["target"],
        "arch": PROFILES[profile]["arch"],
        "official_image_sha256": image_report["verified_raw_image_sha256"],
        "original_installed_packages_examined": len(installed),
        "vendor_host_apk_sha256": sha256(host_apk),
        "pilot_manifest_sha256": sha256(pilot / "pilot-manifest.json"),
        "preflight_checks": observations, "original_db_snapshot": True,
        "used_real_vendor_apk_solver": True, "network_access_allowed": False,
        "host_or_router_packages_installed": False,
        "device_acceptance": "not_run", "publishable": False,
        "scope": "official original firmware snapshot and real host apk --simulate; not physical router, LAN or recovery",
    }


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--profile", choices=tuple(PROFILES), required=True)
    a.add_argument("--source", type=Path, required=True)
    a.add_argument("--image", type=Path, required=True)
    a.add_argument("--pilot", type=Path, required=True)
    a.add_argument("--output", type=Path)
    args = a.parse_args()
    try:
        report = snapshot_check(args.source, args.image, args.profile, args.pilot)
        content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            if args.output.exists() or args.output.is_symlink():
                raise ValueError("Refusing to overwrite original snapshot acceptance evidence")
            args.output.write_text(content, encoding="utf-8", newline="\n")
        print(content, end="")
    except (OSError, ValueError, subprocess.TimeoutExpired,
            subprocess.CalledProcessError) as error:
        a.exit(1, f"iStoreOS pilot snapshot refused: {error}\n")
