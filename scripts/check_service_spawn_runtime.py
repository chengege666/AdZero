"""Check daemon signal inheritance in a disposable, prepared OpenWrt root.

Uses the production adapter in a private mount/network namespace. Service
restart bodies are fixtures; the interpreter, ash, timeout and signal mask
are native. Never runs on or contacts a router.
"""
from pathlib import Path
import json, os, shutil, subprocess, sys, tempfile
from build_sdk import source_hash

SOURCE=Path(__file__).resolve().parents[1]

def main():
    base=Path(os.environ['ADZERO_PASSWALL_FIXTURE']).resolve()
    native=base/'root'
    assert native.is_dir() and native!=Path('/') and os.geteuid()==0
    if '--inside' not in sys.argv:
        return subprocess.call(['unshare','--net','--mount','--propagation','private',sys.executable,__file__,*sys.argv[1:],'--inside'])
    subprocess.run(['mount','-t','proc','proc',str(native/'proc')],check=True)
    try:
        with tempfile.TemporaryDirectory(prefix='service-spawn-',dir=native/'tmp') as tmp:
            dest=Path(tmp); relative='/tmp/'+dest.name
            def write(name,text):
                path=dest/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
                return path
            shutil.copytree(SOURCE/'luci-app-adzero/root/usr/libexec/adzero',dest/'adapter')
            baseline='--baseline-v0172' in sys.argv
            if baseline:
                (dest/'adapter/adapter.uc').write_bytes(subprocess.check_output(['git','-c','safe.directory='+str(SOURCE),'show','v0.17.2:luci-app-adzero/root/usr/libexec/adzero/adapter.uc'],cwd=SOURCE))
            write('etc/config/adzero',"config adzero 'main'\n option enabled '1'\n option routing_enabled '1'\n")
            write('etc/config/adblock-fast',"config adblock-fast 'config'\n option dns 'dnsmasq.servers'\n")
            write('etc/config/dhcp',"config dnsmasq 'main'\n list server '8.8.8.8'\n")
            write('var/run/adblock-fast/dnsmasq.servers','server=/ads.example/\n')
            write('inventory.json','{"plugins":[]}')
            write('etc/init.d/dnsmasq','#!/bin/sh\ngrep "^SigBlk:" /proc/self/status >> '+relative+'/masks\n')
            env=['ADZERO_ADAPTER_ROOT='+relative,'ADZERO_ADAPTER_INVENTORY='+relative+'/inventory.json',
                 'ADZERO_SERVICE_TIMEOUT=/usr/libexec/timeout-coreutils']
            for action in ['apply','remove']:
                result=subprocess.run(['chroot',str(native),'/usr/bin/env',*env,'/usr/bin/ucode','-S',relative+'/adapter/adapter.uc','--',action],text=True,capture_output=True,timeout=15)
                assert result.returncode==0,(action,result.stdout,result.stderr)
            masks=[int(line.split()[1],16) for line in (dest/'masks').read_text().splitlines()]
            assert len(masks)==2 and all(bool(value&0x10000)==baseline for value in masks),masks
            report={'source_sha256':source_hash(SOURCE/'luci-app-adzero'),'native':'OpenWrt 25.12.5 ucode/ash/coreutils-timeout',
                    'apply_remove_sigchld_unblocked':not baseline,'baseline_blocked_reproduced':baseline,'masks':masks,'scope':'production adapter; DNS init body is a signal-reading fixture, not router network acceptance'}
            if baseline:
                report['adapter_baseline']='v0.17.2'
                report['harness_source_sha256']=report.pop('source_sha256')
            output=SOURCE/('artifacts/runtime/service-spawn-baseline.json' if baseline else 'artifacts/runtime/service-spawn-result.json');output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps(report,indent=2))
    finally:
        subprocess.run(['umount',str(native/'proc')],check=True)
    return 0

if __name__=='__main__':raise SystemExit(main())
