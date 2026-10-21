#!/usr/bin/env python3
"""Independent DNS design experiment. No production/router configuration writes.

Run with WSL/Linux root for a disposable chroot only. The checked binaries are
downloaded from official OpenWrt feeds; no package is installed on the host.
"""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from check_openwrt_runtime import SHA256
from check_dns_core import question,recv_exact

BASE='https://downloads.openwrt.org/releases/24.10.8/packages/x86_64/'
SMART_SHA='b7d07896aff635899207a7fdfd5f76440b3262dde467db42dc3281af3dd35074'

def fetch(url):
    with urllib.request.urlopen(url,timeout=30) as r:
        assert r.geturl().startswith('https://')
        return r.read(30_000_000)

def index(feed):
    raw=gzip.decompress(fetch(BASE+feed+'/Packages.gz')).decode()
    return {v['Package']:v for row in raw.split('\n\n') if (v:=dict(line.split(': ',1) for line in row.splitlines() if ': ' in line and not line.startswith(' '))).get('Package')}

def main():
    assert os.name=='posix' and os.geteuid()==0,'isolated OpenWrt chroot requires WSL root'
    archive=ROOT/'artifacts/runtime/openwrt-24.10.8-x86-64-rootfs.tar.gz'
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==SHA256
    package=index('packages')['smartdns']
    assert package['SHA256sum']==SMART_SHA
    openssl=index('base')['libopenssl3']
    assets=[]
    ports=[]
    def freeport():
        with socket.socket() as s:
            s.bind(('127.0.0.1',0));return s.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='adzero-split-design-') as tmp:
        base=Path(tmp)
        with tarfile.open(archive) as t: t.extractall(base,filter='fully_trusted')
        (base/'dev').mkdir(exist_ok=True)
        if not (base/'dev/null').exists(): os.mknod(base/'dev/null',0o666|0o20000,os.makedev(1,3))
        if not (base/'dev/urandom').exists(): os.mknod(base/'dev/urandom',0o666|0o20000,os.makedev(1,9))
        (base/'tmp').mkdir(exist_ok=True)
        for feed,meta in [('packages',package),('base',openssl)]:
            raw=fetch(BASE+feed+'/'+meta['Filename'])
            assert hashlib.sha256(raw).hexdigest()==meta['SHA256sum']
            assets.append({'url':BASE+feed+'/'+meta['Filename'],'sha256':meta['SHA256sum'],'version':meta['Version']})
            with tarfile.open(fileobj=io.BytesIO(raw)) as outer:
                m=next(m for m in outer if m.name.lstrip('./')=='data.tar.gz')
                with tarfile.open(fileobj=io.BytesIO(outer.extractfile(m).read())) as inner:
                    inner.extractall(base,filter='fully_trusted')
        counts={'cn':[],'foreign':[]};respond_enabled={'cn':True,'foreign':True};stop=threading.Event();sockets=[];threads=[]
        def responder(sock,group):
            while not stop.is_set():
                try:packet,peer=sock.recvfrom(4096)
                except socket.timeout:continue
                name=[];i=12
                while packet[i]:
                    n=packet[i];i+=1;name.append(packet[i:i+n].decode());i+=n
                name='.'.join(name);kind=struct.unpack('!H',packet[i+1:i+3])[0]
                counts[group].append((name,kind))
                if not respond_enabled[group]:continue
                ipv6=kind==28
                # SmartDNS filters reserved documentation IPs. These literal
                # replies are never connected to; speed checks are disabled.
                addr=('2400:3200::1' if group=='cn' else '2606:4700:4700::1111') if ipv6 else ('223.5.5.5' if group=='cn' else '1.1.1.1')
                ip=socket.inet_pton(socket.AF_INET6 if ipv6 else socket.AF_INET,addr)
                answer=packet[:2]+struct.pack('!HHHHH',0x8180,1,1,0,0)+packet[12:i+5]+b'\xc0\x0c'+struct.pack('!HHIH',kind,1,60,len(ip))+ip
                sock.sendto(answer,peer)
        for group in counts:
            sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.bind(('127.0.0.1',0));sock.settimeout(.2)
            sockets.append(sock);ports.append(sock.getsockname()[1])
            thread=threading.Thread(target=responder,args=(sock,group),daemon=True);thread.start();threads.append(thread)
        smartport,frontport=freeport(),freeport()
        (base/'tmp/cn.txt').write_text('cn.example\n')
        (base/'tmp/smartdns.conf').write_text(f'''bind 127.0.0.1:{smartport}
bind-tcp 127.0.0.1:{smartport}
cache-size 128
cache-persist no
prefetch-domain no
serve-expired no
dualstack-ip-selection no
speed-check-mode none
log-level error
log-console yes
server 127.0.0.1:{ports[1]} -group foreign
server 127.0.0.1:{ports[0]} -group domestic -exclude-default-group
domain-set -name cn -file /tmp/cn.txt
nameserver /domain-set:cn/domestic
nameserver /remote.cn.example/foreign
''')
        front='''no-daemon
no-resolv
no-hosts
bind-interfaces
listen-address=127.0.0.1
port={port}
server=127.0.0.1#{smart}
server=/ads.example/
server=/tracker.cn.example/
address=/local.lan/192.168.1.2
cache-size=0
'''.format(port=frontport,smart=smartport)
        (base/'tmp/dnsmasq.conf').write_text(front)
        def query(name,kind=1,tcp=False):
            packet=question(name,kind)
            with socket.socket(socket.AF_INET,socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as s:
                s.settimeout(2)
                if tcp:
                    s.connect(('127.0.0.1',frontport));s.sendall(struct.pack('!H',len(packet))+packet)
                    answer=recv_exact(s,struct.unpack('!H',recv_exact(s,2))[0])
                else:s.sendto(packet,('127.0.0.1',frontport));answer=s.recv(4096)
            return answer
        def addresses(packet):
            def skip_name(pos):
                while packet[pos]:
                    if packet[pos]&0xc0==0xc0:return pos+2
                    pos+=packet[pos]+1
                return pos+1
            pos=12
            for _ in range(struct.unpack('!H',packet[4:6])[0]):pos=skip_name(pos)+4
            result=[]
            for _ in range(struct.unpack('!H',packet[6:8])[0]):
                pos=skip_name(pos);kind,cls,ttl,size=struct.unpack('!HHIH',packet[pos:pos+10]);pos+=10
                if kind in (1,28):result.append(socket.inet_ntop(socket.AF_INET if kind==1 else socket.AF_INET6,packet[pos:pos+size]))
                pos+=size
            return result
        procs=[];checks=[]
        with (base/'tmp/services.log').open('w+') as log:
            try:
                procs.append(subprocess.Popen(['chroot',tmp,'/usr/sbin/smartdns','-f','-c','/tmp/smartdns.conf','-p','/tmp/smartdns.pid'],stdout=log,stderr=log))
                procs.append(subprocess.Popen(['chroot',tmp,'/usr/sbin/dnsmasq','-C','/tmp/dnsmasq.conf'],stdout=log,stderr=log))
                for _ in range(30):
                    if any(p.poll() is not None for p in procs):raise RuntimeError((base/'tmp/services.log').read_text())
                    try:query('ready.cn.example');break
                    except OSError:time.sleep(.1)
                for tcp in (False,True):
                    for kind in (1,28):
                        transport='tcp' if tcp else 'udp'
                        for name,group in [(f'www.{transport}.cn.example','cn'),(f'www.{transport}.foreign.example','foreign'),(f'{transport}.remote.cn.example','foreign')]:
                            expected=('2400:3200::1' if group=='cn' else '2606:4700:4700::1111') if kind==28 else ('223.5.5.5' if group=='cn' else '1.1.1.1')
                            answer=query(name,kind,tcp)
                            assert answer[3]&15==0 and expected in addresses(answer),(name,kind,answer.hex(),addresses(answer),counts,(base/'tmp/services.log').read_text())
                            assert (name,kind) in counts[group] and (name,kind) not in counts['foreign' if group=='cn' else 'cn']
                            checks.append({'name':name,'type':kind,'transport':'tcp' if tcp else 'udp','upstream':group})
                        for name in ('sub.ads.example','tracker.cn.example','sub.tracker.cn.example'):
                            answer=query(name,kind,tcp);assert answer[3]&15==3
                            assert all(not any(n==name for n,k in values) for values in counts.values())
                            checks.append({'name':name,'type':kind,'transport':'tcp' if tcp else 'udp','blocked_before_upstream':True})
                counts_before=len(counts['cn']);query('www.tcp.cn.example');assert len(counts['cn'])==counts_before
                checks.append({'cache_reuse':True,'group':'cn'})
                query('local.lan');assert all(not any(n=='local.lan' for n,k in v) for v in counts.values())
                checks.append({'local_name_preserved':True})
                respond_enabled['foreign']=False
                cn_before=len(counts['cn'])
                try:
                    failed=query('failure.foreign.example')
                    assert failed[3]&15!=0 or not addresses(failed)
                    outcome='no_successful_answer'
                except OSError:outcome='timeout'
                assert len(counts['cn'])==cn_before and ('failure.foreign.example',1) in counts['foreign']
                checks.append({'foreign_failure_no_domestic_fallback':True,'client_outcome':outcome})
                assert '223.5.5.5' in addresses(query('available.cn.example'))
                checks.append({'domestic_group_works_while_foreign_fails':True})
                stop.set()
                report={'status':'passed','scope':'design experiment, literal test config; not production integration, proxy, TLS, router or LAN validation','assets':assets,'checks':checks,'request_counts':{k:len(v) for k,v in counts.items()}}
                (ROOT/'artifacts/runtime/smart-dns-design-result.json').write_text(json.dumps(report,indent=2)+'\n')
                print(json.dumps(report,indent=2))
            finally:
                for p in reversed(procs):
                    if p.poll() is None:p.terminate()
                    p.wait(timeout=5)
                stop.set()
                for t in threads:t.join(1)
                for s in sockets:s.close()

if __name__=='__main__':main()
