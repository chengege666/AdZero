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
        for relative in ('usr/share/rpcd/ucode/adzero','usr/libexec/adzero/policy-lib.uc','usr/libexec/adzero/source-lib.uc','usr/libexec/adzero/job','usr/share/rpcd/acl.d/luci-app-adzero.json'):
            target=base/relative; target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/'luci-app-adzero/root'/relative,target)
            if relative.endswith('/job'): target.chmod(0o755)
        uuid=base/'proc/sys/kernel/random/uuid';uuid.parent.mkdir(parents=True,exist_ok=True)
        uuid.write_text('12345678-1234-1234-1234-123456789012\n')
        ctl=base/'usr/libexec/adzero/ctl'
        ctl.write_text('''#!/bin/sh
# A nested rpcd operation would deadlock with synchronous popen in the plugin.
ubus -s /tmp/ubus.sock call session create '{"timeout":2}' >/tmp/nested.json || exit 1
case "$1" in
 lookup) printf '{"available":true,"domain":"%s","match":"none"}\\n' "$2";;
 pause) exit 1;;
 source-add) sleep 2;;
 sources-list) echo '{"catalog":[],"items":[],"pending":false}';;
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
                if r.returncode:
                    debug={str(p.relative_to(base)):p.read_text() for p in (base/'tmp/adzero-jobs').glob('*/result*')}
                    raise AssertionError(r.stdout+r.stderr+json.dumps(debug))
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
            assert call('source_list',{})['data']['items']==[]
            assert not call('source_add',{'catalog':'','name':'test','url':'http://example.com/list','format':'domains'})['ok']
            assert not call('source_toggle',{'id':'../../etc','expected_url':'x','enabled':True})['ok']
            start=time.monotonic()
            started=call('source_add',{'catalog':'adaway','name':'','url':'','format':'hosts'})
            assert time.monotonic()-start < 1.5,'launcher waited for worker'
            assert started['ok'] and started['job']=='12345678-1234-1234-1234-123456789012',started
            for _ in range(30):
                done=call('job_status',{'job':started['job']})
                if not done.get('pending'): break
                time.sleep(.1)
            assert done.get('ok') and not done.get('pending'),done
            assert 'private-backend' not in json.dumps(done)
            assert run('/bin/ubus','call','adzero','exec','{}').returncode != 0
            report={'runtime':'pinned OpenWrt 24.10.8 rpcd/ubusd/ucode in isolated chroot',
                    'checks':15,'nested_rpcd_call':'passed','typed_input_and_no_log_leak':'passed','detached_source_job':'passed','router':'not_touched'}
            (ROOT/'artifacts/runtime/rpc-result.json').write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps(report,indent=2))
        finally:
            for process in reversed(procs):
                process.terminate()
                process.wait(timeout=5)


if __name__ == '__main__': main()
