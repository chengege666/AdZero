"""Real kernel NAT + packaged OpenWrt dnsmasq/conntrack + production monitor.

Requires a disposable prepared OpenWrt 25.12.5 x86 rootfs, conntrack 1.4.8,
dnsmasq-full 2.93, ucode/fs/uci/uloop. Run as root with ADZERO_DNS_FIXTURE set
to its parent directory. Only anonymous net/mount namespaces are changed.
The native-plugin inventory and LAN ubus responses are explicit fixtures.
"""
from pathlib import Path
import hashlib,json,os,shutil,socket,socketserver,struct,subprocess,sys,threading,time

BASE=Path(os.environ['ADZERO_DNS_FIXTURE']).resolve()
ROOT=BASE/'root'
SOURCE=Path(__file__).resolve().parents[1]/'luci-app-adzero/root/usr/libexec/adzero'
SERVER='192.0.2.1';CLIENT='192.0.2.107'
def question(name):
    return struct.pack('!HHHHHH',42,256,1,0,0,0)+b''.join(bytes([len(s)])+s.encode() for s in name.split('.'))+b'\0'+struct.pack('!HH',1,1)
def worker():
    socks={};tcp_socks=[];print('ready',flush=True)
    for raw in sys.stdin:
        try:
            data=json.loads(raw);port=data['port'];target=data.get('target',53)
            if data.get('protocol')=='tcp':
                s=socket.create_connection((SERVER,target),timeout=2)
                try:
                    q=question('chatgpt.example');s.sendall(struct.pack('!H',len(q))+q)
                    length=struct.unpack('!H',s.recv(2))[0];reply=b''
                    while len(reply)<length:reply+=s.recv(length-len(reply))
                finally:
                    if data.get('keep'):tcp_socks.append(s)
                    else:s.close()
                print(json.dumps({'address':socket.inet_ntoa(reply[-4:])}),flush=True);continue
            if port not in socks:
                s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.bind((CLIENT,port));s.settimeout(2);socks[port]=s
            s=socks[port];s.sendto(question(data.get('name','chatgpt.example')),(SERVER,target));reply=s.recv(4096)
            print(json.dumps({'address':socket.inet_ntoa(reply[-4:])}),flush=True)
        except Exception as e:print(json.dumps({'error':str(e)}),flush=True)
def main():
    if '--worker' in sys.argv:return worker()
    if '--inside' not in sys.argv:
        return subprocess.call(['unshare','--net','--mount','--propagation','private',sys.executable,__file__,'--inside'])
    assert os.geteuid()==0 and ROOT.is_dir() and ROOT!=Path('/'), 'disposable fixture required'
    manifest=json.loads((BASE/'fixture-manifest.json').read_text())
    assert manifest['rootfs_sha256']=='2dae4250b1b742062ed5787adcdc9dd6d26c7f69f94ced46548eb512d5957e8a'
    assert Path(manifest['root']).resolve()==ROOT and not ROOT.is_symlink()
    def host(*args):return subprocess.run(args,check=True,text=True,capture_output=True).stdout
    def native(*args,success=True):
        r=subprocess.run(['chroot',str(ROOT),*args],text=True,capture_output=True,timeout=5)
        if success:assert r.returncode==0,repr((args,r.returncode,r.stdout,r.stderr))
        return r
    def nft(text):
        r=subprocess.run(['chroot',str(ROOT),'/usr/sbin/nft','-f','-'],input=text,text=True,capture_output=True,timeout=5)
        assert r.returncode==0,r.stderr
    host('ip','link','set','lo','up')
    client=subprocess.Popen(['unshare','--net',sys.executable,__file__,'--worker'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
    servers=[];dns=None;monitor=None
    try:
        # /proc is mounted only in this private mount namespace. The actual
        # dnsmasq PID, socket FDs and kernel start time are checked by production.
        (ROOT/'proc').mkdir(exist_ok=True)
        host('mount','-t','proc','proc',str(ROOT/'proc'))
        def write(path,text,mode=None):
            target=ROOT/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
            if mode is not None:target.chmod(mode)
        for name in ('dns-handoff','dns-handoff.uc','dns-handoff-lib.uc'):
            target=ROOT/'usr/libexec/adzero'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(SOURCE/name,target);target.chmod(0o755 if name=='dns-handoff' else 0o644)
        write('etc/config/adzero',"config adzero 'main'\n option enabled '1'\n")
        write('etc/config/adblock-fast',"config adblock-fast 'config'\n option enabled '1'\n")
        inactive_config="config global\n option enabled '0'\n option dns_redirect '1'\nconfig global\n option enabled '1'\n option dns_redirect '1'\n"
        active_config="config global\n option enabled '1'\n option dns_redirect '1'\nconfig global\n"
        write('etc/config/passwall',inactive_config)
        write('etc/adzero/managed','1')
        write('usr/sbin/ubus',"#!/bin/sh\nprintf '%s\\n' '"+json.dumps({'l3_device':'az-server','ipv4-address':[{'address':SERVER,'mask':24}]})+"'\n",0o755)
        write('usr/libexec/adzero/probe',"#!/bin/sh\nprintf '%s\\n' '{\"dns\":{\"active_proxies\":[\"passwall\"],\"uncertain_proxies\":[]}}'\n",0o755)
        write('tmp/etc/passwall/acl/default/dnsmasq.conf','port=11400\nuser=dnsmasq\ngroup=dnsmasq\nno-resolv\nbind-dynamic\naddress=/chatgpt.example/198.51.100.42\n')
        binary=ROOT/'tmp/etc/passwall/bin/dnsmasq_default';binary.parent.mkdir(parents=True,exist_ok=True)
        if not binary.is_symlink():binary.symlink_to('/usr/sbin/dnsmasq')
        # Normal foreground mode DOES drop privileges and uses TCP workers.
        dns=subprocess.Popen(['chroot',str(ROOT),'/tmp/etc/passwall/bin/dnsmasq_default','-k','-C','/tmp/etc/passwall/acl/default/dnsmasq.conf','--pid-file='],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        time.sleep(.3);assert dns.poll() is None, dns.communicate()
        assert client.stdout.readline().strip()=='ready'
        host('ip','link','add','az-server','type','veth','peer','name','az-client')
        host('ip','addr','add',SERVER+'/24','dev','az-server');host('ip','link','set','az-server','up')
        host('ip','link','set','az-client','netns',str(client.pid))
        for args in [('ip','link','set','lo','up'),('ip','addr','add',CLIENT+'/24','dev','az-client'),('ip','link','set','az-client','up')]:
            host('nsenter','-t',str(client.pid),'-n','--',*args)
        class DNS(socketserver.BaseRequestHandler):
            def handle(self):
                packet,s=self.request;address=self.server.answer
                response=packet[:2]+struct.pack('!HHHHH',0x8180,1,1,0,0)+packet[12:]+b'\xc0\x0c'+struct.pack('!HHIH',1,1,30,4)+socket.inet_aton(address)
                s.sendto(response,self.client_address)
        for port,address in [(53,'203.0.113.66'),(444,'198.51.100.99')]:
            s=socketserver.ThreadingUDPServer((SERVER,port),DNS);s.answer=address
            threading.Thread(target=s.serve_forever,daemon=True).start();servers.append(s)
        def query(port,target=53,protocol='udp',keep=False):
            client.stdin.write(json.dumps({'port':port,'target':target,'protocol':protocol,'keep':keep})+'\n');client.stdin.flush()
            answer=json.loads(client.stdout.readline());assert 'error' not in answer,answer;return answer['address']
        # Start conntrack/NAT hooks before the original connection, but no redirect.
        nft('add table inet passwall\nadd set inet passwall psw_lan { type ipv4_addr; flags interval; elements = { 192.0.2.0/24 }; }\nadd chain inet passwall dstnat { type nat hook prerouting priority dstnat; policy accept; }\nadd rule inet passwall dstnat udp dport 65534 redirect to :65533\nadd chain inet passwall PSW_DNS\ninsert rule inet passwall dstnat ip saddr @psw_lan jump PSW_DNS\n')
        assert query(51758)=='203.0.113.66'
        assert query(52000,444)=='198.51.100.99'
        nft('add rule inet passwall PSW_DNS udp dport 53 redirect to :11400\nadd rule inet passwall PSW_DNS tcp dport 53 redirect to :11400\n')
        assert query(51758)=='203.0.113.66','existing five-tuple unexpectedly used new NAT'
        assert query(51759)=='198.51.100.42'
        before=native('/usr/sbin/conntrack','-L','-f','ipv4','-p','udp','-o','extended,id').stdout
        write('tmp/handoff-inventory',before,0o600)
        write('tmp/handoff-plan.uc',"import * as fs from 'fs'; import * as lib from '/usr/libexec/adzero/dns-handoff-lib.uc'; let cs=lib.plan(fs.readfile('/tmp/handoff-inventory'),{address:'"+SERVER+"',mask:24,device:'az-server'},11400); print(sprintf('%J',lib.deletion(cs[0])));\n",0o600)
        stale_delete=json.loads(native('/usr/bin/ucode',str('/tmp/handoff-plan.uc')).stdout)
        assert query(54000,protocol='tcp',keep=True)=='198.51.100.42'
        workers=[]
        for path in Path('/proc').glob('[0-9]*/stat'):
            try:
                fields=path.read_text().split(') ',1)[1].split()
                if fields[1]==str(dns.pid):workers.append(int(path.parent.name))
            except (FileNotFoundError,ProcessLookupError):pass
        assert workers,'TCP worker was not kept active during handoff'
        # No hand-written conntrack delete: exercise the released monitor,
        # stabilizing delay, native runtime detection, planner and exact action.
        (ROOT/'tmp/adzero-dns-handoff/status.json').unlink(missing_ok=True)
        monitor=subprocess.Popen(['chroot',str(ROOT),'/usr/libexec/adzero/dns-handoff','run'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        end=time.monotonic()+22;state=None
        # Native PassWall uses the first global. Never choose a later enabled
        # section, even when the native DNS process and redirect still exist.
        while time.monotonic()<end:
            assert monitor.poll() is None, monitor.communicate()
            try:state=json.loads((ROOT/'tmp/adzero-dns-handoff/status.json').read_text())
            except (FileNotFoundError,json.JSONDecodeError):pass
            if state and state.get('reason')=='passwall_disabled':break
            time.sleep(.25)
        assert state and state.get('reason')=='passwall_disabled' and state['repaired']==0,state
        assert native('/sbin/uci','-q','get','passwall.@global[0].enabled').stdout.strip()=='0'
        assert query(51758)=='203.0.113.66','disabled first global must not permit handoff'
        write('etc/config/passwall',active_config)
        assert native('/sbin/uci','-q','get','passwall.@global[0].enabled').stdout.strip()=='1'
        end=time.monotonic()+22
        while time.monotonic()<end:
            assert monitor.poll() is None, monitor.communicate()
            try:state=json.loads((ROOT/'tmp/adzero-dns-handoff/status.json').read_text())
            except (FileNotFoundError,json.JSONDecodeError):pass
            if state and state.get('repaired',0)>0:break
            time.sleep(.25)
        assert state and state.get('repaired')==1,state
        assert query(51758)=='198.51.100.42','same UDP socket did not move to new NAT after exact deletion'
        after=native('/usr/sbin/conntrack','-L','-f','ipv4','-p','udp','-o','extended,id').stdout
        def identity(raw,sport):
            lines=[l for l in raw.splitlines() if 'sport='+str(sport)+' ' in l]
            assert len(lines)==1,lines
            return lines[0].split(' id=')[-1].split()[0]
        assert identity(before,51759)==identity(after,51759),'correct DNS connection was removed'
        assert identity(before,52000)==identity(after,52000),'unrelated UDP traffic was removed'
        # Replaying an old command must not delete a newly correct binding on
        # the SAME original tuple. No --id filter is needed (or used).
        assert native('/usr/sbin/conntrack',*stale_delete,success=False).returncode==1
        unchanged=native('/usr/sbin/conntrack','-L','-f','ipv4','-p','udp','-o','extended,id').stdout
        assert identity(after,51758)==identity(unchanged,51758),'correct replacement on the same tuple was deleted'
        for i in range(3):assert query(55000+i,protocol='tcp')=='198.51.100.42'
        # Runtime UID is genuinely non-root; debug --no-daemon is not used.
        uid=[l for l in Path('/proc/'+str(dns.pid)+'/status').read_text().splitlines() if l.startswith('Uid:')][0].split()[1]
        assert uid!='0',uid
        result={'old_path_before_redirect':'203.0.113.66','same_socket_after_redirect':'203.0.113.66','fresh_socket_after_redirect':'198.51.100.42','same_socket_after_production_handoff':'198.51.100.42','correct_dns_flow_preserved':True,'unrelated_udp_flow_preserved':True,'tcp_dns_passed':3,'dnsmasq_uid':uid,'handoff':state,'fixture':manifest,'production_sha256':{n:hashlib.sha256((SOURCE/n).read_bytes()).hexdigest() for n in ('dns-handoff','dns-handoff.uc','dns-handoff-lib.uc')},'scope':'official OpenWrt 25.12.5 userspace and real kernel NAT, two disposable network namespaces; native inventory and LAN ubus are fixtures; no router or host firewall changes'}
        result['native_tools']={name:{'sha256':hashlib.sha256((ROOT/'usr/sbin'/name).read_bytes()).hexdigest(),'version':native('/usr/sbin/'+name,'--version').stdout.splitlines()[0]} for name in ('dnsmasq','conntrack','nft')}
        result['same_tuple_correct_replacement_preserved']=True
        result['bind_dynamic']=True
        result['concurrent_tcp_worker']=True
        result['first_disabled_later_enabled_skipped']=True
        result['first_enabled_extra_empty_accepted']=True
        result['passwall_configuration_unchanged']=(ROOT/'etc/config/passwall').read_text()==active_config
        assert result['passwall_configuration_unchanged']
        result['fixture_packages']=[r for r in json.loads((BASE/'packages.json').read_text()) if not r['name'].startswith(('kernel-','kmod-'))]
        (BASE/'handoff-proof.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    finally:
        for p in (monitor,dns):
            if p is not None:p.terminate();p.communicate(timeout=5)
        client.terminate();client.communicate(timeout=5)
        for s in servers:s.shutdown();s.server_close()
if __name__=='__main__':raise SystemExit(main())
