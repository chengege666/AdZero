#!/usr/bin/env python3
"""Pinned iStoreOS ARM64 vendor firmware metadata. Candidate only, never an SDK.

Sources are the exact official 25.12.6-2026102312 ARM64 firmware buildinfo.
No OpenWrt SDK or x86 iStoreOS package may be reused for either ARM target.
"""
import hashlib
import json
from urllib.request import urlopen

from probe_istoreos import SOURCE_REPO, SOURCE_COMMIT

FIRMWARE_RELEASE = "25.12.6"
FIRMWARE_REVISION = "2026102312"

# Distinct vendor image/build metadata even though these two targets currently
# share the iStoreOS source commit. In particular Rockchip has 15 feeds and
# ARMSR 13; do not derive provenance from CPU bitness alone.
PROFILES = {
    "armsr": {
        "origin": "https://fw20.koolcenter.com/iStoreOS/armsr/",
        "target": "armsr/armv8",
        "arch": "aarch64_generic",
        "image": "istoreos-25.12.6-2026102312-armsr-squashfs-combined-efi.img.gz",
        "image_sha256": "e1f74b1eadd7a73df4559086c93af53f5ea692b3f1d5f30e8f9afea34112bb7c",
        "commit_prefix": "283d0263",
        "feeds": 13,
        "target_config": ("CONFIG_TARGET_armsr=y", "CONFIG_TARGET_armsr_armv8=y"),
        "metadata_sha256": {
            "commit.buildinfo": "e1c9143cf3f289c5eaf426f8e58f9d5822847e01e003ab33ab5705bddcc3f17a",
            "config.buildinfo": "e64fddafacda5c88ded6195a36846527de1c20aca67b4f08a2a8d26bb443a06b",
            "feeds.buildinfo": "bc91c22e8c63dfaad7957e7eab86a82ad869533022a9bc02ba3aaa9f56c7f726",
            "feeds.conf": "0e1e93ff3683ed79a0bbe95514f00b03f6502c0a8cd23e2755b170e52941cf80",
            "version.latest.v2": "601d7b12047d5c3503cb86d3e953935791a9d89feb1a1f78582975405d662ac2",
        },
    },
    "rockchip-r6xs": {
        "origin": "https://fw20.koolcenter.com/iStoreOS/r6xs/",
        "target": "rockchip/armv8",
        "arch": "aarch64_generic",
        "image": "istoreos-25.12.6-2026102312-r6xs-squashfs.img.gz",
        "image_sha256": "ad9098cad8728a3d50331b1b9701565271e594b57e3aff8dc3a831b951eba6d6",
        "commit_prefix": "283d02639c",
        "feeds": 15,
        "target_config": ("CONFIG_TARGET_rockchip=y", "CONFIG_TARGET_rockchip_armv8=y"),
        "metadata_sha256": {
            "commit.buildinfo": "c6881809e1fb27240acfa997f934d068c4eff35361e2a276fe76e156c6689c91",
            "config.buildinfo": "a7c1677808c1e4c73c281651731ca04e7d6a7eced1bf1b9aecffdd9363b3c517",
            "feeds.buildinfo": "f22cf89fe73d4a1558219e5a9968ac6eb1ed1e206722d8847d28bf479d793316",
            "feeds.conf": "429a305f6cceff936e7487fd1974a3fa18fa37750e2780ce10d05530213be283",
            "version.latest.v2": "a3bc1d0cbac312398a3a2ba8c6785fd8e18a6f691eeba9b345bdcbce8f71b487",
        },
    },
}


def profile_spec(profile):
    try:
        return PROFILES[profile]
    except KeyError as exc:
        raise ValueError("Unrecognized iStoreOS ARM64 firmware profile") from exc


def read_remote(profile, url):
    spec = profile_spec(profile)
    if not url.startswith(spec["origin"]) or url.removeprefix(spec["origin"]) not in spec["metadata_sha256"]:
        raise ValueError("Untrusted iStoreOS ARM64 buildinfo address")
    with urlopen(url, timeout=35) as response:
        return response.read(64 * 1024 + 1)


def validate_metadata(profile, read):
    spec = profile_spec(profile)
    files = {}
    for name, expected in spec["metadata_sha256"].items():
        data = read(spec["origin"] + name)
        if not isinstance(data, bytes) or not 0 < len(data) <= 64 * 1024:
            raise ValueError(f"Missing or oversized official iStoreOS ARM64 buildinfo: {name}")
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"Official iStoreOS ARM64 metadata checksum differs: {name}")
        files[name] = data.decode("utf-8")
    if files["commit.buildinfo"].strip() != spec["commit_prefix"] or not SOURCE_COMMIT.startswith(spec["commit_prefix"]):
        raise ValueError("ARM64 vendor source commit differs from the exact pinned source")
    config = files["config.buildinfo"].splitlines()
    if 'CONFIG_VERSION_DIST="iStoreOS"' not in config or not all(x in config for x in spec["target_config"]):
        raise ValueError("Official iStoreOS ARM64 target configuration differs")
    lines = files["feeds.buildinfo"].splitlines()
    if len(lines) != spec["feeds"] or not any(line.startswith("src-git packages ") for line in lines) or not any(line.startswith("src-git luci ") for line in lines):
        raise ValueError("Official iStoreOS ARM64 feed set differs")
    latest = files["version.latest.v2"]
    if not latest.startswith(f'[{spec["image"]}]({spec["image"]})') or f'SHA256: {spec["image_sha256"]}' not in latest:
        raise ValueError("ARM64 official firmware image/revision checksum differs")
    return {
        "firmware": "istoreos",
        "vendor_profile": profile,
        "source_repo": SOURCE_REPO,
        "source_commit": SOURCE_COMMIT,
        "version": FIRMWARE_RELEASE + "-" + FIRMWARE_REVISION,
        "target": spec["target"],
        "arch_expected_from_vendor_target": spec["arch"],
        "official_image": spec["image"],
        "official_image_sha256_reference": spec["image_sha256"],
        "vendor_build_metadata": spec["origin"],
        "metadata_sha256": spec["metadata_sha256"],
        "vendor_feed_count": len(lines),
        "sdk_build": "not_run",
        "device_acceptance": "not_run",
        "publishable": False,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=tuple(PROFILES))
    args = parser.parse_args()
    print(json.dumps(validate_metadata(args.profile, lambda url: read_remote(args.profile, url)),
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
