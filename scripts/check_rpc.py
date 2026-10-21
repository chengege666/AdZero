#!/usr/bin/env python3
"""Actual rpcd/ubusd/ucode smoke in a disposable chroot; no router or TCP port.

Run with root inside WSL. Uses the checksum-pinned runtime archive and a ctl
fixture that itself calls rpcd, exercising asynchronous nested ubus handling.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time

from check_openwrt_runtime import ROOT, SHA256


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run as root inside Linux/WSL (disposable chroot only)')
    archive = ROOT/'artifacts/runtime/openwrt-24.10.8-x86-64-rootfs.tar.gz'
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == SHA256
    with tempfile.TemporaryDirectory(prefix='adzero-rpc-') as tmp:
        base = Path(tmp)
        with tarfile.open(archive) as tar:
            tar.extractall(base, filter='fully_trusted')  # verified official archive
        for path in ('var/run/ubus','tmp','dev','etc/adzero'):
            (base/path).mkdir(parents=True,exist_ok=True)
        os.mknod(base/'dev/null',0o666 | 0o20000,os.makedev(1,3))
        os.mknod(base/'dev/urandom',0o666 | 0o20000,os.makedev(1,9))
        (base/'var/run/ubus/ubus.sock').symlink_to('/tmp/ubus.sock')
        for relative in ('usr/share/rpcd/ucode/adzero','usr/libexec/adzero/policy-lib.uc','usr/share/rpcd/acl.d/luci-app-adzero.json'):
            target=base/relative; target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/'luci-app-adzero/root'/relative,target)
        ctl=base/'usr/libexec/adzero/ctl'
        ctl.write_text('''#!/bin/sh
# A nested rpcd operation would deadlock with synchronous popen in the plugin.
ubus -s /tmp/ubus.sock call session create '{"timeout":2}' >/tmp/nested.json || exit 1
case "$1" in
 lookup) printf '{"available":true,"domain":"%s","match":"none"}\\n' "$2";;
 pause) exit 1;;
 *) echo 'private-backend-token-not-for-browser';;
esac
'''); ctl.chmod(0o755)
        def run(*args): return subprocess.run(['chroot',tmp,*args],text=True,capture_output=True,timeout=12)
        procs=[]
        try:
            log=(ROOT/'artifacts/runtime/rpc-smoke.log').open('w+')
            procs.append(subprocess.Popen(['chroot',tmp,'/sbin/ubusd','-s','/tmp/ubus.sock'],stdout=log,stderr=log))
            time.sleep(.2)
            procs.append(subprocess.Popen(['chroot',tmp,'/sbin/rpcd','-s','/tmp/ubus.sock'],stdout=log,stderr=log))
            for _ in range(30):
                r=run('/bin/ubus','-s','/tmp/ubus.sock','-v','list','adzero')
                if 'lookup' in r.stdout: break
                time.sleep(.1)
            log.flush()
            assert 'lookup' in r.stdout,r.stdout+r.stderr+(ROOT/'artifacts/runtime/rpc-smoke.log').read_text()
            def call(method,data):
                r=run('/bin/ubus','-s','/tmp/ubus.sock','-t','8','call','adzero',method,json.dumps(data))
                assert r.returncode == 0,r.stdout+r.stderr
                return json.loads(r.stdout)
            reply=call('lookup',{'domain':'HTTPS://Example.COM/path'})
            assert reply.get('data',{}).get('domain')=='example.com',reply
            assert (base/'tmp/nested.json').exists()
            assert not call('lookup',{'domain':'x.example;id'})['ok']
            assert not call('pause',{'seconds':1})['ok']
            assert not call('pause',{'seconds':300})['ok']
            result=call('allow',{'domain':'ads.example','scope':'ads.example'})
            assert result['ok'] and 'private-backend' not in json.dumps(result)
            assert call('resume',{})['ok']
            assert run('/bin/ubus','call','adzero','exec','{}').returncode != 0
            report={'runtime':'pinned OpenWrt 24.10.8 rpcd/ubusd/ucode in isolated chroot',
                    'checks':8,'nested_rpcd_call':'passed','typed_input_and_no_log_leak':'passed','router':'not_touched'}
            (ROOT/'artifacts/runtime/rpc-result.json').write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps(report,indent=2))
        finally:
            for process in reversed(procs):
                process.terminate()
                process.wait(timeout=5)


if __name__ == '__main__': main()
