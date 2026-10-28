#!/usr/bin/env python3
"""Read-only verification of exact iStoreOS x86/64 firmware build provenance.

This does NOT download or build an SDK, add a supported release, or install on
a router. A firmware image and a source commit are not an ABI-certified SDK.
"""
import hashlib
import json
from urllib.request import urlopen

ORIGIN = "https://fw20.koolcenter.com/iStoreOS/x86_64/"
SOURCE_REPO = "https://github.com/istoreos/istoreos"
SOURCE_COMMIT = "283d02639c740f8ae6e9425b48be8c61f152c6b8"
FIRMWARE_VERSION = "25.12.6-2026102312"
IMAGE_FILENAME = f"istoreos-{FIRMWARE_VERSION}-x86-64-squashfs-combined.img.gz"

# The literal source is a published vendor firmware's build metadata, not
# an SDK tarball. SHA-256 pins prevent silently switching to a later build.
METADATA_SHA256 = {
    "commit.buildinfo": "c6881809e1fb27240acfa997f934d068c4eff35361e2a276fe76e156c6689c91",
    "config.buildinfo": "98d38b8909179366d648611efeb0e86de7be03975a866555b8e61971a83a60f2",
    "feeds.buildinfo": "bc91c22e8c63dfaad7957e7eab86a82ad869533022a9bc02ba3aaa9f56c7f726",
    "feeds.conf": "0e1e93ff3683ed79a0bbe95514f00b03f6502c0a8cd23e2755b170e52941cf80",
    "version.latest.v2": "b1670a2256afdc3032021895fdc30da4479c6dce36b323566f608a8c99e22ab7",
}


def validate_metadata(read):
    actual = {}
    for name, digest in METADATA_SHA256.items():
        data = read(ORIGIN + name)
        if not isinstance(data, bytes) or len(data) == 0 or len(data) > 64 * 1024:
            raise ValueError(f"Invalid iStoreOS metadata file: {name}")
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"iStoreOS vendor metadata changed: {name}; review before updating pins")
        actual[name] = data.decode("utf-8")
    if actual["commit.buildinfo"].strip() != SOURCE_COMMIT[:10]:
        raise ValueError("Vendor source commit differs from pinned iStoreOS source")
    if f'CONFIG_VERSION_DIST="iStoreOS"' not in actual["config.buildinfo"]:
        raise ValueError("Vendor build has wrong CONFIG_VERSION_DIST")
    if not actual["version.latest.v2"].startswith(f"[{IMAGE_FILENAME}]({IMAGE_FILENAME})"):
        raise ValueError("Vendor latest image no longer matches pinned build")
    if "src-git packages " not in actual["feeds.buildinfo"] or "src-git luci " not in actual["feeds.buildinfo"]:
        raise ValueError("Vendor feed source revisions missing")
    return {
        "firmware": "istoreos",
        "version": FIRMWARE_VERSION,
        "target": "x86/64",
        "firmware_id_observed": "iStoreOS",
        "source_repo": SOURCE_REPO,
        "source_commit": SOURCE_COMMIT,
        "vendor_build_metadata": ORIGIN,
        "official_image": IMAGE_FILENAME,
        "metadata_sha256": METADATA_SHA256,
        "sdk_build": "not_run",
        "package_format": "requires_actual_device_and_vendor_sdk_confirmation",
        "device_acceptance": "not_run",
        "publishable": False,
    }


def read_remote(url):
    if not url.startswith(ORIGIN) or url.removeprefix(ORIGIN) not in METADATA_SHA256:
        raise ValueError("Unexpected vendor metadata location")
    with urlopen(url, timeout=35) as response:
        data = response.read(64 * 1024 + 1)
    return data


if __name__ == "__main__":
    print(json.dumps(validate_metadata(read_remote), indent=2, ensure_ascii=False))
