#!/usr/bin/env python3
"""Verify the immutable native archives reused by the unified release.

No firmware image, router mutation, extraction or publication. Live vendor
buildinfo audits remain separate because their latest URLs roll every release.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

from build_unified_release import DEPENDENCY_ORIGINS


def archive_specs(profile):
    fragments = {'armsr': 'armsr', 'rockchip-r6xs': 'r6xs', 'x86_64': 'x86_64', 'all': ''}
    if profile not in fragments:
        raise ValueError('Unknown native origin profile')
    for name, digest in DEPENDENCY_ORIGINS.items():
        if fragments[profile] not in name:
            continue
        tag = 'v0.21.5-istoreos-24108-beta.1' if '-24108-' in name else 'v0.21.5-istoreos-beta.4'
        yield name, digest, f'https://github.com/slobys/AdZero/releases/download/{tag}/{name}'


def verify_bytes(data, digest):
    if not isinstance(data, bytes) or not 0 < len(data) <= 64 * 1024 * 1024:
        raise ValueError('Native origin archive size is invalid')
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('Pinned native origin SHA-256 differs')


def audit(profile, cache):
    cache.mkdir(parents=True, exist_ok=True)
    verified = []
    for name, digest, url in archive_specs(profile):
        path = cache / name
        if path.is_symlink():
            raise ValueError('Native origin cache must not be a symlink')
        if path.exists():
            data = path.read_bytes()
        else:
            with urlopen(url, timeout=60) as response:
                data = response.read(64 * 1024 * 1024 + 1)
        verify_bytes(data, digest)
        if not path.exists():
            path.write_bytes(data)
        verified.append({'archive': name, 'sha256': digest, 'url': url})
    return {'profile': profile, 'verified_native_origins': verified,
            'validation': 'immutable_published_archive_sha256', 'live_latest_metadata': 'not_consulted',
            'sdk_build': 'not_run', 'device_acceptance': 'not_run', 'publishable': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True, choices=('armsr', 'rockchip-r6xs', 'x86_64', 'all'))
    parser.add_argument('--cache', type=Path, default=Path('artifacts/verified-native-origins'))
    args = parser.parse_args()
    print(json.dumps(audit(args.profile, args.cache), indent=2))
