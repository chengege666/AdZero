#!/usr/bin/env python3
"""Real OpenWrt updater/parser in a private chroot, controlled HTTP responses.

Installer --check is a harmless fixture; no real install, router or network.
"""
import hashlib,json,os,shutil,subprocess,sys,tarfile,tempfile
from pathlib import Path
from check_openwrt_runtime import ROOT,SHA256

def main():
    if os.geteuid()!=0:raise SystemExit('Run in Linux/WSL as root')
    if '--inside' not in sys.argv:
        return subprocess.call(['unshare','--net','--mount','--propagation','private',sys.executable,__file__,'--inside'])
    archive=ROOT/'artifacts/runtime/openwrt-24.10.8-x86-64-rootfs.tar.gz'
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==SHA256
    rows=[]
    with tempfile.TemporaryDirectory(prefix='adzero-update-native-') as directory:
        base=Path(directory)
        with tarfile.open(archive) as tar:tar.extractall(base,filter='fully_trusted')
        for name in ('tmp','proc','dev','usr/libexec/adzero','usr/share/adzero'):(base/name).mkdir(parents=True,exist_ok=True)
        os.mknod(base/'dev/null',0o600|0o20000,os.makedev(1,3))
        for name in ('update','update-check.uc'):
            shutil.copyfile(ROOT/'luci-app-adzero/root/usr/libexec/adzero'/name,base/'usr/libexec/adzero'/name)
        (base/'usr/share/adzero/version').write_text('0.22.0\n')
        protected=base/'etc/config/adzero';protected.write_text("config adzero 'main'\n option enabled '0'\n")
        before=protected.read_bytes()
        installer='#!/bin/sh\nprintf "%s\\n" "$*" >> /tmp/check-actions\ncase " $* " in *" --check "*) exit 0;; *) touch /tmp/unexpected-upgrade; exit 99;; esac\n'
        (base/'tmp/installer').write_text(installer)
        digest=hashlib.sha256(installer.encode()).hexdigest()
        entry='#!/bin/sh\nINSTALL_URL=https://github.com/slobys/AdZero/releases/download/v0.23.1/install.sh\nINSTALL_SHA256='+digest+'\ntouch /tmp/entry-executed\n'
        (base/'tmp/entry').write_text(entry)
        (base/'tmp/api').write_text(json.dumps([{'tag_name':'v0.23.1','draft':False,'prerelease':False,'assets':[{'name':'install.sh','digest':'sha256:'+digest}]}]))
        curl=base/'tmp/http-fixture'
        curl.write_text('''#!/bin/sh
dest=;url=
while [ "$#" -gt 0 ]; do
 case "$1" in
 --output) dest=$2;shift 2;;
 --proto|--proto-redir|--connect-timeout|--max-time|--max-filesize|--write-out) shift 2;;
 --*) shift;;
 *) url=$1;shift;;
 esac
done
scenario=$(cat /tmp/scenario)
case "$url" in
 'https://api.github.com/repos/slobys/AdZero/releases?per_page=20')
 case "$scenario" in
 api) cp /tmp/api "$dest";printf 200;;
 invalid_api) printf '{}' > "$dest";printf 200;;
 offline) printf 000;exit 6;;
 *) case "$scenario" in 429|502) printf '%s' "$scenario";; *) printf 403;; esac;exit 22;;
 esac;;
 https://raw.githubusercontent.com/slobys/AdZero/main/scripts/install-auto.sh)
 [ "$scenario" != offline ] || { printf 000;exit 6; }
 if [ "$scenario" = bad_entry ];then sed s/github.com/example.com/ /tmp/entry > "$dest";else cp /tmp/entry "$dest";fi;printf 200;;
 https://github.com/slobys/AdZero/releases/download/v0.23.1/install.sh)
 cp /tmp/installer "$dest";[ "$scenario" != bad_hash ] || printf '\\n# modified\\n' >> "$dest";printf 200;;
 *) exit 97;;
esac
''');curl.chmod(0o700)
        env={k:v for k,v in os.environ.items() if not k.startswith('ADZERO_')}
        env.update(ADZERO_UPDATE_CURL='/tmp/http-fixture')
        subprocess.run(['mount','-t','proc','-o','nosuid,nodev,noexec','proc',str(base/'proc')],check=True)
        try:
            for scenario in ('api','403','429','502','invalid_api','bad_entry','bad_hash','offline'):
                (base/'tmp/scenario').write_text(scenario)
                result=subprocess.run(['chroot',directory,'/bin/sh','/usr/libexec/adzero/update','check'],env=env,text=True,capture_output=True,timeout=15)
                assert result.returncode==0,(scenario,result.stdout,result.stderr)
                reply=json.loads(result.stdout)
                approved=base/'tmp/adzero-update/approved'
                if scenario in ('bad_entry','offline'):assert reply['ok'] is False and not approved.exists(),reply
                elif scenario=='bad_hash':assert reply['ok'] and not reply['compatible'] and not approved.exists(),reply
                else:
                    assert reply['ok'] and reply['available'] and reply['compatible'] and approved.exists(),reply
                    assert reply['metadata_source']==('github_api' if scenario=='api' else 'official_entry'),reply
                assert protected.read_bytes()==before
                assert not (base/'tmp/entry-executed').exists() and not (base/'tmp/unexpected-upgrade').exists()
                assert not (base/'tmp/adzero-update/lock').exists()
                rows.append({'scenario':scenario,**reply})
        finally:subprocess.run(['umount',str(base/'proc')],check=True)
    report={'runtime':'real OpenWrt BusyBox/ucode/parser; controlled HTTP and installer --check','checks':len(rows),'cases':rows,'device_acceptance':'not_run','network_or_install':'not_run'}
    (ROOT/'artifacts/runtime/update-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
