#!/usr/bin/env python3
"""Build separate iStoreOS 24.10.8 OPKG test archives from proven native IPKs.

Vendor firmware metadata/images, original package databases and 7 missing
official factory-feed dependencies MUST be present and SHA-pinned. Never
substitute an OpenWrt SDK or the iStoreOS 25.12 APK. Not a stable release.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

from build_sdk import PACKAGE, source_hash

ROOT = Path(__file__).resolve().parents[1]
TAG = "v0.21.5-istoreos-24108-beta.1"
VER = "24.10.8"
REV = "2026073111"
APP_VER = "0.21.5-r1"
APP_NAME = f"luci-app-adzero_{APP_VER}_all.ipk"
SOURCE_SHA = "8df7589827fdc1adc418c3b83887097589b257a4a7654ac0dd91ddf878ee60c9"
HISTORICAL_SOURCE = "a405f0378aef729f0f250c94b18a34a09b7d8890"
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
FILE = re.compile(r"[a-zA-Z0-9_.+~-]+\.ipk\Z")
ROOT_DEPS = frozenset(("luci-base", "adblock-fast", "curl", "rpcd-mod-file",
                       "rpcd-mod-ucode", "ca-bundle", "ucode", "ucode-mod-fs",
                       "ucode-mod-uci", "ucode-mod-ubus", "ucode-mod-uloop",
                       "ucode-mod-socket", "tcpdump", "conntrack",
                       "coreutils-timeout"))
PROFILES = {
    "x86_64": {
        "target": "x86/64", "arch": "x86_64", "build_dir": "x86",
        "image_sha": "2ce609e2625f9ba67723ec29b0b509baa300c6b74f528596490d950909e09a9c",
        "raw_sha": "431470911d0aac490c14e744c8213c057819f1c1ac72bc66aa428bf4f8315170",
        "config_sha": "b2ae3d3faa52b28595dd4597a691f9659deb94084056ddea4855a74ba4e39c44",
        "feed_sha": "fc18878e95b97235e70edffe525c8236d25a0c1a76ffa3f29a62b76f236b2b05",
        "feed_count": 12, "original_installed": 1041,
    },
    "armsr": {
        "target": "armsr/armv8", "arch": "aarch64_generic", "build_dir": "armsr",
        "image_sha": "361c7b1657422a1217d74fbcd3aeb09c56dcea40503a46d35494a45b5feeeefb",
        "raw_sha": "7d5bd7abba081402b1265e243e0d1474e22a4ba66e7ba72ccb91ee0e10bc1355",
        "config_sha": "2af1b50f2fe6d5273d0e20eccc705a599612a9aca6ef173f00aed63508740ae7",
        "feed_sha": "fc18878e95b97235e70edffe525c8236d25a0c1a76ffa3f29a62b76f236b2b05",
        "feed_count": 12, "original_installed": 1001,
    },
    "r6xs": {
        "target": "rockchip/armv8", "arch": "aarch64_generic", "build_dir": "r6xs",
        "image_sha": "8b916526ecb19d450b88eb1a198c39aa00c43e1c63d086c7a4040150d8298c14",
        "raw_sha": "783858ab2c6ee31d8a1339f9b57dba0a27fbfb38c619e8bc4ccfe237e6bf8731",
        "config_sha": "1c2da6a3f619ef444d50115700996f3c23d90a5fd1ed0874b89e30c65d68e879",
        "feed_sha": "5a660b4dae2a80f23bd5c153d266d70b0b1d37ce6ee03030d11a5363ad6f2b2f",
        "feed_count": 14, "original_installed": 922,
    },
}


def digest(content):
    return hashlib.sha256(content).hexdigest()

def file_digest(path):
    """Stream huge original factory images without loading them into memory."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Original factory image missing or symlinked")
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()



def readable(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or symlinked original firmware dependency")
    return path.read_bytes()


def ipk_control(ipk):
    """Parse the vendor's gzip-tar OPKG IPK (NOT Debian ar-format)."""
    with tarfile.open(ipk, mode="r:gz") as outer:
        members = outer.getmembers()
        filenames = [item.name.removeprefix("./") for item in members]
        if (len(members) != 3 or set(filenames) !=
                {"debian-binary", "control.tar.gz", "data.tar.gz"} or
                any(not item.isfile() for item in members)):
            raise ValueError("Original 24.10 IPK must be a three-file gzip tar archive")
        chunks = {name: outer.extractfile(item).read() for name, item in zip(filenames, members)}
    if chunks["debian-binary"] != b"2.0\n" or not chunks["data.tar.gz"].startswith(b"\x1f\x8b"):
        raise ValueError("Original OPKG archive member headers invalid")
    with tarfile.open(fileobj=io.BytesIO(chunks["control.tar.gz"]), mode="r:gz") as control:
        headers = [item for item in control.getmembers()
                   if item.name in ("control", "./control") and item.isfile()]
        if len(headers) != 1:
            raise ValueError("IPK has no unique OPKG control header")
        raw = control.extractfile(headers[0]).read().decode("utf-8")
    return dict(re.findall(r"^([A-Za-z0-9-]+): ([^\n]+)$", raw, re.M))


def validated_bundle(profile, *, root=ROOT):
    if profile not in PROFILES:
        raise ValueError("Unsupported exact iStoreOS 24.10.8 target")
    spec = PROFILES[profile]
    if source_hash(root / "luci-app-adzero") != SOURCE_SHA:
        raise ValueError("AdZero source changed; native package must be rebuilt")
    meta = root / ".sdk/istoreos-24108-official-metadata" / profile
    for filename, expected in (("24.10-config.buildinfo", spec["config_sha"]),
                               ("24.10-feeds.buildinfo", spec["feed_sha"])):
        if digest(readable(meta / filename)) != expected:
            raise ValueError("Original vendor config/feeds SHA mismatch")
    if len(readable(meta / "24.10-feeds.buildinfo").splitlines()) != spec["feed_count"]:
        raise ValueError("Wrong original vendor feed count")
    images = root / ".sdk/istoreos-24108-official-images"
    report = json.loads(readable(images / "original-image-report.json"))
    check = report[profile]
    if (check["gzip_sha256"] != spec["image_sha"]
            or check["raw_sha256"] != spec["raw_sha"]
            or len(check["squashfs_offsets"]) != 1):
        raise ValueError("Official firmware image checksum or squashfs offset missing")
    if (any(Path(check[k]).name != check[k] for k in ("gzip_filename", "raw_filename")) or
            file_digest(images / check["gzip_filename"]) != spec["image_sha"] or
            file_digest(images / check["raw_filename"]) != spec["raw_sha"]):
        raise ValueError("Actual original compressed/raw vendor firmware images changed")

    status = readable(images / (profile + "-usr_lib_opkg_status")).decode("utf-8")
    installed = {}
    for text in status.split("\n\n"):
        fields = dict(re.findall(r"^([A-Za-z0-9-]+): ([^\n]+)$", text, re.M))
        if "Package" in fields:
            installed[fields["Package"]] = fields
    if (len(installed) != spec["original_installed"]
            or not {"luci-base", "rpcd", "tcpdump", "opkg"}.issubset(installed)
            or "luci-app-adzero" in installed or "adblock-fast" in installed):
        raise ValueError("Original OPKG database does not match preserved 24.10 image")
    release_lines = readable(images / (profile + "-etc_openwrt_release")).decode("utf-8").splitlines()
    must = (f"DISTRIB_ID='iStoreOS'", f"DISTRIB_RELEASE='{VER}'",
            f"DISTRIB_REVISION='{REV}'", f"DISTRIB_TARGET='{spec['target']}'",
            f"DISTRIB_ARCH='{spec['arch']}'")
    if any(x not in release_lines for x in must):
        raise ValueError("Official original firmware target/revision/arch mismatch")

    native = root / (".sdk/istoreos-24108-" + spec["build_dir"] + "-source")
    if native.is_symlink() or not native.is_dir():
        raise ValueError("Missing real vendor 24.10 Buildroot")
    source = native / "package/luci-app-adzero"
    if source_hash(source) != SOURCE_SHA:
        raise ValueError("Native package sources differ")
    actual_commit = subprocess.check_output(["git", "-C", str(native), "rev-parse", "HEAD"], text=True).strip()
    if actual_commit != HISTORICAL_SOURCE:
        raise ValueError("Native Buildroot differs from pinned 24.10 historical source")
    pinned_feeds = readable(meta / "24.10-feeds.buildinfo").decode("utf-8").splitlines()
    for entry in pinned_feeds:
        match = re.fullmatch(
            r"src-git ([a-z0-9_]+) https://github\.com/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+\.git\^([a-f0-9]{40})",
            entry,
        )
        if not match:
            raise ValueError("Original vendor feed metadata format invalid")
        feed, commit = match.groups()
        installed_feed = native / "feeds" / feed
        if installed_feed.is_symlink() or not installed_feed.is_dir():
            raise ValueError(f"Missing original vendor feed {feed}")
        observed = subprocess.check_output(
            ["git", "-C", str(installed_feed), "rev-parse", "HEAD"], text=True
        ).strip()
        if observed != commit:
            raise ValueError(f"Original vendor pinned feed differs: {feed}")
    config_lines = (native / ".config").read_text(encoding="utf-8").splitlines()
    board, subtarget = spec["target"].split("/", 1)
    for entry in (
        f'CONFIG_TARGET_BOARD="{board}"',
        f'CONFIG_TARGET_SUBTARGET="{subtarget}"',
        f'CONFIG_TARGET_ARCH_PACKAGES="{spec["arch"]}"',
        "CONFIG_PACKAGE_luci-app-adzero=m",
    ):
        if entry not in config_lines:
            raise ValueError("Native Buildroot OPKG target ABI or AdZero configuration differs")
    if "CONFIG_USE_APK=y" in config_lines:
        raise ValueError("iStoreOS 24.10 vendor target must build an OPKG IPK")

    app_matches = sorted((native / "bin/packages").rglob(APP_NAME))
    if len(app_matches) != 1 or app_matches[0].is_symlink():
        raise ValueError("Native vendor Buildroot has not built the exact original OPKG IPK")
    app = app_matches[0]
    original_ipk = readable(app)
    control = ipk_control(app)
    if (control.get("Package") != "luci-app-adzero"
            or control.get("Version") != APP_VER
            or control.get("Architecture") != "all"
            or not ROOT_DEPS.issubset(set(re.findall(r"[a-zA-Z0-9_.+-]+", control.get("Depends", ""))))):
        raise ValueError("Wrong original OPKG package control or missing dependencies")
    if not 1000 < len(original_ipk) < 24 * 1024 * 1024:
        raise ValueError("Unexpected original IPK size")

    deps_path = root / ".sdk/istoreos-24108-native-deps" / profile
    evidence = json.loads(readable(deps_path / "closure.json"))
    missing = evidence.get("missing_native_packages")
    if (evidence.get("profile") != profile or evidence.get("release") != VER
            or evidence.get("revision") != REV
            or evidence.get("package_manager") != "opkg"
            or evidence.get("original_full_tcpdump_preserved") is not True
            or len(missing) != 7):
        raise ValueError("Incomplete original-firmware native dependency closure")
    payload = {"packages/" + APP_NAME: original_ipk}
    for name, item in sorted(missing.items()):
        if name in installed or item["name"] != name or item["arch"] not in ("all", spec["arch"]):
            raise ValueError("Attempt to reinstall existing or foreign-arch original package")
        path = deps_path / item["filename"]
        if not FILE.fullmatch(path.name) or not path.name.startswith(name + "_"):
            raise ValueError("Invalid factory dependency IPK filename")
        content = readable(path)
        if digest(content) != item["sha256"]:
            raise ValueError("Original OPKG repository package SHA mismatch")
        dependency_info = ipk_control(path)
        if (dependency_info.get("Package") != name or
                dependency_info.get("Version") != item["version"] or
                dependency_info.get("Architecture") != item["arch"]):
            raise ValueError("OPKG vendor dependency header differs from original index")

        payload["packages/" + path.name] = content
    if len(payload) != 8:
        raise ValueError("Expected one real native AdZero IPK and seven factory dependencies")

    meta_data = {
        "schema_version": 1, "channel": "user_opt_in_istoreos_24108_experimental_beta",
        "release_tag": TAG, "firmware": "istoreos", "release": VER,
        "revision": REV, "profile": profile, "target": spec["target"],
        "arch": spec["arch"], "format": "ipk", "original_image_sha256": spec["image_sha"],
        "original_image_raw_sha256": spec["raw_sha"],
        "original_installed_packages": spec["original_installed"],
        "original_feed_config_sha256": spec["config_sha"],
        "original_feed_commit_sha256": spec["feed_sha"], "vendor_feed_count": spec["feed_count"],
        "historical_vendor_source": HISTORICAL_SOURCE,
        "historical_vendor_source_exact_build_commit_attested": False,
        "native_buildroot_ipk_sha256": digest(original_ipk),
        "application_source_sha256": SOURCE_SHA,
        "factory_feed_dependencies": [{"name": name, "file": row["filename"],
            "version": row["version"], "sha256": row["sha256"],
            "architecture": row["arch"]} for name, row in sorted(missing.items())],
        "all_other_existing_packages_preserved": True, "default_enable": False,
        "physical_router_acceptance": "not_run", "stable_approved": False,
    }
    payload["manifest.json"] = (json.dumps(meta_data, sort_keys=True, indent=2) + "\n").encode()
    payload["profile.tsv"] = (f"istoreos\t{VER}\t{REV}\t{spec['target']}\t{spec['arch']}\t{profile}\tipk\n").encode()
    payload["SHA256SUMS"] = "".join(f"{digest(payload[name])}  {name}\n"
                                 for name in sorted(payload)).encode()
    return payload


def tgz(files):
    memory = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=memory, compresslevel=9, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            for name in sorted(files):
                data = files[name]
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
    return memory.getvalue()


def build(destination, *, root=ROOT):
    destination = Path(destination)
    if not destination.is_dir() or destination.is_symlink():
        raise ValueError("Create a new, non-symlinked target output directory first")
    assets = {}
    for profile in PROFILES:
        name = f"adzero-istoreos-24108-{profile}-beta.tar.gz"
        data = tgz(validated_bundle(profile, root=root))
        output = destination / name
        if output.exists() or output.is_symlink():
            raise ValueError("Refusing to overwrite a previously generated firmware beta")
        output.write_bytes(data)
        assets[name] = digest(data)
    installer = (root / "scripts/install_istoreos_24108_beta.sh").read_text()
    installer = installer.replace("@RELEASE_TAG@", TAG)
    for profile in PROFILES:
        name = f"adzero-istoreos-24108-{profile}-beta.tar.gz"
        installer = installer.replace("@SHA_" + profile.upper() + "@", assets[name])
    if "@SHA_" in installer or "@RELEASE_TAG@" in installer:
        raise ValueError("Unresolved vendor release hash placeholders")
    install_name = "install-istoreos-24108-beta.sh"
    installed = destination / install_name
    if installed.exists():
        raise ValueError("Release installer already exists")
    installed.write_text(installer, encoding="utf-8", newline="\n")
    installed.chmod(0o755)
    assets[install_name] = digest(installed.read_bytes())
    (destination / "SHA256SUMS").write_text(
        "".join(f"{assets[name]}  {name}\n" for name in sorted(assets)))
    return {"release_tag": TAG, "assets": assets, "format": "ipk",
            "targets": len(PROFILES), "historical_source_exact_firmware_attested": False,
            "physical_router_acceptance": "not_run", "public_stable_matrix_unchanged": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.output), indent=2, ensure_ascii=False))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"iStoreOS 24.10.8 beta build refused: {exc}\n")
