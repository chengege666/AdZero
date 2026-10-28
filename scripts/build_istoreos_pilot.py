#!/usr/bin/env python3
"""Prepare PRIVATE iStoreOS ARM64 pilot bundles (never install or publish).

Only copy real original-vendor APKs after re-running the exact pinned firmware
offline solver against the original system image. A bundle includes no installer
and cannot authorize public SDK releases or LuCI online updates.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from build_ipk import version
from build_sdk import PACKAGE, source_hash
from check_istoreos_apk_solver import verify as verify_solver
from inspect_istoreos_arm64_image import RAW_IMAGES
from probe_istoreos import SOURCE_COMMIT
from probe_istoreos_arm64 import PROFILES

ROOT = Path(__file__).resolve().parents[1]
VALID_APK = re.compile(r"[a-z0-9][a-z0-9_.+-]*\.apk\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_report(report, profile):
    spec = PROFILES[profile]
    expected = {
        "firmware": "istoreos", "release": "25.12.6",
        "revision": "2026102312", "vendor_profile": profile,
        "target": spec["target"], "arch": spec["arch"],
        "original_image_sha256": RAW_IMAGES[profile]["sha256"],
        "native_source_sha256": source_hash(PACKAGE),
        "vendor_source_commit": SOURCE_COMMIT, "offline_solver": "passed_no_network",
        "original_db_unchanged": True, "original_full_tcpdump_preserved": True,
        "existing_firmware_package_removals": 0,
        "device_acceptance": "not_run", "publishable": False,
    }
    if not isinstance(report, dict) or any(report.get(k) != v for k, v in expected.items()):
        raise ValueError("Original firmware solver evidence is mismatched or publishable")
    deps = report.get("missing_vendor_dependencies")
    if not isinstance(deps, dict) or len(deps) != 6:
        raise ValueError("Expected six independent native vendor dependencies")
    if report.get("packages_simulated") != 7:
        raise ValueError("Candidate offline solver did not test all seven packages")
    if set(report.get("installed_packages_simulated", [])) != set(deps) | {"luci-app-adzero"}:
        raise ValueError("Simulated native dependencies differ")
    if not HEX64.fullmatch(report.get("native_apk_sha256", "")):
        raise ValueError("No verified native AdZero APK digest")


def pick(source, name, digest_expected, arch):
    if not VALID_APK.fullmatch(name) or not HEX64.fullmatch(digest_expected):
        raise ValueError("Untrusted APK basename or checksum")
    root = source / "bin/packages" / arch
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Vendor source APK directory invalid")
    found = [p for p in root.glob(f"*/{name}") if p.is_file()
             and not p.is_symlink() and not p.parent.is_symlink()]
    if len(found) != 1 or found[0].stat().st_size > 16 * 1024 * 1024:
        raise ValueError(f"Missing, duplicate or oversized original APK: {name}")
    if digest(found[0]) != digest_expected:
        raise ValueError(f"Vendor APK source checksum differs: {name}")
    return found[0]


def bundle(source, image, profile, output, *, solver=verify_solver):
    if profile not in PROFILES:
        raise ValueError("Only exact pinned iStoreOS ARM64 targets are supported")
    source, image, output = Path(source), Path(image), Path(output)
    if any(p.is_symlink() for p in (source, image, output, output.parent)):
        raise ValueError("Symlinked input or output paths are forbidden")
    source, image, output = source.resolve(), image.resolve(), output.resolve()
    if not source.is_dir() or not image.is_file() or not output.parent.is_dir():
        raise ValueError("Source, official raw image or destination parent is missing")
    archive = output.with_suffix(".zip")
    part = output.with_name(output.name + ".zip.partial")
    if (output.exists() or archive.exists() or archive.is_symlink()
            or part.exists() or part.is_symlink()
            or output == source or output.is_relative_to(source)):
        raise ValueError("Pilot output already exists or is inside the vendor Buildroot")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", output.name):
        raise ValueError("Unsafe private pilot output name")
    report = solver(source, image, profile)
    validate_report(report, profile)
    spec = PROFILES[profile]
    app = f"luci-app-adzero-{version()}.apk"
    entries = {app: {"name": "luci-app-adzero", "file": app,
                     "sha256": report["native_apk_sha256"],
                     "arch": "noarch", "purpose": "unreleased_candidate"}}
    for name, item in report["missing_vendor_dependencies"].items():
        if (not re.fullmatch(r"[a-z0-9][a-z0-9_.+-]*", name)
                or name in ("tcpdump-mini", "luci-app-adzero")
                or not isinstance(item, dict)):
            raise ValueError("Invalid or conflicting vendor dependency name")
        filename = item.get("file", "")
        if (not filename.startswith(name + "-") or filename in entries
                or item.get("arch") not in ("noarch", spec["arch"])):
            raise ValueError("Wrong vendor dependency filename or architecture")
        entries[filename] = {**item, "name": name,
                             "purpose": "original_vendor_dependency"}
    if len(entries) != 7:
        raise ValueError("Not exactly one candidate and six vendor dependencies")

    stage = Path(tempfile.mkdtemp(prefix=".istoreos-candidate-", dir=output.parent))
    renamed = False
    try:
        packages = stage / "packages"
        packages.mkdir()
        for name, item in sorted(entries.items()):
            src = pick(source, name, item["sha256"], spec["arch"])
            shutil.copyfile(src, packages / name)
            if digest(packages / name) != item["sha256"]:
                raise ValueError("Candidate APK changed while staging")
        (stage / "profile.tsv").write_text(
            f"istoreos\t25.12.6\t2026102312\t{spec['target']}\t{spec['arch']}\t{profile}\tapk\n",
            encoding="utf-8", newline="\n")
        manifest = {
            "schema_version": 1, "firmware": "istoreos",
            "release": "25.12.6", "revision": "2026102312",
            "vendor_profile": profile, "target": spec["target"], "arch": spec["arch"],
            "original_image_sha256": RAW_IMAGES[profile]["sha256"],
            "vendor_source_commit": SOURCE_COMMIT,
            "source_sha256": report["native_source_sha256"],
            "offline_solver": "passed_no_network",
            "packages": [entries[k] for k in sorted(entries)],
            "public_release": False, "publishable": False,
            "device_acceptance": "not_run", "installation_enabled": False,
        }
        (stage / "pilot-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
        (stage / "README.txt").write_text(
            "AdZero iStoreOS PRIVATE PILOT, READ-ONLY\n"
            "NOT A RELEASE. NOT AN INSTALLATION APPROVAL.\n"
            "For the exact iStoreOS 25.12.6 revision 2026102312 target only.\n"
            "Run sh preflight.sh --check to verify identity, files and ABI.\n"
            "Optionally run sh preflight.sh --solver for OFFLINE simulated solver.\n"
            "Run sh preflight.sh --report for fixed-schema REDACTED readiness JSON.\n"
            "Report only includes safe boolean/numeric observations, no raw configs.\n"
            "Neither command installs, upgrades, changes DNS or reboots.\n"
            "Do not manually run apk add before separately approved device trials,\n"
            "network recovery readiness and configuration backups.\n",
            encoding="utf-8", newline="\n")
        shutil.copyfile(ROOT / "scripts/istoreos_pilot_preflight.sh", stage / "preflight.sh")
        (stage / "preflight.sh").chmod(0o755)
        files = sorted(f for f in stage.rglob("*") if f.is_file())
        (stage / "SHA256SUMS").write_text(
            "".join(f"{digest(f)}  {f.relative_to(stage).as_posix()}\n" for f in files),
            encoding="utf-8", newline="\n")
        with zipfile.ZipFile(part, "x", compression=zipfile.ZIP_STORED,
                             allowZip64=False) as zipped:
            for f in sorted(q for q in stage.rglob("*") if q.is_file()):
                rel = f.relative_to(stage).as_posix()
                info = zipfile.ZipInfo(f"{output.name}/{rel}", (2026, 10, 29, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (0o100755 if rel == "preflight.sh" else 0o100644) << 16
                zipped.writestr(info, f.read_bytes())
        stage.rename(output)
        renamed = True
        part.rename(archive)
        return {"profile": profile, "target": spec["target"], "package_count": 7,
                "directory": str(output), "archive": str(archive),
                "archive_sha256": digest(archive), "public_release": False,
                "publishable": False, "installation_enabled": False}
    finally:
        if not renamed:
            shutil.rmtree(stage, ignore_errors=True)
            part.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(PROFILES), required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    a = parser.parse_args()
    try:
        print(json.dumps(bundle(a.source, a.image, a.profile, a.output),
                         ensure_ascii=False, indent=2))
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, f"iStoreOS private pilot refused: {error}\n")
