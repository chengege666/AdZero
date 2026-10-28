#!/usr/bin/env python3
"""Run isolated mock checks with an official, SHA-256-pinned OpenWrt BusyBox.

Linux/WSL only. Downloads a small x86_64 rootfs to the development workspace,
extracts three runtime files, and never starts router services or installs it.
This is a userspace compatibility check, not a router or DNS integration test.
"""
import hashlib
import json
import os
import posixpath
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
import urllib.request

from build_sdk import source_hash

ROOT = Path(__file__).resolve().parents[1]
URL = "https://downloads.openwrt.org/releases/24.10.8/targets/x86/64/openwrt-24.10.8-x86-64-rootfs.tar.gz"
SHA256 = "6c94190246a54088e3984fc0c4cbbb518972abb2b10a28e30a0c41554eea8b9d"
FILES = {"./bin/busybox": "busybox", "./sbin/uci": "uci", "./lib/libc.so": "libc.so", "./lib/libgcc_s.so.1": "libgcc_s.so.1"}
# Use the actual OpenWrt applets, not GNU lookalikes on the development host.
APPLETS = ("sh", "awk", "sed", "grep", "tr", "cut", "sort", "mkdir", "rmdir", "cat", "rm", "dirname", "sha256sum", "date")


def main():
    if os.name == "nt" or os.uname().machine != "x86_64":
        raise SystemExit("Run this x86_64 runtime check in x86_64 Linux/WSL")
    cache = ROOT / "artifacts/runtime"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / "openwrt-24.10.8-x86-64-rootfs.tar.gz"
    if not archive.exists():
        with urllib.request.urlopen(URL, timeout=60) as response:
            data = response.read(16 * 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != SHA256:
            raise SystemExit("Official rootfs SHA-256 mismatch")
        archive.write_bytes(data)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise SystemExit("Cached rootfs SHA-256 mismatch")
    runtime = ROOT / ".sdk/runtime-24.10.8"
    runtime.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        for member_name, filename in FILES.items():
            member = tar.getmember(member_name)
            if not member.isfile():
                raise SystemExit("Unexpected runtime archive member type")
            (runtime / filename).write_bytes(tar.extractfile(member).read())
            (runtime / filename).chmod(0o755)
        # Same pinned rootfs also supplies ucode and its native module closure.
        members = {m.name.removeprefix('./'): m for m in tar.getmembers()}
        def content(member):
            for _ in range(12):
                if member.isfile():
                    return tar.extractfile(member).read()
                if not member.issym():
                    break
                target = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), member.linkname)).lstrip('/')
                member = members[target.removeprefix('./')]
            raise ValueError("Unexpected runtime link")
        for name, member in members.items():
            if name == 'usr/bin/ucode' or ('/lib/' in '/' + name and '.so' in Path(name).name):
                if member.isfile() or member.issym():
                    path = runtime / Path(name).name
                    path.write_bytes(content(member))
                    path.chmod(0o755)
    command = [str(runtime / "libc.so"), "--library-path", str(runtime), str(runtime / "busybox")]
    from prepare_dns_socket import prepare as prepare_socket
    prepare_socket(ROOT,runtime)
    wrappers = runtime / "wrappers"
    wrappers.mkdir(exist_ok=True)
    for applet in APPLETS:
        path = wrappers / applet
        path.write_text("#!/bin/sh\nexec " + shlex.join(command + [applet]) + ' "$@"\n')
        path.chmod(0o755)
    before = source_hash(ROOT / "luci-app-adzero")
    env = {**os.environ, "PATH": str(wrappers) + os.pathsep + os.environ["PATH"],
           "ADZERO_TEST_SHELL": shlex.join(command + ["ash"]),
           "ADZERO_UCODE": shlex.join([str(runtime / "libc.so"), "--library-path", str(runtime), str(runtime / "ucode"), "-L", str(runtime)])}
    for program in ('adapter', 'probe', 'policy', 'sources', 'routing-data', 'cache-curl', 'observe', 'dns-handoff', 'dns-enhance', 'dns-native', 'dns-guard', 'dns-pool'):
        subprocess.run(shlex.split(env['ADZERO_UCODE']) + ['-c', '-o', str(runtime / (program + '.ucb')),
                       str(ROOT / ('luci-app-adzero/root/usr/libexec/adzero/' + program + '.uc'))], check=True)
    subprocess.run(shlex.split(env["ADZERO_UCODE"]) + ["-c", "-o", str(runtime / "rpc.ucb"), str(ROOT / "luci-app-adzero/root/usr/share/rpcd/ucode/adzero")], check=True)
    subprocess.run(shlex.split(env["ADZERO_UCODE"]) + ["-c", "-o", str(runtime / "update-check.ucb"), str(ROOT / "luci-app-adzero/root/usr/libexec/adzero/update-check.uc")], check=True)
    result = subprocess.run(command + ["ash", "scripts/check.sh"], cwd=ROOT, env=env, text=True, capture_output=True)
    log = result.stdout + result.stderr
    (cache / "openwrt-24.10.8-check.log").write_text(log)
    stable = before == source_hash(ROOT / "luci-app-adzero")
    report = {
        "runtime": "OpenWrt 24.10.8 x86_64 BusyBox/ash and selected applets under WSL/Linux",
        "rootfs_url": URL, "rootfs_sha256": SHA256, "source_sha256": before,
        "source_stable": stable, "exit_code": result.returncode,
        "python_tests": int(re.search(r"Ran (\d+) tests", log)[1]) if re.search(r"Ran (\d+) tests", log) else None,
        "device_acceptance": "not_run", "ucode": "official rootfs interpreter and modules",
        "optional_parsers": {"ruby": bool(__import__('shutil').which('ruby')), "yq": bool(__import__('shutil').which('yq'))},
    }
    (cache / "openwrt-24.10.8-result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(log[-16000:] if result.returncode else result.stdout)
    print(json.dumps(report, indent=2))
    raise SystemExit(result.returncode if stable else 1)


if __name__ == "__main__":
    main()
