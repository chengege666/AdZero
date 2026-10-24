#!/usr/bin/env python3
"""Pinned OpenClash quick-start/hook stages, rc.common and real Mihomo DNS.

Runs in a private OpenWrt chroot/network namespace. Only configuration-generation
stages are extracted from native init; firewall, subscription and nodes are not
tested. Ruby closure intentionally excludes ruby-json (not an OpenClash dependency).
"""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request

from build_sdk import source_hash
from prepare_dns_socket import install as install_socket, prepare as prepare_socket
from check_openwrt_runtime import ROOT, URL, SHA256
from check_dns_core import VERSION, SHA256 as CORE_SHA256, URL as CORE_URL, query

REF='e553e82e01c697aefbe1555261a503f425e00ccd'


def fetch(path,url,digest=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():path.write_bytes(urllib.request.urlopen(url,timeout=60).read())
    raw=path.read_bytes()
    if digest and hashlib.sha256(raw).hexdigest()!=digest:raise AssertionError(path)
    return raw


def main():
    cache=ROOT/'artifacts/runtime/openclash-extras'
    if '--inside' not in sys.argv:
        if os.geteuid()!=0:raise SystemExit('Run in Linux/WSL as root')
        prepare_socket(ROOT,None)
        fetch(ROOT/'artifacts/runtime/openwrt-24.10.8-x86-64-rootfs.tar.gz',URL,SHA256)
        raw=fetch(cache/'native-init',f'https://raw.githubusercontent.com/vernesong/OpenClash/{REF}/luci-app-openclash/root/etc/init.d/openclash')
        assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()=='7bc7e7568c74c197668ddf6372c7013de2baf152'
        fetch(cache/'mihomo.gz',CORE_URL,CORE_SHA256)
        packages={}
        for feed in ('base','packages'):
            prefix=f'https://downloads.openwrt.org/releases/24.10.8/packages/x86_64/{feed}/'
            index=gzip.decompress(fetch(cache/(feed+'-Packages.gz'),prefix+'Packages.gz')).decode()
            for block in index.split('\n\n'):
                info=dict(line.split(': ',1) for line in block.splitlines() if ': ' in line)
                if 'Package' in info:packages[info['Package']]={**info,'prefix':prefix}
        needed={}
        def dependency(name):
            if name in needed or name in ('libc','libgcc','libpthread','librt'):return
            row=packages[name];needed[name]=row
            for item in row.get('Depends','').split(','):
                dep=item.strip().split(' ')[0]
                if dep:dependency(dep)
        for name in ('ruby','ruby-yaml','coreutils-timeout'):dependency(name)
        assert 'ruby-json' not in needed
        for row in needed.values():fetch(cache/row['Filename'],row['prefix']+row['Filename'],row['SHA256sum'])
        (cache/'packages.json').write_text(json.dumps(list(needed.values())))
        return subprocess.call(['unshare','--net','--mount','--propagation','private',sys.executable,__file__,'--inside'])

    subprocess.run(['ip','link','set','lo','up'],check=True)
    native=(cache/'native-init').read_text()
    assert hashlib.sha1(b'blob '+str(len(native.encode())).encode()+b'\0'+native.encode()).hexdigest()=='7bc7e7568c74c197668ddf6372c7013de2baf152'
    functions=[]
    for name in ('check_run_quick','write_run_quick'):
        block=re.search(r'^'+name+r'\(\)\n\{.*?^\}[^\n]*',native,re.M|re.S)
        assert block;functions.append(block.group())
    invocation=re.search(r'^[ \t]*if \[ -f "/etc/openclash/custom/openclash_custom_overwrite.sh" \]; then\n[ \t]*chmod[^\n]+\n[ \t]*/etc/openclash/custom/openclash_custom_overwrite.sh "\$TMP_CONFIG_FILE"',native,re.M)
    assert invocation
    with tempfile.TemporaryDirectory(prefix='adzero-openclash-native-') as tmp:
        base=Path(tmp)
        with tarfile.open(ROOT/'artifacts/runtime/openwrt-24.10.8-x86-64-rootfs.tar.gz') as tar:tar.extractall(base,filter='fully_trusted')
        install_socket(ROOT,base)
        packages=json.loads((cache/'packages.json').read_text())
        for row in packages:
            raw=fetch(cache/row['Filename'],row['prefix']+row['Filename'],row['SHA256sum'])
            with tarfile.open(fileobj=io.BytesIO(raw)) as outer:
                member=next(m for m in outer if m.name.endswith('data.tar.gz'))
                with tarfile.open(fileobj=io.BytesIO(outer.extractfile(member).read())) as tar:tar.extractall(base,filter='fully_trusted')
        for name in ('etc/adzero','etc/openclash/config','etc/openclash/custom','etc/openclash/core','usr/share/openclash/ui','etc/ssl','tmp/untrusted-ui','var/run/adblock-fast','dev','proc/self','proc/sys/kernel/random'):(base/name).mkdir(parents=True,exist_ok=True)
        # Supply only the process-owner and nonce metadata used by private
        # recovery storage; do not mount the host's /proc into this fixture.
        (base/'proc/sys/kernel/random/uuid').write_text('11111111-1111-4111-8111-111111111111\n')
        os.mknod(base/'dev/null',0o666|0o20000,os.makedev(1,3));os.mknod(base/'dev/urandom',0o666|0o20000,os.makedev(1,9))
        shutil.copytree(ROOT/'luci-app-adzero/root/usr/libexec/adzero',base/'usr/libexec/adzero',dirs_exist_ok=True)
        for path in (base/'usr/libexec/adzero').iterdir():path.chmod(0o755)
        core=base/'etc/openclash/core/clash_meta';core.write_bytes(gzip.decompress(fetch(cache/'mihomo.gz',CORE_URL,CORE_SHA256)));core.chmod(0o755)
        (base/'etc/config/openclash').write_text("config openclash 'config'\n option enable '1'\n option config_path '/etc/openclash/config/test profile.yaml'\n")
        (base/'etc/config/adblock-fast').write_text("config adblock-fast 'config'\n option dns 'dnsmasq.servers'\n")
        (base/'tmp/inventory.json').write_text(json.dumps({'plugins':[{'id':'openclash','installed':True,'enabled':True,'runtime':'running'}]}))
        child={k:v for k,v in os.environ.items() if not k.startswith('ADZERO_') and k not in ('RUBYLIB','RUBYOPT','LD_LIBRARY_PATH')}
        child.update(PATH='/usr/sbin:/usr/bin:/sbin:/bin',ADZERO_ADAPTER_INVENTORY='/tmp/inventory.json')
        # A broad inherited value must never widen AdZero's validation child.
        child['SAFE_PATHS']='/'
        safe_paths='SAFE_PATHS=/usr/share/openclash:/etc/ssl'
        assert 'procd_set_param env '+safe_paths in native
        def run(*args,success=True):
            result=subprocess.run(['chroot',tmp,*args],env=child,text=True,capture_output=True,timeout=12)
            assert (result.returncode==0)==success,result.stdout+result.stderr
            return result
        assert run('/usr/bin/ruby','-e',"begin; require 'json'; exit 2; rescue LoadError; exit 0; end").returncode==0
        (base/'etc/openclash/custom/openclash_custom_overwrite.sh').write_text('#!/bin/sh\n# Retain user custom script\nexit 0\n')
        # Native functions and the exact native temporary-file hook invocation.
        # Other init actions are deliberately replaced with a local stage runner.
        stage='''#!/bin/sh /etc/rc.common
QUICK_START=true
QUICK_START_CHECK=false
RAW_CONFIG_FILE='/etc/openclash/config/test profile.yaml'
CONFIG_FILE='/etc/openclash/test profile.yaml'
TMP_CONFIG_FILE='/tmp/test profile.yaml'
LOG_TIP() { :; }
'''+ '\n'.join(functions)+'''
start() {
 echo restart >>/tmp/restarts
 check_run_quick
 if ! $QUICK_START; then
  cp "$RAW_CONFIG_FILE" "$TMP_CONFIG_FILE"
'''+invocation.group()+'''
  fi
  mv "$TMP_CONFIG_FILE" "$CONFIG_FILE"
 fi
 write_run_quick
}
restart() { start; }
'''
        (base/'etc/init.d/openclash').write_text(stage)
        rules=base/'var/run/adblock-fast/dnsmasq.servers'
        rules.write_text('server=/ads.example/\nserver=/track.example/\n')
        rows=[]
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as upstream:
            upstream.bind(('127.0.0.1',0));upstream.settimeout(.2);stop=threading.Event()
            def respond():
                while not stop.is_set():
                    try:packet,peer=upstream.recvfrom(4096)
                    except socket.timeout:continue
                    kind=struct.unpack('!H',packet[-4:-2])[0]
                    address=socket.inet_pton(socket.AF_INET6 if kind==28 else socket.AF_INET,'2001:db8::9' if kind==28 else '192.0.2.9')
                    reply=packet[:2]+struct.pack('!HHHHH',0x8180,1,1,0,0)+packet[12:]+b'\xc0\x0c'+struct.pack('!HHIH',kind,1,0,len(address))+address
                    upstream.sendto(reply,peer)
            thread=threading.Thread(target=respond,daemon=True);thread.start()
            try:
                for mode in ('redir-host','fake-ip'):
                    source=base/'etc/openclash/config/test profile.yaml'
                    config={'mode':'rule','log-level':'error','external-ui':'/usr/share/openclash/ui','dns':{'enable':True,'ipv6':True,'listen':'127.0.0.1:12053','enhanced-mode':mode,'nameserver':[f'udp://127.0.0.1:{upstream.getsockname()[1]}']},'rules':['MATCH,DIRECT']}
                    # Exercise the actual strategy labels commonly seen in
                    # subscriptions, rather than only ASCII fixture names.
                    target='🚀 节点选择 🇭🇰'
                    config['proxy-groups']=[{'name':target,'type':'select','proxies':['DIRECT']}]
                    config['rules']=['MATCH,'+target]
                    config['custom-text']='literal \\U0001F680 / 中文 / 🚀'
                    source.write_text(json.dumps(config,ensure_ascii=False))
                    # Same untouched native config: missing env reproduces the
                    # user's external-ui rejection; native env passes.
                    rejected=run('/usr/bin/env','SAFE_PATHS=','/etc/openclash/core/clash_meta','-t','-d','/etc/openclash','-f','/etc/openclash/config/test profile.yaml',success=False)
                    assert 'SAFE_PATHS' in rejected.stdout+rejected.stderr
                    run('/usr/bin/env',safe_paths,'/etc/openclash/core/clash_meta','-t','-d','/etc/openclash','-f','/etc/openclash/config/test profile.yaml')
                    for phase in ('enabled','changed','disabled'):
                        if phase=='changed':rules.write_text('server=/ads.example/\nserver=/new.example/\n')
                        # Seed native quick-start cache before each operation.
                        (base/'tmp/openclash.change').write_text('')
                        started=time.monotonic();run('/usr/libexec/adzero/adapter','remove' if phase=='disabled' else 'apply');elapsed=time.monotonic()-started
                        process=subprocess.Popen(['chroot',tmp,'/usr/bin/env',safe_paths,'/etc/openclash/core/clash_meta','-d','/etc/openclash','-f','/etc/openclash/test profile.yaml'],env=child,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                        try:
                            for attempt in range(40):
                                try:query(12053,'www.example',1);break
                                except OSError:time.sleep(.05)
                            for tcp in (False,True):
                                for kind in (1,28):
                                    result=query(12053,'ads.example',kind,tcp)
                                    assert result==(3,0) if phase!='disabled' else result[0]==0,(phase,mode,kind,tcp,result)
                                    normal=query(12053,'www.example',kind,tcp);assert normal[0]==0
                                    added=query(12053,'new.example',kind,tcp)
                                    removed=query(12053,'track.example',kind,tcp)
                                    assert (added==(3,0)) if phase=='changed' else added[0]==0,(phase,added)
                                    assert (removed==(3,0)) if phase=='enabled' else removed[0]==0,(phase,removed)
                                    rows.append({'mode':mode,'phase':phase,'protocol':'tcp' if tcp else 'udp','qtype':kind,'blocked':phase!='disabled','added_and_removed_rule_queries':True,'seconds':round(elapsed,3)})
                        finally:process.terminate();process.wait(timeout=5)
                    rules.write_text('server=/ads.example/\nserver=/track.example/\n')
                # An outside path would pass with the inherited SAFE_PATHS=/.
                # The actual adapter must override it, reject and restore.
                config['external-ui']='/tmp/untrusted-ui'
                source.write_text(json.dumps(config,ensure_ascii=False))
                rejected=run('/usr/libexec/adzero/adapter','apply',success=False)
                assert 'OpenClash core rejected the adapted configuration' in rejected.stderr
                assert not (base/'etc/adzero/adapter.json').exists()
                assert (base/'etc/openclash/test profile.yaml').read_text()==source.read_text()
            finally:stop.set();thread.join(timeout=2)
        assert not (base/'etc/adzero/adapter.json').exists()
        assert (base/'etc/openclash/custom/openclash_custom_overwrite.sh').read_text()=='#!/bin/sh\n# Retain user custom script\nexit 0\n'
        output={'source_sha256':source_hash(ROOT/'luci-app-adzero'),'native_init_commit':REF,'native_init_blob':'7bc7e7568c74c197668ddf6372c7013de2baf152','core':VERSION,'checks':len(rows),'native_safe_paths':safe_paths,'missing_safe_paths_reproduced':True,'inherited_safe_paths_overridden':True,'outside_path_rejected_and_restored':True,'unicode_strategy_labels':True,'ruby_json_installed':False,'cases':rows,'scope':'Native rc.common + extracted OpenClash quick-start/hook stages + real Mihomo DNS; no firewall or router test'}
        (ROOT/'artifacts/runtime/openclash-result.json').write_text(json.dumps(output,indent=2)+'\n')
        print(json.dumps(output,indent=2))


if __name__=='__main__':sys.exit(main())
