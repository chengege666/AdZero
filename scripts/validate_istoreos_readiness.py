#!/usr/bin/env python3
"""Strictly validate a redacted iStoreOS ARM64 device-readiness report.

Rejects unexpected fields, credentials/IPs/URLs/command lines, wrong target,
unapproved pilot manifest and malformed types. This NEVER authorizes installs
or claims LAN/DNS/rollback/physical device acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from probe_istoreos_arm64 import PROFILES

MAX_BYTES = 16 * 1024
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
FIELDS = frozenset((
    "schema_version", "report_type", "firmware", "release", "revision",
    "vendor_profile", "target", "arch", "apk_cpu", "pilot_manifest_sha256",
    "board_check",
    "checked_local_apks", "original_full_tcpdump", "luci_base_present",
    "rpcd_present", "memory_available_kib", "overlay_available_kib",
    "dns_process_presence", "proxy_config_presence", "proxy_core_presence",
    "network_dns_test", "proxy_coexistence_test", "device_acceptance",
    "installation_authorized", "public_release", "publishable",
))
GROUPS = {
    "dns_process_presence": frozenset(
        ("dnsmasq", "smartdns", "unbound", "adguardhome")),
    "proxy_config_presence": frozenset(
        ("nailink", "passwall", "openclash", "nikki", "homeproxy")),
    "proxy_core_presence": frozenset(
        ("mihomo", "clash", "sing_box", "xray")),
}
CONSTANTS = {
    "schema_version": 1,
    "report_type": "adzero_istoreos_readonly_readiness",
    "firmware": "istoreos", "release": "25.12.6", "revision": "2026102312",
    "arch": "aarch64_generic", "checked_local_apks": 7,
    "original_full_tcpdump": True, "luci_base_present": True,
    "rpcd_present": True, "network_dns_test": "not_run",
    "proxy_coexistence_test": "not_run", "device_acceptance": "not_run",
    "installation_authorized": False, "public_release": False,
    "publishable": False,
}
SIGNED_LIMIT = 2**52


def no_duplicates(pairs):
    result = {}
    for key, val in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key refused")
        result[key] = val
    return result


def load_json(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Report/manifest is symlinked, missing or oversized")
    def reject_constant(value):
        raise ValueError(f"Non-finite/non-JSON numeric constant refused: {value}")
    try:
        obj = json.loads(path.read_bytes().decode("utf-8"),
                         object_pairs_hook=no_duplicates, parse_constant=reject_constant)
    except (UnicodeError, json.JSONDecodeError) as err:
        raise ValueError("Report/manifest is not valid UTF-8 JSON") from err
    if type(obj) is not dict:
        raise ValueError("JSON document must be an object")
    return obj


def validate(report, pilot):
    if type(report) is not dict or set(report) != FIELDS:
        raise ValueError("Readiness schema has missing or unexpected fields")
    for key, expected in CONSTANTS.items():
        if type(report.get(key)) is not type(expected) or report[key] != expected:
            raise ValueError(f"Unexpected readiness identity or unsafe status: {key}")
    profile = report.get("vendor_profile")
    if type(profile) is not str or profile not in PROFILES:
        raise ValueError("Unknown original iStoreOS ARM64 profile")
    target = PROFILES[profile]["target"]
    if report["target"] != target or type(report["target"]) is not str:
        raise ValueError("Original firmware target mismatch")
    if report["apk_cpu"] not in ("aarch64", "aarch64_generic"):
        raise ValueError("Original firmware APK CPU alias mismatch")
    if type(report["apk_cpu"]) is not str:
        raise ValueError("Original firmware APK CPU type invalid")
    board_check = report["board_check"]
    expected_board_states = (("not_applicable",) if profile == "armsr"
                             else ("matched", "unavailable"))
    if type(board_check) is not str or board_check not in expected_board_states:
        raise ValueError("Vendor board identity is missing or not pinned")
    pilot = Path(pilot)
    if pilot.is_symlink() or not pilot.is_dir():
        raise ValueError("Pilot source directory is missing or symlinked")
    manifest_path = pilot / "pilot-manifest.json"
    manifest = load_json(manifest_path)
    expected_manifest = {
        "schema_version": 1, "firmware": "istoreos", "release": "25.12.6",
        "revision": "2026102312", "vendor_profile": profile,
        "target": target, "arch": PROFILES[profile]["arch"],
        "public_release": False, "publishable": False,
        "installation_enabled": False, "device_acceptance": "not_run",
    }
    for key, val in expected_manifest.items():
        if type(manifest.get(key)) is not type(val) or manifest[key] != val:
            raise ValueError(f"Pilot is not the exact unapproved vendor target: {key}")
    packages = manifest.get("packages")
    if type(packages) is not list or len(packages) != 7:
        raise ValueError("Pilot does not contain seven original-vendor packages")
    checksum = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if (type(report.get("pilot_manifest_sha256")) is not str
            or not HEX64.fullmatch(report["pilot_manifest_sha256"])
            or report["pilot_manifest_sha256"] != checksum):
        raise ValueError("Device report does not match exact pilot manifest")
    for name, expected_names in GROUPS.items():
        obj = report.get(name)
        if type(obj) is not dict or set(obj) != expected_names:
            raise ValueError(f"Unknown, missing or privacy-leaking observation: {name}")
        if any(type(value) is not bool for value in obj.values()):
            raise ValueError(f"Non-boolean process/config observation: {name}")
    for name in ("memory_available_kib", "overlay_available_kib"):
        observed = report.get(name)
        if observed is not None and (type(observed) is not int
                                     or not 0 <= observed < SIGNED_LIMIT):
            raise ValueError(f"Invalid resource availability value: {name}")

    cautions = []
    if report["memory_available_kib"] is None:
        cautions.append("memory_unavailable")
    elif report["memory_available_kib"] < 64 * 1024:
        cautions.append("memory_under_64_mib")
    if report["overlay_available_kib"] is None:
        cautions.append("overlay_space_unavailable")
    elif report["overlay_available_kib"] < 64 * 1024:
        cautions.append("overlay_under_64_mib")
    if profile == "rockchip-r6xs" and board_check != "matched":
        cautions.append("r6xs_board_identity_unverified")
    if sum(report["dns_process_presence"].values()) > 1:
        cautions.append("multiple_dns_process_types_present")
    if sum(report["proxy_config_presence"].values()) > 1:
        cautions.append("multiple_proxy_configs_present")
    if any(report["proxy_core_presence"].values()):
        cautions.append("proxy_core_process_present_review_dns_path")
    return {
        "report": "validated_strict_redacted_schema",
        "profile": profile,
        "target": target,
        "firmware_revision": "2026102312",
        "pilot_manifest_sha_matches": True,
        "private_pilot": True,
        "redacted_report_only": True,
        "cautions": cautions,
        "requires_manual_topology_review": True,
        "lan_dns_verified": False,
        "real_device_install_verified": False,
        "device_acceptance": "not_run",
        "installation_authorized": False,
        "publishable": False,
    }


def validate_files(report_path, pilot):
    report = load_json(report_path)
    return validate(report, pilot)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = validate_files(args.report, args.pilot)
        text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            if args.output.is_symlink() or args.output.exists():
                raise ValueError("Refusing to overwrite existing validation report")
            args.output.write_text(text, encoding="utf-8", newline="\n")
        print(text, end="")
    except (OSError, ValueError) as error:
        parser.exit(1, f"iStoreOS readonly device report refused: {error}\n")


if __name__ == "__main__":
    main()
