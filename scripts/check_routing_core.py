#!/usr/bin/env python3
"""Production routing compiler + real Mihomo in a private Linux network namespace.

Requires WSL/Linux root for unshare only. No host or router routes are changed.
Every upstream and target is a deterministic local fixture inside that namespace.
"""
import gzip
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shlex
import socket
import socketserver
import struct
import subprocess
import sys
import tempfile
import threading
import time

from check_dns_core import ROOT, SHA256, VERSION, question, recv_exact
from build_sdk import source_hash


def transform(kind, operation, *args):
    runtime=ROOT/'.sdk/runtime-24.10.8'
    cmd=[str(runtime/'libc.so'),'--library-path',str(runtime),str(runtime/'ucode'),'-L',str(runtime),str(ROOT/'scripts'/f'{kind}_transform.uc')]
    p=subprocess.run(cmd,input=json.dumps({'operation':operation,'arguments':args}),text=True,capture_output=True)
    if p.returncode:raise RuntimeError(p.stderr)
    return json.loads(p.stdout)


def freeport():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


def main():
    if os.name!='posix' or os.geteuid()!=0:
        raise SystemExit('Run under WSL/Linux root; all addresses live in a disposable network namespace')
    if '--inside' not in sys.argv:
        subprocess.run(['unshare','--net',sys.executable,str(Path(__file__).resolve()),'--inside'],check=True)
        return
    subprocess.run(['ip','link','set','lo','up'],check=True)
    for ip in ('223.5.5.5','119.29.29.29','223.5.5.42'):
        subprocess.run(['ip','addr','add',ip+'/32','dev','lo'],check=True)
    subprocess.run(['ip','-6','addr','add','2400:3200::42/128','dev','lo','nodad'],check=True)
    archive=ROOT/f'artifacts/upstream/mihomo-linux-amd64-compatible-{VERSION}.gz'
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==SHA256
    binary=Path.home()/f'.cache/adzero/mihomo/{VERSION}/mihomo'
    binary.parent.mkdir(parents=True,exist_ok=True)
    binary.write_bytes(gzip.decompress(archive.read_bytes()));binary.chmod(0o755)
    assert binary.read_bytes()==gzip.decompress(archive.read_bytes())
    dns_records=[];proxy_records=[];servers=[];threads=[];checks=[];fail_proxy={'dns':False}

    def dns_reply(packet,group,endpoint=None):
        pos=12;labels=[]
        while packet[pos]:
            size=packet[pos];pos+=1;labels.append(packet[pos:pos+size].decode());pos+=size
        name='.'.join(labels);kind=struct.unpack('!H',packet[pos+1:pos+3])[0]
        dns_records.append({'group':group,'name':name,'type':kind,'endpoint':endpoint})
        if name.startswith('race.'):time.sleep(.45 if endpoint in ('223.5.5.5','1.1.1.1') else .02)
        addr=('2400:3200::42' if group=='domestic' else '2606:4700:4700::42') if kind==28 else ('223.5.5.42' if group=='domestic' else '8.8.8.42')
        ip=socket.inet_pton(socket.AF_INET6 if kind==28 else socket.AF_INET,addr)
        return packet[:2]+struct.pack('!HHHHH',0x8180,1,1,0,0)+packet[12:pos+5]+b'\xc0\x0c'+struct.pack('!HHIH',kind,1,60,len(ip))+ip

    class UDPDNS(socketserver.BaseRequestHandler):
        def handle(self):
            packet,sock=self.request;sock.sendto(dns_reply(packet,'domestic',self.server.server_address[0]),self.client_address)

    class TCPDNS(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(4)
            try:
                while True:
                    packet=recv_exact(self.request,struct.unpack('!H',recv_exact(self.request,2))[0])
                    answer=dns_reply(packet,'domestic',self.server.server_address[0]);self.request.sendall(struct.pack('!H',len(answer))+answer)
            except OSError:pass

    class SOCKS(socketserver.BaseRequestHandler):
        def handle(self):
            sock=self.request;sock.settimeout(5)
            try:
                version,n=recv_exact(sock,2);assert version==5;recv_exact(sock,n);sock.sendall(b'\x05\x00')
                version,command,_,kind=recv_exact(sock,4);assert (version,command)==(5,1)
                host=socket.inet_ntop(socket.AF_INET,recv_exact(sock,4)) if kind==1 else socket.inet_ntop(socket.AF_INET6,recv_exact(sock,16)) if kind==4 else recv_exact(sock,recv_exact(sock,1)[0]).decode()
                port=struct.unpack('!H',recv_exact(sock,2))[0];proxy_records.append({'host':host,'port':port})
                if port==53 and fail_proxy['dns']:return
                sock.sendall(b'\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x01')
                if host in ('1.1.1.1','8.8.8.8') and port==53:
                    while True:
                        packet=recv_exact(sock,struct.unpack('!H',recv_exact(sock,2))[0]);answer=dns_reply(packet,'foreign-through-proxy',host);sock.sendall(struct.pack('!H',len(answer))+answer)
                else:
                    data=b''
                    while b'\r\n\r\n' not in data:data+=recv_exact(sock,1)
                    sock.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nPROXY')
            except (OSError,AssertionError):pass

    class DirectHTTP(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Length','6');self.end_headers();self.wfile.write(b'DIRECT')
        def log_message(self,*args):pass

    class TCPServer(socketserver.ThreadingTCPServer):
        allow_reuse_address=True;daemon_threads=True
    class UDPServer(socketserver.ThreadingUDPServer):
        allow_reuse_address=True;daemon_threads=True
    class HTTP6(ThreadingHTTPServer):address_family=socket.AF_INET6

    def start(server):
        servers.append(server);t=threading.Thread(target=server.serve_forever,daemon=True);t.start();threads.append(t);return server.server_address[1]

    for address in ('223.5.5.5','119.29.29.29'):
        start(UDPServer((address,53),UDPDNS));start(TCPServer((address,53),TCPDNS))
    socks_port=start(TCPServer(('127.0.0.1',0),SOCKS))
    http_port=start(ThreadingHTTPServer(('223.5.5.42',0),DirectHTTP));start(HTTP6(('2400:3200::42',http_port),DirectHTTP))

    def query(port,name,kind,tcp):
        packet=question(name,kind)
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as sock:
            sock.settimeout(3)
            if tcp:
                sock.connect(('127.0.0.1',port));sock.sendall(struct.pack('!H',len(packet))+packet)
                answer=recv_exact(sock,struct.unpack('!H',recv_exact(sock,2))[0])
            else:sock.sendto(packet,('127.0.0.1',port));answer=sock.recv(4096)
        return answer[3]&15,struct.unpack('!H',answer[6:8])[0]

    def connection_path(port,host):
        c=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
        try:
            c.request('GET',f'http://{host}:{http_port}/');r=c.getresponse();body=r.read().decode();assert r.status==200;return body
        finally:c.close()

    try:
        profiles=[('default',None),('custom',{'domestic':{'servers':['119.29.29.29'],'active':'119.29.29.29'},'foreign':{'servers':['8.8.8.8'],'active':'8.8.8.8'}})]
        profiles.append(('parallel-strict',{'strict':True,'domestic':{'servers':['223.5.5.5','119.29.29.29'],'active':'223.5.5.5','mode':'parallel'},'foreign':{'servers':['1.1.1.1','8.8.8.8'],'active':'1.1.1.1','mode':'parallel'}}))
        for label,settings in profiles:
            for mode in ('redir-host','fake-ip'):
                with tempfile.TemporaryDirectory(prefix='adzero-routing-core-') as tmp:
                    home=Path(tmp);dns_port,mixed_port=freeport(),freeport()
                    ads=home/'ads.txt';ads.write_text('+.ads.example\n+.ads.cn.example\n')
                    cn=home/'cn.txt';cn.write_text('+.cn.example\n+.sub.ads.example\n')
                    ips=home/'ips.txt';ips.write_text('223.5.5.0/24\n2400:3200::/32\n')
                    target='🚀 节点选择 🇭🇰'
                    config={'mode':'global','log-level':'error','mixed-port':mixed_port,'bind-address':'127.0.0.1','dns':{'enable':True,'listen':f'127.0.0.1:{dns_port}','ipv6':True,'enhanced-mode':mode,'fake-ip-range':'198.18.0.1/16','nameserver':['223.5.5.5'],'fake-ip-filter':['+.real.foreign.example']},'proxies':[{'name':'test-node','type':'socks5','server':'127.0.0.1','port':socks_port}],'proxy-groups':[{'name':target,'type':'select','proxies':['test-node']}],'rules':['DOMAIN,override.cn.example,'+target,'MATCH,'+target]}
                    config=transform('adapter','mihomo',config,str(ads),False)
                    config=transform('routing','mihomo',config,str(cn),str(ips),settings)['config']
                    # Match production ucode's UTF-8 output. Python's default
                    # surrogate-pair escapes are not accepted by YAML readers.
                    path=home/'config.json';path.write_text(json.dumps(config,ensure_ascii=False))
                    p=subprocess.run([str(binary),'-t','-d',tmp,'-f',str(path)],text=True,capture_output=True)
                    assert p.returncode==0,p.stdout+p.stderr
                    with (home/'core.log').open('w+') as log:
                        process=subprocess.Popen([str(binary),'-d',tmp,'-f',str(path)],stdout=log,stderr=log)
                        try:
                            for attempt in range(40):
                                if process.poll() is not None:raise RuntimeError((home/'core.log').read_text())
                                try:query(dns_port,'ready.cn.example',1,False);break
                                except OSError:time.sleep(.1)
                            for tcp in (False,True):
                                for kind in (1,28):
                                    for name,rcode in [('www.cn.example',0),('test.real.foreign.example',0),('sub.ads.example',3),('deep.sub.ads.example',3),('ads.cn.example',3)]:
                                        result=query(dns_port,name,kind,tcp)
                                        assert result[0]==rcode and (rcode!=0 or result[1]>0),(mode,name,kind,tcp,result,(home/'core.log').read_text())
                                        checks.append({'profile':label,'mode':mode,'transport':'tcp' if tcp else 'udp','type':kind,'name':name,'rcode':result[0]})
                            for host,expected in [('www.cn.example','DIRECT'),('www.foreign.example','PROXY'),('override.cn.example','PROXY'),('223.5.5.42','DIRECT'),('8.8.8.42','PROXY'),('[2400:3200::42]','DIRECT'),('[2606:4700:4700::42]','PROXY')]:
                                actual=connection_path(mixed_port,host);assert actual==expected,(mode,host,actual,proxy_records)
                                checks.append({'profile':label,'mode':mode,'target':host,'actual_connection_path':actual})
                            if label=='parallel-strict':
                                for name,expected in [('race.cn.example',{'223.5.5.5','119.29.29.29'}),('race.real.foreign.example',{'1.1.1.1','8.8.8.8'})]:
                                    start=time.monotonic();result=query(dns_port,name,1,False);elapsed=time.monotonic()-start
                                    assert result[0]==0 and elapsed<.35,(name,elapsed,result)
                                    actual={r['endpoint'] for r in dns_records if r['name']==name};assert expected<=actual,(name,actual)
                                    checks.append({'profile':label,'mode':mode,'parallel':name,'seconds':elapsed,'upstreams':sorted(actual)})
                                fail_proxy['dns']=True
                                try:
                                    try:failed=query(dns_port,'failed.real.foreign.example',1,False)
                                    except OSError:failed=(2,0)
                                    assert failed[0]!=0,failed
                                    assert not any(r['group']=='domestic' and r['name']=='failed.real.foreign.example' for r in dns_records)
                                    checks.append({'profile':label,'mode':mode,'proxy_unavailable':'no direct DNS fallback'})
                                finally:fail_proxy['dns']=False
                        finally:process.terminate();process.wait(timeout=5)
        assert any(r['group']=='domestic' and r['name']=='www.cn.example' for r in dns_records)
        assert any(r['group']=='foreign-through-proxy' and r['name']=='test.real.foreign.example' for r in dns_records)
        assert not any('ads.example' in r['name'] or 'ads.cn.example' in r['name'] for r in dns_records),dns_records
        assert not any(r['host'] in ('223.5.5.5','119.29.29.29','223.5.5.42','2400:3200::42') for r in proxy_records),proxy_records
        assert all(any(r['host']==address and r['port']==53 for r in proxy_records) for address in ('1.1.1.1','8.8.8.8'))
        report={'status':'passed','source_sha256':source_hash(ROOT/'luci-app-adzero'),'core':VERSION,'asset_sha256':SHA256,'scope':'production compiler and real core; isolated namespace, local DNS/SOCKS/HTTP fixtures; no router, LAN, TUN or eBPF validation','checks':checks,'dns_records':dns_records,'proxy_records':proxy_records}
        (ROOT/'artifacts/runtime/routing-mihomo-result.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'status':report['status'],'checks':len(checks),'scope':report['scope']},indent=2))
    finally:
        for server in servers:server.shutdown();server.server_close()
        for thread in threads:thread.join(2)


if __name__=='__main__':main()
