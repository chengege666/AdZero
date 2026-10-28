#!/usr/bin/env python3
"""Bundle only real SDK outputs for the current source hash. No publication."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tarfile

from build_sdk import PACKAGE, ROOT, source_hash
from build_ipk import version

SUPPORTED_BUILDS = {
    ("24.10.8", "x86/64", "ipk"): "x86_64",
    ("25.12.5", "x86/64", "apk"): "x86_64",
    ("25.12.5", "rockchip/armv8", "apk"): "aarch64_generic",
}


def validate_release(output):
    """Check the actual bytes the router downloads, before archiving/uploading."""
    for name in ('releases.tsv', 'build-provenance.json', 'install.sh', 'INSTALL.txt'):
        raw = (output / name).read_bytes()
        if not raw or b'\r' in raw or raw.startswith(b'\xef\xbb\xbf') or not raw.endswith(b'\n'):
            raise ValueError(f'Release text must be UTF-8 without BOM and use LF: {name}')
        raw.decode('utf-8')
    identities = set()
    rows = (output / 'releases.tsv').read_text(encoding='utf-8').splitlines()
    for row in rows:
        if row.startswith('#'):
            continue
        fields = row.split('\t')
        if len(fields) != 7:
            raise ValueError('Release catalog must have exactly seven fields')
        sha, name, firmware, release, target, arch, fmt = fields
        identity = (release, target, fmt)
        if firmware != 'openwrt' or SUPPORTED_BUILDS.get(identity) != arch or identity in identities:
            raise ValueError('Release catalog contains an unsupported or duplicate identity')
        if not re.fullmatch(r'[a-f0-9]{64}', sha) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._+-]*', name):
            raise ValueError('Release catalog contains an invalid checksum or filename')
        if hashlib.sha256((output / name).read_bytes()).hexdigest() != sha:
            raise ValueError('Release catalog checksum differs from delivered package')
        identities.add(identity)
    if not identities:
        raise ValueError('Release catalog is empty')


def bundle(manifests, output):
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    reports = []
    seen = set()
    release_version = version().rsplit('-r', 1)[0]
    current = source_hash(PACKAGE)
    for path in manifests:
        report = json.loads(path.read_text())
        if report.get("sdk_build") != "passed" or report.get("source_sha256") != current:
            raise ValueError("Release requires an SDK build of the current sources")
        identity = (report["release_declared"], report["target_observed"], report["package_format"])
        if report["firmware_declared"] != "openwrt" or SUPPORTED_BUILDS.get(identity) != report["package_arch_observed"]:
            raise ValueError("Release/target/format/SDK architecture is not in the supported build matrix")
        if identity in seen:
            raise ValueError("Duplicate build identity in release")
        seen.add(identity)
        package = path.parent / report["package"]
        if hashlib.sha256(package.read_bytes()).hexdigest() != report["sha256"]:
            raise ValueError("SDK output checksum changed")
        target_part = '' if report['target_observed'] == 'x86/64' else report['target_observed'].replace('/', '-') + '-'
        name = f"adzero-openwrt-{report['release_declared']}-{target_part}{report['package_arch_observed']}.{report['package_format']}"
        shutil.copyfile(package, output / name)
        rows.append("\t".join((report["sha256"], name, report["firmware_declared"], report["release_declared"], report["target_observed"], report["package_arch_observed"], report["package_format"])))
        reports.append(report)
    (output / "releases.tsv").write_text("# sha256\tfile\tfirmware\trelease\ttarget\tarch\tformat\n" + "\n".join(rows) + "\n", encoding='utf-8', newline='\n')
    (output / "build-provenance.json").write_text(json.dumps(reports, indent=2) + "\n", encoding='utf-8', newline='\n')
    (output / "install.sh").write_text((ROOT / "scripts/install.sh").read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
    (output / "INSTALL.txt").write_text(f"AdZero {release_version} development candidate\nSSH as root, extract this archive, then run the Chinese interactive installer:\nsh install.sh --menu --local-dir \"$(pwd)\"\nThe menu automatically chooses install or upgrade and offers read-only compatibility checks and safe uninstall. No version, architecture or package file input is needed.\nHeadless automation remains available with: sh install.sh --local-dir \"$(pwd)\" --install [--no-enable] or --upgrade [--no-enable].\nIt verifies package checksums and backs up config/recovery state before asking the old controller to restore it. Persistent locks stop the upgrade; never delete an active lock.\n\nOnly exact SDK-verified rows are accepted. Router/LAN acceptance is pending.\n", encoding='utf-8', newline='\n')
    validate_release(output)
    archive = output.parent / f"adzero-{release_version}-install.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(output.iterdir()):
            tar.add(path, arcname=f"adzero-{release_version}/" + path.name)
    print(json.dumps({"archive": str(archive), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "rows": len(rows), "source_sha256": current}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / ("dist/release-" + version().rsplit('-r', 1)[0]))
    args = parser.parse_args()
    bundle(args.manifest, args.output)
