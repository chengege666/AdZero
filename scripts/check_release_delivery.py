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
    results = []
    for kind in ('24.10.8-x86-ipk', '25.12.5-x86-apk', '25.12.5-rockchip-apk'):
        for ending in ('LF', 'CRLF'):
            fixture = InstallerTest()
            fixture.setUp()
            try:
                if not kind.endswith('ipk'):
                    arm = 'rockchip' in kind
                    fixture.arm_apk(arch='aarch64' if arm else 'x86_64')
                    if not arm:
                        fixture.write('etc/openwrt_release', "DISTRIB_ID='OpenWrt'\nDISTRIB_RELEASE='25.12.5'\nDISTRIB_TARGET='x86/64'\nDISTRIB_ARCH='x86_64'\n")
                delivered = fixture.base / 'delivered'
                shutil.copytree(directory, delivered)
                if ending == 'CRLF':
                    path = delivered / 'releases.tsv'
                    path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
                fixture.upgrade_fixture()
                result = subprocess.run(shell + [str(delivered / 'install.sh'), '--local-dir', str(delivered), '--upgrade', '--no-enable'],
                                        env=fixture.env, text=True, capture_output=True, timeout=20)
                if result.returncode:
                    raise AssertionError(kind + ' ' + ending + ': ' + result.stdout + result.stderr)
                suffix = 'rockchip-armv8-aarch64_generic.apk' if 'rockchip' in kind else ('25.12.5-x86_64.apk' if kind.endswith('apk') else '24.10.8-x86_64.ipk')
                assert suffix in result.stdout, result.stdout
                manager = 'opkg' if kind.endswith('ipk') else 'apk'
                expected=['opkg update','ctl disable','opkg install'] if manager=='opkg' else ['apk check-local','ctl disable','apk add-local']
                assert fixture.log.read_text().splitlines() == expected
                assert list((fixture.root / 'etc/adzero-backups').glob('*/state.tar.gz'))
                results.append({'target': kind, 'catalog_ending': ending, 'selection_checksum_backup_restore_install': 'passed'})
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
