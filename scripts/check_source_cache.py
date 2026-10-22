#!/usr/bin/env python3
"""Actual OpenWrt shell/ucode curl handoff using pinned upstream download().

Disposable rootfs only. The transport is a local curl fixture: no DNS service,
proxy reload, real HTTPS request or router timing is claimed by this check.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from build_sdk import source_hash
from check_openwrt_runtime import ROOT, SHA256

UPSTREAM='19727b189472f380b9791b1fc37c4acdec60eea06650f7d845fea8fafbd49315'
URL='https://raw.githubusercontent.com/openwrt/packages/65493e273e4b9cd7014236b69fd6fdc617b88436/net/adblock-fast/files/lib/adblock-fast/adblock-fast.uc'

def main():
    if os.geteuid()!=0: raise SystemExit('Run inside WSL/Linux as root for a disposable chroot')
    source=ROOT/'artifacts/upstream/adblock-fast-1.2.4-r4.uc'
    raw=source.read_bytes() if source.exists() else urllib.request.urlopen(URL,timeout=30).read()
    assert hashlib.sha256(raw).hexdigest()==UPSTREAM
    text=raw.decode();download=text[text.index('function download(url, dest) {'):text.index('function service_restart(name) {')]
    archive=ROOT/'artifacts/runtime/openwrt-24.10.8-x86-64-rootfs.tar.gz'
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==SHA256
    checks=[]
    with tempfile.TemporaryDirectory(prefix='adzero-cache-handoff-') as temp:
        base=Path(temp)
        with tarfile.open(archive) as tar: tar.extractall(base,filter='fully_trusted')
        for name in ('tmp','dev','etc/adzero','proc/self','proc/sys/kernel/random'): (base/name).mkdir(parents=True,exist_ok=True)
        os.mknod(base/'dev/null',0o666|0o20000,os.makedev(1,3))
        (base/'proc/sys/kernel/random/uuid').write_text('12345678-1234-1234-1234-123456789012\n')
        shutil.copytree(ROOT/'luci-app-adzero/root/usr/libexec/adzero',base/'usr/libexec/adzero',dirs_exist_ok=True)
        (base/'usr/libexec/adzero/cache-curl/curl').chmod(0o755)
        (base/'etc/config/adblock-fast').write_text("config adblock-fast 'config'\n option enabled '0'\n option dns 'dnsmasq.servers'\n option download_allow_insecure '0'\n")
        curl=base/'usr/bin/curl'
        if curl.is_symlink(): curl.unlink()
        curl.write_text('''#!/bin/sh
echo fetch >> /tmp/fetches
[ ! -f /tmp/timeout ] || exit 28
while [ "$#" -gt 0 ]; do
 case "$1" in -o|--output) out=$2; shift;; esac
 shift
done
[ -n "$out" ] || exit 2
cat /tmp/body > "$out"
''');curl.chmod(0o755)
        (base/'tmp/body').write_text('one-ad.example\ntwo-ad.example\n')
        # The exact upstream function constructs and executes the command.
        # Only downloader discovery is fixed; no upstream formatting/lifecycle
        # functions or DNS restarts are executed by this transport check.
        probe="""'use strict';
function shell_quote(s){return "'"+replace(s,/'/g,"'\\\\''")+"'";}
let env={get_downloader:()=>({kind:'curl',flag:'-o',command:'curl -f --silent --max-filesize 25000000 --retry 3 --connect-timeout 10 --speed-limit 1 --speed-time 20'})};
"""+download+"\nlet ok=download(ARGV[0],ARGV[1]);print(sprintf('%J',{ok,timeout:env._last_dl_timeout}));exit(ok?0:1);\n"
        (base/'tmp/native-download.uc').write_text(probe)
        env={**os.environ,'PATH':'/usr/libexec/adzero/cache-curl:/usr/sbin:/usr/bin:/sbin:/bin','ADZERO_SOURCE_REPLAY':'1'}
        def run(*args,ok=True):
            p=subprocess.run(['/usr/sbin/chroot',str(base),*args],env=env,text=True,capture_output=True,timeout=15)
            assert (p.returncode==0)==ok,p.stdout+p.stderr
            return p
        def sources(*args): return run('/usr/bin/ucode','-S','/usr/libexec/adzero/sources.uc','--',*args)
        def count(): return len((base/'tmp/fetches').read_text().splitlines())
        def fetch(address,ok=True):
            target=base/'tmp/adblock-fast_tmp.12345678';target.write_text('');target.chmod(0o600)
            return run('/usr/bin/ucode','-S','/tmp/native-download.uc',address,'/tmp/'+target.name,ok=ok)
        address='https://lists.example/one?token=private-marker'
        sources('begin','add','','Fixture',address,'domains');sources('finish')
        assert count()==1
        fetch(address);assert count()==1 and (base/'tmp/adblock-fast_tmp.12345678').read_bytes()==(base/'tmp/body').read_bytes()
        checks.append('precheck download reused through real shell PATH wrapper and pinned upstream download function')
        fetch(address);assert count()==1
        checks.append('repeated backend list download uses the same checked bytes without transport')
        sources('begin','refresh');sources('finish');assert count()==2
        fetch(address);assert count()==2
        checks.append('explicit refresh fetches once; unchanged bytes are replayed without a second fetch')
        (base/'tmp/body').write_text('new-ad.example\n')
        sources('begin','refresh');sources('finish');fetch(address)
        assert count()==3 and (base/'tmp/adblock-fast_tmp.12345678').read_text()=='new-ad.example\n'
        checks.append('changed refresh content reaches backend; stale snapshot is not replayed')
        next((base/'tmp/adzero-source-cache').glob('*.body')).write_text('corrupt.example\n')
        fetch(address);assert count()==4,count()
        fetch(address);assert count()==4,count()
        checks.append('corrupt snapshot falls back to real downloader and successful backend fetch reseeds cache')
        with (base/'etc/config/adblock-fast').open('a') as f: f.write("\nconfig file_url 'cold'\n option enabled '1'\n option url 'https://lists.example/cold'\n")
        fetch('https://lists.example/cold');assert count()==5
        fetch('https://lists.example/cold');assert count()==5
        checks.append('previously existing uncached source downloads once, then reuses snapshot')
        run('/sbin/uci','set','adblock-fast.config.curl_additional_param=--header X-Custom:1')
        run('/sbin/uci','commit','adblock-fast')
        fetch(address);fetch(address);assert count()==7
        checks.append('custom curl configuration retains real downloader behavior on every call')
        (base/'tmp/timeout').write_text('1')
        p=fetch(address,ok=False);assert json.loads(p.stdout)=={'ok':False,'timeout':True}
        checks.append('real curl exit 28 propagates to pinned upstream timeout handling')
    report={'source_sha256':source_hash(ROOT/'luci-app-adzero'),'upstream_sha256':UPSTREAM,'upstream_url':URL,'checks':checks,
            'runtime':'actual OpenWrt 24.10.8 shell/ucode/UCI and shipped curl wrapper in disposable rootfs',
            'transport':'local curl fixture, no network','backend_lifecycle_and_proxy_reload':'not_run','router':'not_touched'}
    (ROOT/'artifacts/runtime/source-cache-handoff-result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
