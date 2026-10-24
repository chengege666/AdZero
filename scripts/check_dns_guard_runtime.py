#!/usr/bin/env python3
"""Production nft rules tested in a disposable Linux network namespace only."""
import hashlib,json,os,shlex,socket,subprocess,sys,tarfile,tempfile,threading,time
from pathlib import Path
from build_sdk import source_hash
from check_openwrt_runtime import SHA256
ROOT=Path(__file__).resolve().parents[1]
def run(*args,**kw):return subprocess.run(args,check=True,capture_output=True,text=True,**kw).stdout
def peer():
    code='''import socket,threading,time
def serve(port,tcp,v6):
 s=socket.socket(socket.AF_INET6 if v6 else socket.AF_INET,socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM);s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
 if v6:s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
 s.bind(('::' if v6 else '0.0.0.0',port))
 if tcp:s.listen()
 while True:
  if tcp:
   c,_=s.accept()
   try:c.recv(100);c.sendall(b'OK')
   except OSError:pass
   c.close()
  else:q,a=s.recvfrom(100);s.sendto(b'OK',a)
for p in [53,443,853]:
 for t in [False,True]:
  for v6 in [False,True]:threading.Thread(target=serve,args=(p,t,v6),daemon=True).start()
while True:time.sleep(1)
'''
    return subprocess.Popen(['unshare','--net',sys.executable,'-u','-c',code],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
def main():
    if os.geteuid()!=0:raise SystemExit('Linux root required for isolated namespace only')
    if '--inside' not in sys.argv:
        subprocess.run(['unshare','--net',sys.executable,str(Path(__file__).resolve()),'--inside'],check=True);return
    run('ip','link','set','lo','up');runtime=ROOT/'.sdk/runtime-24.10.8';archive=ROOT/'artifacts/runtime/openwrt-24.10.8-x86-64-rootfs.tar.gz'
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==SHA256
    with tarfile.open(archive) as tar:
        member=next(m for m in tar.getmembers() if m.name.removeprefix('./')=='usr/sbin/nft');binary=runtime/'nft';binary.write_bytes(tar.extractfile(member).read());binary.chmod(0o755)
    nft=[str(runtime/'libc.so'),'--library-path',str(runtime),str(binary)]
    cmd=shlex.split(os.environ.get('ADZERO_UCODE','')) or [str(runtime/'libc.so'),'--library-path',str(runtime),str(runtime/'ucode'),'-L',str(runtime)]
    before=source_hash(ROOT/'luci-app-adzero');other=peer();checks=[];sockets=[]
    try:
        time.sleep(.1);run('ip','link','add','br-lan','type','veth','peer','name','peer0');run('ip','link','set','peer0','netns',str(other.pid))
        run('ip','addr','add','192.0.2.1/24','dev','br-lan');run('ip','link','set','br-lan','up')
        run('ip','-6','addr','add','fd00::1/64','dev','br-lan','nodad')
        ns=['nsenter','-t',str(other.pid),'-n'];run(*ns,'ip','link','set','lo','up');run(*ns,'ip','link','set','peer0','up')
        for address in ['192.0.2.107/24','192.0.2.108/32']:run(*ns,'ip','addr','add',address,'dev','peer0')
        run(*ns,'ip','-6','addr','add','fd00::107/64','dev','peer0','nodad')
        run(*ns,'ip','route','add','default','via','192.0.2.1')
        def local_server(port,v6=False):
            s=socket.socket(socket.AF_INET6 if v6 else socket.AF_INET,socket.SOCK_DGRAM)
            if v6:s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
            s.bind(('::' if v6 else '0.0.0.0',port));sockets.append(s)
            def serve():
                while True:
                    try:q,a=s.recvfrom(100);s.sendto(b'MANAGED' if port==53 else b'OLD',a)
                    except OSError:return
            threading.Thread(target=serve,daemon=True).start()
        local_server(53);local_server(53,True);local_server(11400)
        probe='''import socket,sys,json
s=socket.socket(socket.AF_INET6 if ':' in sys.argv[1] else socket.AF_INET,socket.SOCK_STREAM if sys.argv[3]=='tcp' else socket.SOCK_DGRAM);s.settimeout(.35)
try:
 s.connect((sys.argv[1],int(sys.argv[2])));s.send(b'query');r=s.recv(100);print(json.dumps({'ok':True,'reply':r.decode()}))
except OSError:print('{"ok":false}')
finally:s.close()
'''
        def ask(address,port=53,tcp=False,lan=False):return json.loads(run(*(ns if lan else []),sys.executable,'-c',probe,address,str(port),'tcp' if tcp else 'udp'))
        def expect(label,actual,ok,reply=None):
            assert actual['ok']==ok,(label,actual)
            if reply:assert actual['reply']==reply,(label,actual)
            checks.append(label)
        p={'domestic':{'servers':['192.0.2.107'],'active':'192.0.2.107'},'foreign':{'servers':['192.0.2.108'],'active':'192.0.2.108'},'strict':True}
        installed=False
        def install(ready,bootstrap):
            nonlocal installed
            payload=dict(lan=dict(device='br-lan',address='192.0.2.1',mask=24),profile=p,ready=ready,bootstrap=bootstrap)
            script=subprocess.run(cmd+[str(ROOT/'scripts/dns_guard_transform.uc')],input=json.dumps(payload),text=True,capture_output=True,check=True).stdout
            if installed:script='delete table inet adzero_dns_guard\n'+script
            with tempfile.NamedTemporaryFile(mode='w') as f:
                f.write(script);f.flush();run(*nft,'-c','-f',f.name);run(*nft,'-f',f.name)
            installed=True
        expect('baseline public DNS fixture',ask('192.0.2.107'),True)
        expect('baseline IPv6 DNS fixture',ask('fd00::107'),True)
        expect('baseline IPv6 LAN listener',ask('fd00::1',lan=True),True,'MANAGED')
        install(False,False)
        for tcp in [False,True]:
            expect('held public DNS '+str(tcp),ask('192.0.2.107',tcp=tcp),False)
            expect('HTTPS remains available '+str(tcp),ask('192.0.2.107',443,tcp),True)
        expect('held LAN DNS',ask('192.0.2.1',lan=True),False)
        install(True,True)
        for tcp in [False,True]:
            expect('bootstrap exception '+str(tcp),ask('192.0.2.107',tcp=tcp),True)
            expect('foreign direct DNS blocked '+str(tcp),ask('192.0.2.108',tcp=tcp),False)
            expect('direct 853 blocked '+str(tcp),ask('192.0.2.107',853,tcp),False)
            expect('public IPv6 DNS blocked '+str(tcp),ask('fd00::107',tcp=tcp),False)
            expect('IPv6 HTTPS available '+str(tcp),ask('fd00::107',443,tcp),True)
        expect('LAN external DNS redirected',ask('198.51.100.53',lan=True),True,'MANAGED')
        expect('IPv6 LAN DNS blocked',ask('fd00::1',lan=True),False)
        expect('LAN 853 blocked',ask('192.0.2.1',853,lan=True),False)
        install(False,False);expect('handoff returns to held DNS',ask('192.0.2.1',lan=True),False)
        assert source_hash(ROOT/'luci-app-adzero')==before
        report=dict(checks=checks,source_sha256=before,nft='official OpenWrt 24.10.8',scope='private Linux veth/network namespaces; no router touched')
        target=ROOT/'artifacts/runtime/dns-guard-result.json';target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    finally:
        for s in sockets:s.close()
        other.terminate();other.communicate(timeout=4)
if __name__=='__main__':main()
