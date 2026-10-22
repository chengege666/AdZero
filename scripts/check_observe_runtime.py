#!/usr/bin/env python3
"""Real OpenWrt tcpdump, ucode and dnsmasq in a private network/mount namespace.

Run as root under Linux/WSL. Only disposable chroot files and namespace-local
addresses/processes are used. Dependencies are downloaded before isolation;
the isolated capture test has no real router, household traffic or WAN access.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_observe import dns
from check_openwrt_runtime import SHA256

EXTRAS={
    'libpcap1_1.10.5-r2_x86_64.ipk':'51c6bc3cc46fa1cd964a3fe7c2cdb283aced09c888bd6e61cc8d0ff0070649a2',
    'tcpdump-mini_4.99.5-r1_x86_64.ipk':'fa88889694215128b26ad3d94e8b05b8c052475b90d45d2b20394668a94d0fb2',
    'ucode-mod-uloop_2025.07.18~3f64c808-r1_x86_64.ipk':'1c0c07ecd7e820b9a70347284d3c26d4d7760e2224f48e5eadee50a6e0030095',
}


def prepare_extras(download):
    files=[]
    for filename,digest in EXTRAS.items():
        cache=ROOT/'artifacts/runtime/observe-extras'/filename
        if not cache.exists():
            if not download:raise RuntimeError('Prepare observer dependencies before network isolation')
            with urllib.request.urlopen('https://downloads.openwrt.org/releases/24.10.8/packages/x86_64/base/'+filename,timeout=30) as response:data=response.read()
            if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Observer dependency SHA-256 mismatch')
            cache.parent.mkdir(parents=True,exist_ok=True);cache.write_bytes(data)
        if hashlib.sha256(cache.read_bytes()).hexdigest()!=digest:raise ValueError('Cached observer dependency SHA-256 mismatch')
        files.append(cache)
    return files


def main():
    if os.geteuid()!=0:raise SystemExit('Run as root in Linux/WSL')
    if '--inside' not in sys.argv:
        prepare_extras(download=True)
        return subprocess.call(['unshare','--net','--mount','--propagation','private',sys.executable,__file__,'--inside'])
    subprocess.run(['ip','link','set','lo','up'],check=True)
    for ip in ('192.168.2.1','192.168.2.10'):subprocess.run(['ip','addr','add',ip+'/32','dev','lo'],check=True)
    archive=ROOT/'artifacts/runtime/openwrt-24.10.8-x86-64-rootfs.tar.gz'
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==SHA256
    with tempfile.TemporaryDirectory(prefix='adzero-observe-') as temp:
        base=Path(temp)
        with tarfile.open(archive) as tar:tar.extractall(base,filter='fully_trusted')
        for cache in prepare_extras(download=False):
            with tarfile.open(cache) as outer:
                member=next(m for m in outer.getmembers() if m.name.endswith('data.tar.gz'))
                with tarfile.open(fileobj=io.BytesIO(outer.extractfile(member).read())) as tar:tar.extractall(base,filter='fully_trusted')
        for relative in ('etc/adzero','tmp','proc','sys','dev','usr/libexec/adzero','var/run/adblock-fast'):(base/relative).mkdir(parents=True,exist_ok=True)
        subprocess.run(['mount','--bind','/proc',str(base/'proc')],check=True)
        subprocess.run(['mount','--bind','/sys',str(base/'sys')],check=True)
        os.mknod(base/'dev/null',0o666|0o20000,os.makedev(1,3))
        os.mknod(base/'dev/urandom',0o666|0o20000,os.makedev(1,9))
        for f in (ROOT/'luci-app-adzero/root/usr/libexec/adzero').iterdir():
            if f.is_file():shutil.copyfile(f,base/'usr/libexec/adzero'/f.name);(base/'usr/libexec/adzero'/f.name).chmod(0o755)
        (base/'etc/config/adzero').write_text("config adzero 'main'\n option enabled '1'\n")
        (base/'etc/config/adblock-fast').write_text("config adblock-fast 'config'\n option enabled '1'\n option dns 'dnsmasq.servers'\n")
        (base/'etc/adzero/managed').write_text('1\n')
        (base/'var/run/adblock-fast/dnsmasq.servers').write_text('server=/doubleclick.net/\n')
        # Real adapter serialization puts potentially large provider strings
        # before the top-level stage. The original 1 KiB prefix missed it.
        journal={'schema':1,'plugin':'nailink','files':[{'path':'/etc/daed/adzero-geosite.dat','kind':'owned','before':None,'after':'A'*2097152}],'flags':[],'stage':'configured_unverified'}
        journal_path=base/'etc/adzero/adapter.json'
        def replace_journal(stage):
            journal['stage']=stage;temp=journal_path.with_suffix('.next')
            temp.write_text(json.dumps(journal));temp.chmod(0o600);temp.replace(journal_path)
        replace_journal('configured_unverified')
        stage_offset=journal_path.read_text().index('"stage"');assert stage_offset>1024
        # Only netifd discovery is a fixture. Capture, packets, DNS responses,
        # timers, UCI, process lifecycle and state files are native binaries.
        (base/'bin/ubus').write_text('#!/bin/sh\necho \'{"l3_device":"lo"}\'\n');(base/'bin/ubus').chmod(0o755)
        log=(ROOT/'artifacts/runtime/observe-runtime.log').open('w+')
        procs=[]
        def run(*args):return subprocess.run(['chroot',temp,*args],capture_output=True,text=True,timeout=8)
        def query(name,ident=42,tcp=False):
            with socket.socket(socket.AF_INET,socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as sock:
                sock.settimeout(2);sock.bind(('192.168.2.10',0));raw=dns(name,ident=ident)
                if tcp:
                    sock.connect(('192.168.2.1',53));sock.sendall(struct.pack('!H',len(raw))+raw)
                    def exact(n):
                        data=b''
                        while len(data)<n:
                            part=sock.recv(n-len(data));assert part;data+=part
                        return data
                    return exact(struct.unpack('!H',exact(2))[0])
                sock.sendto(raw,('192.168.2.1',53));return sock.recvfrom(4096)[0]
        def status():
            p=run('/usr/libexec/adzero/observe','status');assert p.returncode==0,p.stderr
            return json.loads(p.stdout)
        def wait_for(check):
            value=None
            for _ in range(80):
                value=status()
                if check(value):return value
                if len(procs)>1 and procs[-1].poll() is not None:break
                time.sleep(.1)
            log.flush()
            state_file=base/'tmp/adzero-observe/status.json'
            raw=state_file.read_text() if state_file.exists() else 'missing'
            raise AssertionError((value,raw,[p.poll() for p in procs],(ROOT/'artifacts/runtime/observe-runtime.log').read_text()))
        try:
            procs.append(subprocess.Popen(['chroot',temp,'/usr/sbin/dnsmasq','--no-daemon','--conf-file=/dev/null','--no-resolv','--no-hosts','--bind-interfaces','--listen-address=192.168.2.1','--user=root','--server=/doubleclick.net/','--server=/adzero.invalid/','--host-record=www.baidu.com,1.2.3.4','--host-record=allowed-by-path.example,1.2.3.4'],stdout=log,stderr=log))
            time.sleep(.2)
            procs.append(subprocess.Popen(['chroot',temp,'/usr/libexec/adzero/observe','run'],env={**os.environ,'ADZERO_OBSERVER_DEBUG':'1'},stdout=log,stderr=log))
            value=wait_for(lambda s:s.get('available') and s.get('active'))
            time.sleep(.3)
            query('doubleclick.net');query('www.baidu.com',43)
            value=wait_for(lambda s:s.get('blocked')==1 and s.get('queries')==2)
            assert value['answered']==2,value
            query('doubleclick.net',51,tcp=True);query('www.baidu.com',52,tcp=True)
            value=wait_for(lambda s:s.get('blocked')==2 and s.get('queries')==4)
            result=run('/usr/libexec/adzero/observe','start-test');test=json.loads(result.stdout);assert test['ok'],test
            # The timer imports the fresh challenge before its marker arrives.
            wait_for(lambda s:s.get('verification',{}).get('state')=='waiting')
            names=[line.split()[-1] for line in test['commands'].splitlines()]
            for i,name in enumerate(names):query(name,100+i)
            value=wait_for(lambda s:s.get('verification',{}).get('state')=='passed')
            assert value['queries']==4 and value['blocked']==2,value
            assert value['verification']['client']=='192.168.2.10',value
            # Rule/config changes invalidate the receipt, without network restart.
            (base/'etc/config/adzero').write_text("config adzero 'main'\n option enabled '1'\n option routing_enabled '1'\n")
            wait_for(lambda s:s.get('verification',{}).get('state')=='idle')
            procs[-1].terminate();procs[-1].wait(timeout=4)
            procs.append(subprocess.Popen(['chroot',temp,'/usr/libexec/adzero/observe','run'],stdout=log,stderr=log))
            value=wait_for(lambda s:s.get('available') and s.get('active'))
            assert value['queries']==4 and value['blocked']==2,value
            replace_journal('recovery_required')
            wait_for(lambda s:s.get('available') and not s.get('active'))
            assert status()['reason']=='adapter_pending'
            query('doubleclick.net',150)
            time.sleep(1.1);value=status();assert value['queries']==4 and value['blocked']==2,value
            replace_journal('configured_unverified')
            wait_for(lambda s:s.get('available') and s.get('active'))
            query('doubleclick.net',151);query('www.baidu.com',152)
            value=wait_for(lambda s:s.get('queries')==6 and s.get('blocked')==3)
            # Background switch metadata arrives through the same small snapshot.
            journal.update(plugin='passwall',count=246925,split={'mode':'proxy'})
            replace_journal('configured_unverified')
            value=wait_for(lambda s:s.get('connection',{}).get('plugin')=='passwall')
            assert value['connection']['domains']==246925 and value['connection']['confirmed'],value
            assert value['queries']==6 and value['blocked']==3 and value['current']['matched']==0,value
            assert json.loads(run('/usr/libexec/adzero/observe','recent-start').stdout)['ok']
            wait_for(lambda s:s.get('recent',{}).get('enabled'))
            query('doubleclick.net',201);query('www.baidu.com',202)
            value=wait_for(lambda s:s.get('queries')==8 and s.get('blocked')==4)
            assert value['recent']['items'][0]['domain']=='doubleclick.net' and len(value['recent']['items'])==1,value
            assert json.loads(run('/usr/libexec/adzero/observe','recent-stop').stdout)['ok']
            assert status()['recent']['items']==[],'stop must hide even a snapshot awaiting its next timer'
            wait_for(lambda s:not s.get('recent',{}).get('enabled'))
            query('doubleclick.net',203)
            value=wait_for(lambda s:s.get('queries')==9 and s.get('blocked')==5)
            assert value['recent']['items']==[],value
            assert json.loads(run('/usr/libexec/adzero/observe','recent-start').stdout)['ok']
            wait_for(lambda s:s.get('recent',{}).get('enabled'))
            query('doubleclick.net',204)
            wait_for(lambda s:s.get('queries')==10 and s.get('blocked')==6 and len(s.get('recent',{}).get('items',[]))==1)
            assert json.loads(run('/usr/libexec/adzero/observe','recent-start').stdout)['ok']
            assert status()['recent']['items']==[],'a new recording must not expose the previous session while waiting for its first tick'
            value=wait_for(lambda s:s.get('recent',{}).get('enabled'))
            assert 'recent_token' not in value,'private recording token must not leave snapshot API'
            control=base/'tmp/adzero-observe/recent.json';data=json.loads(control.read_text());data['deadline']=0
            control.write_text(json.dumps(data));control.chmod(0o600)
            assert not status()['recent']['items'],'expired request cannot expose old domains'
            # A matching rule with a real positive answer diagnoses bypass; it
            # is never silently added to the blocked count, including fake-IP.
            (base/'var/run/adblock-fast/dnsmasq.servers').write_text('server=/doubleclick.net/\nserver=/allowed-by-path.example/\n')
            wait_for(lambda s:s.get('current',{}).get('queries')==0)
            query('allowed-by-path.example',205)
            value=wait_for(lambda s:s.get('queries')==11 and s.get('current',{}).get('matched_positive')==1)
            assert value['blocked']==6 and value['current']['blocked']==0,value
            report={'native':'OpenWrt 24.10.8 tcpdump-mini/ucode/uloop/dnsmasq','queries':11,'blocked':6,'udp_tcp':'passed','terminal_challenge':'passed','large_journal_bytes':journal_path.stat().st_size,'stage_offset':stage_offset,'recovery_then_resume_counts':'passed','test_queries_excluded':True,'config_invalidates_receipt':True,'same_boot_restart_preserves_counts':True,'unconfirmed_configuration_not_counted':True,'live_passwall_metadata':'passed','recent_opt_in_stop_expiry':'passed','positive_rule_hit_not_counted_as_block':'passed','scope':'isolated namespace; netifd interface discovery fixture; not a router/LAN certificate'}
            print(json.dumps(report,indent=2));(ROOT/'artifacts/runtime/observe-result.json').write_text(json.dumps(report,indent=2)+'\n')
        finally:
            for p in reversed(procs):p.terminate()
            for p in reversed(procs):
                try:p.wait(timeout=4)
                except subprocess.TimeoutExpired:p.kill();p.wait()
            log.close()
            subprocess.run(['umount',str(base/'sys')],check=True)
            subprocess.run(['umount',str(base/'proc')],check=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
