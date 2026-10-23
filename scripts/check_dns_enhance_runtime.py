"""Real OpenWrt ucode/socket, dnsmasq, nft and veth client in private namespaces.

Uses a prepared disposable OpenWrt fixture, never a router. Only service
inventory/LAN ubus responses and upstream DNS are fixtures; DNS sockets,
connection tracking, native handoff inspection, NAT and cleanup are real.
"""
from pathlib import Path
import hashlib,json,os,shutil,signal,socket,socketserver,struct,subprocess,sys,threading,time,tempfile
from build_sdk import source_hash
BASE=Path(os.environ['ADZERO_PASSWALL_FIXTURE']).resolve();ROOT=BASE/'root'
SOURCE=Path(__file__).resolve().parents[1]/'luci-app-adzero/root/usr/libexec/adzero'
SDK=Path('/home/slobys/.cache/adzero/sdks/openwrt-sdk-25.12.5-x86-64_gcc-14.3.0_musl.Linux-x86_64')
def main():
 if '--inside' not in sys.argv:return subprocess.call(['unshare','--net','--mount','--propagation','private',sys.executable,__file__,'--inside'])
 assert os.geteuid()==0 and ROOT!=Path('/') and ROOT.is_dir()
 source_before=source_hash(SOURCE.parents[3])
 assert hashlib.sha256((ROOT/'usr/sbin/dnsmasq').read_bytes()).hexdigest()=='80f3c8ba28681a32929e03e75c477b42493471e943290bc3b5a0e4ffe9c3df7a'
 pkg=next((SDK/'bin/packages/x86_64/base').glob('ucode-mod-socket-*.apk'))
 with tempfile.TemporaryDirectory(prefix='enhance-socket-',dir=BASE) as tmp:
  subprocess.run([str(SDK/'staging_dir/host/bin/apk'),'extract','--allow-untrusted','--no-chown','--destination',tmp,str(pkg)],check=True,capture_output=True)
  module=Path(tmp)/'usr/lib/ucode/socket.so';assert module.is_file()
  shutil.copyfile(module,ROOT/'usr/lib/ucode/socket.so')
 subprocess.run(['mount','-t','proc','proc',str(ROOT/'proc')],check=True)
 subprocess.run(['ip','link','set','lo','up'],check=True)
 client=subprocess.Popen(['unshare','--net','sleep','100'],start_new_session=True)
 time.sleep(.1)
 def ip(*args):subprocess.run(['ip',*args],check=True)
 def clientrun(*args):return subprocess.run(['nsenter','-t',str(client.pid),'-n',*args],check=True,text=True,capture_output=True,timeout=6)
 ip('link','add','br-lan','type','veth','peer','name','client0');ip('link','set','client0','netns',str(client.pid));ip('addr','add','192.168.50.1/24','dev','br-lan');ip('link','set','br-lan','up')
 clientrun('ip','link','set','lo','up');clientrun('ip','addr','add','192.168.50.2/24','dev','client0');clientrun('ip','addr','add','192.168.50.3/24','dev','client0');clientrun('ip','link','set','client0','up')
 def write(path,text,mode=0o644):
  p=ROOT/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);p.chmod(mode);return p
 def run(*args,ok=True):
  r=subprocess.run(['chroot',str(ROOT),*args],text=True,capture_output=True,timeout=15)
  assert not ok or r.returncode==0,(args,r.stdout,r.stderr)
  return r
 def cname(n):return b''.join(bytes([len(p)])+p.encode() for p in n.split('.'))+b'\0'
 def respond(q):
  p=12
  while q[p]:p+=q[p]+1
  domain=q[12:p+1];records=[]
  if domain==cname('shop.example'):
   target=cname('ads.example');records.append(b'\xc0\x0c'+struct.pack('!HHIH',5,1,60,len(target))+target)
   records.append(target+struct.pack('!HHIH',1,1,60,4)+socket.inet_aton('198.51.100.7'))
  else:records.append(b'\xc0\x0c'+struct.pack('!HHIH',1,1,60,4)+socket.inet_aton('198.51.100.8'))
  return q[:2]+struct.pack('!5H',0x8180,1,len(records),0,0)+q[12:p+5]+b''.join(records)
 class UDP(socketserver.BaseRequestHandler):
  def handle(self):q,s=self.request;s.sendto(respond(q),self.client_address)
 class TCP(socketserver.BaseRequestHandler):
  def handle(self):
   self.request.settimeout(1)
   def read(n):
    b=b''
    while len(b)<n:
     v=self.request.recv(n-len(b))
     if not v:return b''
     b+=v
    return b
   h=read(2)
   if h:
    r=respond(read(struct.unpack('!H',h)[0]));self.request.sendall(struct.pack('!H',len(r))+r)
 udp=socketserver.ThreadingUDPServer(('127.0.0.1',0),UDP);udp.daemon_threads=True
 tcp=socketserver.ThreadingTCPServer(udp.server_address,TCP);tcp.daemon_threads=True
 for s in (udp,tcp):threading.Thread(target=s.serve_forever,daemon=True).start()
 procs=[]
 original_ubus=ROOT/'usr/sbin/ubus';saved_ubus=(original_ubus.read_bytes(),original_ubus.stat().st_mode&0o777) if original_ubus.exists() else None
 try:
  shutil.copytree(SOURCE,ROOT/'usr/libexec/adzero',dirs_exist_ok=True)
  for p in (ROOT/'usr/libexec/adzero').iterdir():
   if p.is_file() and not p.suffix:p.chmod(0o755)
  write('etc/config/adzero',"config adzero 'main'\n option enabled '1'\n")
  write('etc/config/adblock-fast',"config adblock-fast 'config'\n option enabled '1'\n option dns 'dnsmasq.servers'\n")
  write('etc/config/passwall',"config global\n option enabled '1'\n option dns_redirect '1'\n")
  write('etc/adzero/managed','1');(ROOT/'etc/adzero/pause.json').unlink(missing_ok=True)
  write('etc/adzero/adapter.json',json.dumps(dict(schema=1,plugin='passwall',stage='configured_unverified',files=[],count=2)),0o600)
  write('var/run/adblock-fast/dnsmasq.servers','server=/ads.example/\nserver=/other.example/\n')
  write('usr/libexec/adzero/probe',"#!/bin/sh\necho '{\"dns\":{\"active_proxies\":[\"passwall\"],\"uncertain_proxies\":[]}}'\n",0o755)
  write('usr/sbin/ubus',"#!/bin/sh\necho '{\"l3_device\":\"br-lan\",\"ipv4-address\":[{\"address\":\"192.168.50.1\",\"mask\":24}]}'\n",0o755)
  shutil.copyfile(ROOT/'usr/sbin/dnsmasq',write('tmp/etc/passwall/bin/dnsmasq_default','',0o755))
  write('tmp/etc/passwall/acl/default/dnsmasq.conf',f'port=11400\nno-resolv\nno-hosts\ncache-size=0\nlisten-address=192.168.50.1\nbind-interfaces\nuser=root\nserver=127.0.0.1#{udp.server_address[1]}\n')
  p=subprocess.Popen(['chroot',str(ROOT),'/tmp/etc/passwall/bin/dnsmasq_default','-C','/tmp/etc/passwall/acl/default/dnsmasq.conf','-k'],stdout=subprocess.PIPE,stderr=subprocess.PIPE);procs.append(p);time.sleep(.1)
  assert p.poll() is None,p.communicate()
  rules='''table inet passwall {
 set psw_lan { type ipv4_addr; flags interval; elements = { 192.168.50.0/24 }; }
 set psw_local { type ipv4_addr; elements = { 192.168.50.1 }; }
 chain PSW_DNS { udp dport 53 redirect to :11400; tcp dport 53 redirect to :11400; }
 chain dstnat { type nat hook prerouting priority -100; policy accept; ip saddr @psw_lan ip daddr @psw_local jump PSW_DNS; }
}'''
  write('tmp/rules.nft',rules);run('/usr/sbin/nft','-f','/tmp/rules.nft')
  context=json.loads(run('/usr/libexec/adzero/dns-handoff','context').stdout);assert context['port']==11400,context
  config=dict(enabled=True,cname=True,failover=False,proxy_port=0,devices=[dict(ip='192.168.50.2',name='PC',enabled=True,allowed=[],blocked=['device.example'])])
  run('/sbin/uci','set','adzero.main.dns_enhance='+json.dumps(config));run('/sbin/uci','commit','adzero')
  log=(BASE/'enhance-native.log').open('w')
  service=subprocess.Popen(['chroot',str(ROOT),'/usr/libexec/adzero/dns-enhance','run'],stdout=log,stderr=log,start_new_session=True);procs.append(service)
  for _ in range(30):
   value=json.loads(run('/usr/libexec/adzero/dns-enhance','status').stdout)
   if value['runtime']['state']=='active':break
   time.sleep(.2)
  assert value['runtime']['state']=='active',(value,(BASE/'enhance-native.log').read_text())
  probe=write('tmp/client.py','')
  # Host Python executes in the separate client network namespace, outside chroot.
  code="""import socket,struct,json,sys
n,source,tcp=sys.argv[1:];q=struct.pack('!6H',12,256,1,0,0,0)+b''.join(bytes([len(x)])+x.encode() for x in n.split('.'))+b'\\0'+struct.pack('!HH',1,1)
with socket.socket(socket.AF_INET,socket.SOCK_STREAM if tcp=='1' else socket.SOCK_DGRAM) as s:
 s.settimeout(2);s.bind((source,0));s.connect(('192.168.50.1',53));s.sendall(struct.pack('!H',len(q))+q if tcp=='1' else q)
 r=s.recv(4096)
 if tcp=='1':r=r[2:]
 print(json.dumps(dict(answers=struct.unpack('!H',r[6:8])[0],rcode=r[3]&15)))
"""
  def query(n,source='192.168.50.2',tcp=False):return json.loads(clientrun(sys.executable,'-c',code,n,source,str(int(tcp))).stdout)
  for tcp_mode in (False,True):assert query('shop.example',tcp=tcp_mode)['answers']==0
  assert query('device.example')['answers']==0
  assert query('device.example','192.168.50.3')['answers']==1
  assert query('normal.example')['answers']==1
  # Save through the production UCI validator, without touching native DNS PID.
  after={**config,'cname':False}
  write('tmp/enhance-request.json',json.dumps(dict(before=config,after=after)),0o600)
  run('/usr/libexec/adzero/dns-enhance','save','/tmp/enhance-request.json');time.sleep(1.2)
  assert query('shop.example')['answers']==2
  assert p.poll() is None,'device/CNAME edits must not restart native DNS'
  assert run('/usr/libexec/adzero/dns-enhance','save','/tmp/enhance-request.json',ok=False).returncode!=0,'stale editor must be rejected'
  service.terminate();service.wait(timeout=6);log.close()
  assert run('/usr/sbin/nft','list','table','inet','adzero_dns_enhance',ok=False).returncode!=0
  assert query('shop.example')['answers']==2,'native path must work after cleanup'
  assert source_hash(SOURCE.parents[3])==source_before
  report=dict(schema=1,source_sha256=source_before,native_context=True,udp_cname=True,tcp_cname=True,device_block=True,other_device_unaffected=True,normal_domain=True,hot_policy_change=True,stale_policy_rejected=True,native_dns_not_restarted=True,owned_table_removed=True,native_path_restored=True,device_acceptance='not_run')
  (BASE/'enhance-proof.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
 finally:
  for p in reversed(procs):
   if p.poll() is None:p.terminate()
   try:p.wait(timeout=5)
   except subprocess.TimeoutExpired:p.kill();p.wait()
  udp.shutdown();tcp.shutdown();udp.server_close();tcp.server_close()
  client.terminate();client.wait(timeout=3)
  if saved_ubus:original_ubus.write_bytes(saved_ubus[0]);original_ubus.chmod(saved_ubus[1])
  else:original_ubus.unlink(missing_ok=True)
  shutil.copyfile(SOURCE/'probe',ROOT/'usr/libexec/adzero/probe');(ROOT/'usr/libexec/adzero/probe').chmod(0o755)
 return 0
if __name__=='__main__':sys.exit(main())
