#!/usr/bin/env python3
"""Bundle only real SDK outputs for the current source hash. No publication."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

from build_sdk import PACKAGE, ROOT, source_hash


def bundle(manifests, output):
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    reports = []
    current = source_hash(PACKAGE)
    for path in manifests:
        report = json.loads(path.read_text())
        if report.get("sdk_build") != "passed" or report.get("source_sha256") != current:
            raise ValueError("Release requires an SDK build of the current sources")
        if report["firmware_declared"] != "openwrt" or report["target_observed"] != "x86/64":
            raise ValueError("This release channel only supports verified OpenWrt x86/64 builds")
        package = path.parent / report["package"]
        if hashlib.sha256(package.read_bytes()).hexdigest() != report["sha256"]:
            raise ValueError("SDK output checksum changed")
        name = f"adzero-openwrt-{report['release_declared']}-x86_64.{report['package_format']}"
        shutil.copyfile(package, output / name)
        rows.append("\t".join((report["sha256"], name, report["firmware_declared"], report["release_declared"], report["target_observed"], report["package_arch_observed"], report["package_format"])))
        reports.append(report)
    (output / "releases.tsv").write_text("# sha256\tfile\tfirmware\trelease\ttarget\tarch\tformat\n" + "\n".join(rows) + "\n")
    (output / "build-provenance.json").write_text(json.dumps(reports, indent=2) + "\n")
    shutil.copyfile(ROOT / "scripts/install.sh", output / "install.sh")
    (output / "INSTALL.txt").write_text("AdZero 0.5.0 development candidate\nSSH as root, extract this archive, then run:\nsh install.sh --local-dir \"$(pwd)\"\n\nOnly exact SDK-verified rows are accepted. Router/LAN acceptance is pending.\n")
    archive = output.parent / "adzero-0.5.0-install.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(output.iterdir()):
            tar.add(path, arcname="adzero-0.5.0/" + path.name)
    print(json.dumps({"archive": str(archive), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "rows": len(rows), "source_sha256": current}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/release-0.5.0")
    args = parser.parse_args()
    bundle(args.manifest, args.output)
