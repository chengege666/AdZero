#!/usr/bin/env python3
"""Exercise delivered catalogs/packages with isolated installer/PM fixtures.

Run in Linux/WSL. ADZERO_TEST_SHELL may select the pinned OpenWrt ash.
No real packages, router services or network settings are modified.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from test_installer import InstallerTest
from build_release import validate_release


def check(directory):
    if os.name != 'posix':
        raise ValueError('Run the isolated installer lifecycle in Linux/WSL')
    directory = directory.resolve()
    validate_release(directory)
    shell = shlex.split(os.environ.get('ADZERO_TEST_SHELL', 'sh'))
    # Require the entire verified release matrix for distribution packages,
    # including vendor-specific builds. Tests of single-row release catalogs
    # deliberately use build_release.validate_release() directly instead.
    from build_release import SUPPORTED_BUILDS, SUPPORTED_REVISIONS
    catalog_rows = (directory / 'releases.tsv').read_text().splitlines()
    available = {
        (parts[2], parts[3], parts[4], parts[6])
        for line in catalog_rows if not line.startswith('#')
        for parts in [line.split('\t')] if len(parts) in (7, 8)
    }
    if available != set(SUPPORTED_BUILDS):
        raise ValueError(
            f'Release must contain all exact SDK-verified identities; '
            f'missing={set(SUPPORTED_BUILDS)-available}'
        )
    # Each independently verified release identity must have a real delivered
    # package and two isolated upgrade checks. Never silently skip a newly
    # added ARM64 SDK target merely because an old test table listed x86 only.
    platforms = []
    supported_istoreos_abis = {
        'x86/64': 'x86_64',
        'rockchip/armv8': 'aarch64_generic',
        'armsr/armv8': 'aarch64_generic',
    }
    for (firmware, version, target, fmt), arch in sorted(SUPPORTED_BUILDS.items()):
        if firmware not in ('openwrt', 'immortalwrt', 'istoreos'):
            raise ValueError('Unknown firmware in SDK-verified delivery matrix')
        revision = SUPPORTED_REVISIONS.get((firmware, version, target, fmt))
        if firmware == 'istoreos':
            # A vendor-specific ABI and exact firmware revision must already
            # have passed provenance checks before this future release test.
            if (version != '25.12.6' or fmt != 'apk'
                    or revision != '2026102312'
                    or supported_istoreos_abis.get(target) != arch):
                raise ValueError('Unknown iStoreOS build revision or ABI; refuse delivery')
        elif revision is not None:
            raise ValueError('Non-iStoreOS release has an unexpected vendor revision')
        target_part = '' if target == 'x86/64' else target.replace('/', '-') + '-'
        filename = f'adzero-{firmware}-{version}-{target_part}{arch}.{fmt}'
        platforms.append((firmware, version, target, arch, fmt, filename, revision))
    results = []
    for firmware, version, target, arch, fmt, expected_suffix, revision in platforms:
        for ending in ('LF', 'CRLF'):
            kind = f'{firmware}-{version}-{target}-{fmt}'
            fixture = InstallerTest()
            fixture.setUp()
            try:
                if fmt == 'apk':
                    # Only known target ABIs exercise the apk-tools aarch64
                    # CPU alias. Other targets must match their package arch
                    # literally, rather than guessing from 64-bit hardware.
                    cpu_arch = ("aarch64" if target in (
                        'rockchip/armv8', 'mediatek/filogic', 'armsr/armv8'
                    ) and arch in ('aarch64_generic', 'aarch64_cortex-a53') else arch)
                    fixture.arm_apk(arch=cpu_arch)
                original_id = {
                    'openwrt': 'OpenWrt', 'immortalwrt': 'ImmortalWrt',
                    'istoreos': 'iStoreOS',
                }[firmware]
                fixture.write('etc/openwrt_release',
                              f"DISTRIB_ID='{original_id}'\nDISTRIB_RELEASE='{version}'\n"
                              f"DISTRIB_TARGET='{target}'\nDISTRIB_ARCH='{arch}'\n"
                              + (f"DISTRIB_REVISION='{revision}'\n" if revision else ''))
                delivered = fixture.base / 'delivered'
                shutil.copytree(directory, delivered)
                if ending == 'CRLF':
                    path = delivered / 'releases.tsv'
                    path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
                fixture.upgrade_fixture()
                result = subprocess.run(shell + [
                    str(delivered / 'install.sh'), '--local-dir', str(delivered),
                    '--upgrade', '--no-enable',
                ], env=fixture.env, text=True, capture_output=True, timeout=20)
                if result.returncode:
                    raise AssertionError(kind + ' ' + ending + ': ' + result.stdout + result.stderr)
                assert expected_suffix in result.stdout, result.stdout
                expected = (['opkg update', 'ctl disable', 'opkg install']
                            if fmt == 'ipk' else
                            ['apk check-local', 'ctl disable', 'apk add-local'])
                assert fixture.log.read_text().splitlines() == expected
                assert list((fixture.root / 'etc/adzero-backups').glob('*/state.tar.gz'))
                results.append({'target': kind, 'catalog_ending': ending,
                                'selection_checksum_backup_restore_install': 'passed'})
            finally:
                fixture.doCleanups()
    return {'checks': len(results), 'cases': results,
            'scope': 'actual delivered installer, catalog and SDK package bytes; mock PM/service operations in private roots; not a real router installation'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = check(args.directory)
    text = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8', newline='\n')
    print(text, end='')
