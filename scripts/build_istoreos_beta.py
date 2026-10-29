#!/usr/bin/env python3
"""Build immutable iStoreOS 25.12.6 public *beta* installation assets.

Only exactly pinned factory Buildroot packages are permitted. This intentionally
does NOT add any beta target to production's sdk_verified or releases.tsv.
Release version contains a non-semver suffix so LuCI's stable updater ignores it.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile

from build_sdk import PACKAGE, source_hash
from build_ipk import version as apk_version
from probe_istoreos import SOURCE_COMMIT
from probe_istoreos_arm64 import PROFILES as ARM_PROFILES

ROOT = Path(__file__).resolve().parents[1]
RELEASE_TAG = "v0.21.5-istoreos-beta.2"
RELEASE_FW = "25.12.6"
RELEASE_REVISION = "2026102312"
PACKAGE_HASH = "b579f94fe847da6b6a0230fbdb7efa833d39a6bc80c9b6c726e8da7b10dc0f52"
RAW_X86_SHA = "833e203e667fb49b27dd69ce8a8a8176a563d5f7154ba95ac219bed0af5da3c9"
EXPECTED_SOURCE = "8df7589827fdc1adc418c3b83887097589b257a4a7654ac0dd91ddf878ee60c9"
TARGETS = {
    "x86_64": {
        "target": "x86/64", "arch": "x86_64", "missing_sha": RAW_X86_SHA,
        "source": ".sdk/istoreos-25.12.6-2026102312-source",
        "evidence": "dist/istoreos-native-candidate-tcpdump-provider-20261028/dependency-closure.json",
    },
    "armsr": {
        "target": "armsr/armv8", "arch": "aarch64_generic",
        "missing_sha": "c46658d6f9a4b1d6d45b2da25f0eee0d188a7a625cdc200a59eb7af1a4f78128",
        "source": ".sdk/istoreos-armsr-2026102312-source",
        "evidence": "docs/evidence/istoreos-25.12.6/arm64-armsr-native-offline-solver.json",
    },
    "rockchip-r6xs": {
        "target": "rockchip/armv8", "arch": "aarch64_generic",
        "missing_sha": "c89326ee924f41d10921570d3da1b7caf22be13a275be7bd9bd830e0f21c8ec8",
        "source": ".sdk/istoreos-r6xs-2026102312-source",
        "evidence": "docs/evidence/istoreos-25.12.6/arm64-r6xs-native-offline-solver.json",
    },
}
NAMES = ("adblock-fast", "conntrack", "coreutils-timeout",
         "libnetfilter-cthelper0", "libnetfilter-cttimeout1", "libnetfilter-queue1")
SHA = re.compile(r"[0-9a-f]{64}\Z")
NAME = re.compile(r"[a-z0-9][a-z0-9_.+-]*\.apk\Z")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def get_evidence(profile, root=ROOT):
    target = TARGETS[profile]
    source = root / target["source"]
    evidence = json.loads((root / target["evidence"]).read_text())
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Missing or symlinked pinned original vendor Buildroot")
    observed = evidence["missing_vendor_dependencies"] if profile != "x86_64" else evidence["missing_from_original_firmware"]
    if (set(observed) != set(NAMES) or
            evidence.get("firmware") != "istoreos" or
            evidence.get("release") != RELEASE_FW or
            evidence.get("revision") != RELEASE_REVISION or
            evidence.get("vendor_source_commit") != SOURCE_COMMIT or
            evidence.get("source_sha256", evidence.get("native_source_sha256")) != EXPECTED_SOURCE or
            evidence.get("image_raw_sha256", evidence.get("original_image_sha256")) != target["missing_sha"] or
            evidence.get("apk_sha256", evidence.get("native_apk_sha256")) != PACKAGE_HASH or
            evidence.get("device_acceptance") not in ("not_run", "isolated_vm_install_verified_no_real_lan_test") or
            evidence.get("publishable") is not False):
        raise ValueError("Original vendor package evidence mismatch")
    if profile != "x86_64":
        if (evidence.get("vendor_profile") != profile or evidence.get("target") != target["target"]
                or evidence.get("arch") != target["arch"] or evidence.get("offline_solver") != "passed_no_network"
                or evidence.get("packages_simulated") != 7 or evidence.get("existing_firmware_package_removals") != 0
                or evidence.get("original_full_tcpdump_preserved") is not True):
            raise ValueError("Original ARM64 offline solver evidence incomplete")
    return source, observed


def collect(profile, root=ROOT):
    target = TARGETS[profile]
    if source_hash(root / "luci-app-adzero") != EXPECTED_SOURCE:
        raise ValueError("Current native AdZero sources changed; do not package old binary")
    if apk_version() != "0.21.5-r1":
        raise ValueError("Beta release must use exact original candidate APK version")
    source, evidence = get_evidence(profile, root=root)
    folder = source / "bin/packages" / target["arch"]
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Missing original vendor APK directory")
    names = {"luci-app-adzero": {"file": f"luci-app-adzero-{apk_version()}.apk",
                                "sha256": PACKAGE_HASH, "arch": "noarch"}}
    names.update(evidence)
    entries, data = [], {}
    for pkg, record in sorted(names.items()):
        name = record["file"]
        expected_sha = record["sha256"]
        if not NAME.fullmatch(name) or not SHA.fullmatch(expected_sha):
            raise ValueError(f"Unsafe binary filename/checksum for {pkg}")
        if record.get("arch") not in ("noarch", target["arch"]):
            raise ValueError(f"Foreign ABI attempted by {pkg}")
        matches = [f for f in folder.glob("*/" + name) if f.is_file()
                   and not f.is_symlink() and not f.parent.is_symlink()]
        if len(matches) != 1:
            raise ValueError(f"Missing or ambiguous vendor binary {name}")
        body = matches[0].read_bytes()
        if len(body) > 24 * 1024 * 1024 or sha256(body) != expected_sha:
            raise ValueError(f"Original vendor APK digest mismatch: {name}")
        entries.append({"name": pkg, "file": name, "sha256": expected_sha,
                        "arch": record["arch"]})
        data["packages/" + name] = body
    if len(entries) != 7:
        raise ValueError("Beta requires one AdZero and exactly six same-vendor dependencies")
    meta = {"schema_version": 1, "channel": "explicit_opt_in_public_beta",
            "release_tag": RELEASE_TAG, "firmware": "istoreos", "release": RELEASE_FW,
            "revision": RELEASE_REVISION, "vendor_profile": profile,
            "target": target["target"], "arch": target["arch"],
            "original_image_sha256": target["missing_sha"],
            "vendor_source_commit": SOURCE_COMMIT, "source_sha256": EXPECTED_SOURCE,
            "candidate_apk_sha256": PACKAGE_HASH,
            "packages": entries, "stable_approved": False,
            "physical_router_acceptance": "not_run", "default_enable": False}
    data["manifest.json"] = (json.dumps(meta, ensure_ascii=False, sort_keys=True,
                                        indent=2) + "\n").encode()
    data["profile.tsv"] = (f"istoreos\t{RELEASE_FW}\t{RELEASE_REVISION}\t"
                           f"{target['target']}\t{target['arch']}\t{profile}\tapk\n").encode()
    data["SHA256SUMS"] = ("".join(f"{sha256(data[name])}  {name}\n"
                                  for name in sorted(data))).encode()
    return data


def deterministic_tar_gz(files):
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, compresslevel=9, mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for filename in sorted(files):
                raw = files[filename]
                entry = tarfile.TarInfo(name=filename)
                entry.size = len(raw)
                entry.mtime = 0
                entry.uid = entry.gid = 0
                entry.uname = entry.gname = ""
                entry.mode = 0o644
                tar.addfile(entry, io.BytesIO(raw))
    return buf.getvalue()


def build(outdir, *, root=ROOT):
    if outdir.is_symlink() or not outdir.is_dir():
        raise ValueError("Beta output directory missing or a symlink")
    checksums, assets = {}, {}
    for profile in TARGETS:
        filename = f"adzero-istoreos-{profile}-beta.tar.gz"
        body = deterministic_tar_gz(collect(profile, root=root))
        outfile = outdir / filename
        if outfile.exists() or outfile.is_symlink():
            raise ValueError(f"Refusing to overwrite existing public beta asset {filename}")
        outfile.write_bytes(body)
        checksums[profile] = sha256(body)
        assets[filename] = checksums[profile]
    installer_template = (root / "scripts/install_istoreos_beta.sh").read_text(encoding="utf-8")
    for profile in TARGETS:
        installer_template = installer_template.replace("@SHA_" + profile.upper().replace("-", "_") + "@",
                                                        checksums[profile])
    installer_template = installer_template.replace("@RELEASE_TAG@", RELEASE_TAG)
    if "@SHA_" in installer_template or "@RELEASE_TAG@" in installer_template:
        raise ValueError("Unresolved beta installer asset digest placeholders")
    installer = outdir / "install-istoreos-beta.sh"
    if installer.exists() or installer.is_symlink():
        raise ValueError("Refusing to overwrite a beta installer")
    installer.write_text(installer_template, encoding="utf-8", newline="\n")
    installer.chmod(0o755)
    assets[installer.name] = sha256(installer.read_bytes())
    (outdir / "SHA256SUMS").write_text(
        "".join(f"{assets[k]}  {k}\n" for k in sorted(assets)),
        encoding="utf-8", newline="\n")
    return {"release_tag": RELEASE_TAG, "assets": assets,
            "firmware": "istoreos", "beta_only": True,
            "production_verified_matrix_unchanged": True,
            "physical_router_acceptance": "not_run"}


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--output", type=Path, required=True)
    args = a.parse_args()
    try:
        print(json.dumps(build(args.output), indent=2, ensure_ascii=False))
    except (OSError, ValueError) as err:
        a.exit(1, f"Refused iStoreOS public beta: {err}\n")
