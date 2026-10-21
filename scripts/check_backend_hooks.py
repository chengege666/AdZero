#!/usr/bin/env python3
"""Reproduce upstream init exit codes with actual pinned shell functions.

Only extracts start/stop/dl and notification hooks; procd calls are fixtures.
No service startup, router connection, UCI or firewall modification occurs.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

from check_rule_source import fetch, ROOT
from build_sdk import source_hash

SOURCES = {
    "adblock-fast-1.2.4-r4.init": (
        "https://raw.githubusercontent.com/openwrt/packages/65493e273e4b9cd7014236b69fd6fdc617b88436/net/adblock-fast/files/etc/init.d/adblock-fast",
        "630f27de08507520a03e1378c1a7018cb64bc7b499b0e7456cbc8697e80fa9e2"),
    "rc-common-25.12.5.sh": (
        "https://raw.githubusercontent.com/openwrt/openwrt/v25.12.5/package/base-files/files/etc/rc.common",
        "dd8ae95c78d10cccf78cb487874f163ace4c1ee14dace05fe28393b19ba639e4"),
}


def main():
    sources = {}
    for name, (url, sha) in SOURCES.items():
        path = ROOT / 'artifacts/upstream' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            fetch(url, path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError('Upstream shell source checksum mismatch')
        sources[name] = path.read_text()
    init = sources['adblock-fast-1.2.4-r4.init']
    common = sources['rc-common-25.12.5.sh']
    hooks = '\n'.join(re.search(r'^' + name + r'\(\).*$', init, re.M)[0]
                      for name in ('service_started', 'service_stopped'))
    functions = '\n'.join(re.search(r'^\t' + name + r'\(\) \{\n.*?^\t\}', common, re.M | re.S)[0]
                          for name in ('start', 'stop'))
    functions += '\n' + re.search(r'^dl\(\).*$', init, re.M)[0]
    # Exact upstream shell bodies, with external operations explicitly inert.
    stubs = '\n'.join(name + '() { return 0; }' for name in
                      ('rc_procd', 'procd_set_config_changed', 'procd_lock', 'procd_kill', 'stop_service'))
    shell = shlex.split(os.environ.get('ADZERO_TEST_SHELL', 'sh'))
    results = []
    for flag in ('', '1'):
        for action in ('start', 'stop', 'dl'):
            program = hooks + '\n' + functions + '\n' + stubs + '\ninitscript=/etc/init.d/adblock-fast\n_fw4_restart=' + shlex.quote(flag) + '\n' + action
            result = subprocess.run(shell + ['-c', program], text=True, capture_output=True, timeout=10)
            expected = 0 if flag == '1' else 1
            if result.returncode != expected:
                raise ValueError('Unexpected upstream hook result: ' + result.stderr)
            results.append({'action':action, 'fw4_restart':flag == '1', 'returncode':result.returncode})
    report = {'upstream':'adblock-fast 1.2.4-r4 / OpenWrt 25.12.5 rc.common',
              'sources':{name:sha for name, (_, sha) in SOURCES.items()}, 'cases':results,
              'source_sha256':source_hash(ROOT / 'luci-app-adzero'),
              'scope':'exact upstream shell bodies; inert procd fixtures; no live service lifecycle'}
    path = ROOT / 'artifacts/runtime/backend-hook-result.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
