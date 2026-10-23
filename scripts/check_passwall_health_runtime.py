"""Native PassWall DNS engine + SIGCHLD regression, private net/mount NS only.

Prepared official OpenWrt 25.12.5 userspace and upstream ChinaDNS-NG required.
Native rc.common and pinned PassWall block-list generator are real; service
body, node API and DNS upstreams are explicit fixtures. Not router acceptance.
"""
from pathlib import Path
import hashlib,json,os,shutil,socket,socketserver,struct,subprocess,sys,threading,time

BASE=Path(os.environ['ADZERO_PASSWALL_FIXTURE']).resolve();ROOT=BASE/'root'
SOURCE=Path(__file__).resolve().parents[1]/'luci-app-adzero/root/usr/libexec/adzero'

def main():
 if '--inside' not in sys.argv:
  return subprocess.call(['unshare','--net','--mount','--propagation','private',sys.executable,__file__,'--inside'])
 assert os.geteuid()==0 and ROOT.is_dir() and ROOT!=Path('/')
 assert hashlib.sha256((ROOT/'usr/sbin/dnsmasq').read_bytes()).hexdigest()=='80f3c8ba28681a32929e03e75c477b42493471e943290bc3b5a0e4ffe9c3df7a'
 subprocess.run(['ip','link','set','lo','up'],check=True)
 subprocess.run(['mount','-t','proc','proc',str(ROOT/'proc')],check=True)
 def write(path,text,mode=0o644):
  p=ROOT/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);p.chmod(mode);return p
 def run(*args,success=True):
  r=subprocess.run(['chroot',str(ROOT),*args],text=True,capture_output=True,timeout=25)
  assert not success or r.returncode==0,(args,r.returncode,r.stdout,r.stderr)
  return r
 def uc(text):
  write('tmp/test.uc',text)
  return run('/usr/bin/ucode','-S','/tmp/test.uc')
 def query(name='chatgpt.example',kind=1,tcp=False):
  q=struct.pack('!HHHHHH',7,256,1,0,0,0)+b''.join(bytes([len(p)])+p.encode() for p in name.split('.'))+b'\0'+struct.pack('!HH',kind,1)
  with socket.socket(socket.AF_INET,socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as s:
   s.settimeout(.8);s.connect(('127.0.0.1',11400));s.sendall(struct.pack('!H',len(q))+q if tcp else q)
   if tcp:
    head=s.recv(2)
    if len(head)!=2:raise RuntimeError('short TCP DNS')
    size=struct.unpack('!H',head)[0];r=b''
    while len(r)<size:
     part=s.recv(size-len(r))
     if not part:raise RuntimeError('closed TCP DNS')
     r+=part
   else:r=s.recv(4096)
  return dict(rcode=r[3]&15,answers=struct.unpack('!H',r[6:8])[0])
 def signals():
  pid=int((ROOT/'tmp/dns.pid').read_text());raw=Path('/proc/'+str(pid)+'/status').read_text()
  mask=int(next(l.split()[1] for l in raw.splitlines() if l.startswith('SigBlk:')),16)
  children=Path('/proc/'+str(pid)+'/task/'+str(pid)+'/children').read_text().split()
  zombies=sum('State:\tZ' in Path('/proc/'+p+'/status').read_text() for p in children if Path('/proc/'+p+'/status').exists())
  return dict(blocked_sigchld=bool(mask&0x10000),zombies=zombies)
 class DNS(socketserver.BaseRequestHandler):
  @staticmethod
  def answer(q):
   p=12
   while q[p]:p+=q[p]+1
   p+=1;kind=struct.unpack('!H',q[p:p+2])[0]
   address=socket.inet_pton(socket.AF_INET if kind==1 else socket.AF_INET6,'198.51.100.42' if kind==1 else '2001:db8::42')
   return q[:2]+struct.pack('!HHHHH',0x8180,1,1,0,0)+q[12:p+4]+b'\xc0\x0c'+struct.pack('!HHIH',kind,1,30,len(address))+address
  def handle(self):
   q,s=self.request;s.sendto(self.answer(q),self.client_address)
 class TCPDNS(socketserver.BaseRequestHandler):
  def handle(self):
   def read(n):
    data=b''
    while len(data)<n:
     part=self.request.recv(n-len(data))
     if not part:return b''
     data+=part
    return data
   while True:
    head=read(2)
    if not head:return
    q=read(struct.unpack('!H',head)[0])
    if not q:return
    reply=DNS.answer(q);self.request.sendall(struct.pack('!H',len(reply))+reply)
 upstream=socketserver.ThreadingUDPServer(('127.0.0.1',0),DNS)
 threading.Thread(target=upstream.serve_forever,daemon=True).start();up='127.0.0.1#'+str(upstream.server_address[1])
 tcp_upstream=socketserver.ThreadingTCPServer(upstream.server_address,TCPDNS);tcp_upstream.daemon_threads=True
 threading.Thread(target=tcp_upstream.serve_forever,daemon=True).start()
 try:
  shutil.copytree(SOURCE,ROOT/'usr/libexec/adzero',dirs_exist_ok=True)
  for name in ['adapter','probe']: (ROOT/'usr/libexec/adzero'/name).chmod(0o755)
  for name in ['etc/adzero','etc/passwall/rules','usr/share/passwall/rules','tmp/etc/passwall/acl/default','tmp/etc/passwall/bin','tmp/etc/passwall_tmp/user_rules','usr/lib/lua/luci/passwall']:(ROOT/name).mkdir(parents=True,exist_ok=True)
  for name in ['adapter.json','adapter.previous.json']:(ROOT/'etc/adzero'/name).unlink(missing_ok=True)
  write('etc/config/adzero',"config adzero 'main'\n option enabled '1'\n option routing_enabled '1'\n")
  write('etc/config/adblock-fast',"config adblock-fast 'config'\n option dns 'dnsmasq.servers'\n")
  write('etc/config/passwall',"config global 'main'\n option enabled '1'\n option dns_shunt 'chinadns-ng'\n option dns_mode 'xray'\n option node 'chosen'\nconfig nodes 'chosen'\n option type 'Xray'\n")
  write('var/run/adblock-fast/dnsmasq.servers','server=/ads.example/\nserver=/track.example/\n')
  write('etc/passwall/rules/block_host','user.example\n')
  for name in ['chnlist','chnroute']:write('usr/share/passwall/rules/'+name,'198.51.100.0/24\n' if name=='chnroute' else 'cn.example\n')
  write('tmp/inventory.json',json.dumps(dict(plugins=[dict(id='passwall',installed=True,enabled=True,runtime='running')],cores=['xray'])))
  for name in ['app.sh','helper_chinadns_add.lua']:shutil.copyfile(BASE/'upstream'/name,ROOT/'usr/share/passwall'/name)
  helper=ROOT/'usr/share/passwall/helper_chinadns_add.lua'
  assert hashlib.sha256(helper.read_bytes()).hexdigest()=='a5fc56efecc3e427aeb2e80ae81474a0034da74ed5ad8ab1abbfca9f6485efc9'
  # Native generator; fixture only the LuCI API environment and absent nodes.
  api=r'''
local a={TMP_PATH='/tmp/etc/passwall',CACHE_PATH='/tmp/etc/passwall_tmp'}
getmetatable('').__mod=function(s,v)return string.format(s,v)end
function trim(s)return (s:gsub('^%s*(.-)%s*$','%1'))end
local function exec(s)local p=io.popen(s);local r=p:read('*a');p:close();return r end
a.sys={exec=exec,call=os.execute}
a.fs={access=function(s)local f=io.open(s);if f then f:close();return true end return false end}
a.datatypes={hostname=function(s)return s:find('%.')~=nil end}
a.remove=function(s)os.execute('rm -f '..s)end
a.get_std_domain=function(s)s=trim(s);if s:find('#') then return '' end return s end
a.uci_get_c=function()return nil end
a.uci_foreach_c=function()end
a.is_finded=function()return false end
a.log=function()end
a.vps_domain_exclude=function()return false end
a.get_args=function(args)local r={};for i=1,#args,2 do r[args[i]]=args[i+1] end return r end
return a
'''
  write('usr/lib/lua/luci/passwall/api.lua',api)
  for name,target in [('dnsmasq_default','/usr/sbin/dnsmasq'),('chinadns-ng','/usr/bin/chinadns-ng')]:
   p=ROOT/'tmp/etc/passwall/bin'/name
   if p.is_symlink():p.unlink()
   p.symlink_to(target)
  body='''#!/bin/sh /etc/rc.common
stop() {
 for f in /tmp/dns.pid /tmp/china.pid; do
  [ ! -f "$f" ] || { kill "$(cat "$f")" 2>/dev/null || :; rm -f "$f"; }
 done
 sleep 1
}
restart() {
 stop
 echo restart >> /tmp/restarts
 if [ -f /tmp/old-launch ]; then
  printf 'port=11400\nuser=dnsmasq\ngroup=dnsmasq\nno-resolv\nmax-tcp-connections=2\nhost-record=chatgpt.example,198.51.100.42\n' > /tmp/etc/passwall/acl/default/dnsmasq.conf
 else
  lua /usr/share/passwall/helper_chinadns_add.lua -FLAG default -LISTEN_PORT 15354 -DNS_LOCAL UPSTREAM -DNS_TRUST UPSTREAM -USE_BLOCK_LIST 1 -USE_DIRECT_LIST 0 -USE_PROXY_LIST 0 -GFWLIST 0 -CHNLIST 0 -DEFAULT_MODE proxy -DEFAULT_TAG gfw -NODE chosen -NFTFLAG 0 -NO_LOGIC_LOG 1 -LOG_FILE /dev/null > /tmp/etc/passwall/acl/default/chinadns_ng.conf || return 1
  /tmp/etc/passwall/bin/chinadns-ng -C /tmp/etc/passwall/acl/default/chinadns_ng.conf >/tmp/china.log 2>&1 & echo $! > /tmp/china.pid
  printf 'port=11400\nuser=dnsmasq\ngroup=dnsmasq\nno-resolv\nmax-tcp-connections=2\nserver=127.0.0.1#15354\n' > /tmp/etc/passwall/acl/default/dnsmasq.conf
 fi
 /tmp/etc/passwall/bin/dnsmasq_default -k -C /tmp/etc/passwall/acl/default/dnsmasq.conf --pid-file=/tmp/dns.pid >/tmp/dns.log 2>&1 & echo $! > /tmp/dns.pid
 sleep 1
}
'''.replace('UPSTREAM',up)
  write('etc/init.d/passwall',body,0o755)
  write('tmp/old-launch','1')
  uc("print(system(['/bin/sh','/etc/rc.common','/etc/init.d/passwall','restart'],5000));\n")
  deadline=time.monotonic()+8
  while True:
   try:
    if query()['answers']==1:break
   except (TimeoutError,OSError,RuntimeError):pass
   assert time.monotonic()<deadline,'old DNS did not start'
   time.sleep(.1)
  outcomes=[]
  for n in range(6):
   try:outcomes.append(query(tcp=True))
   except (TimeoutError,OSError,RuntimeError) as e:outcomes.append(type(e).__name__+': '+str(e))
  time.sleep(.1);old=signals()
  assert old['blocked_sigchld'] and old['zombies']>=2 and sum(type(v)==str and v.startswith('TimeoutError:') for v in outcomes)>=4,(old,outcomes)
  (ROOT/'tmp/old-launch').unlink()
  # Production apply and restore paths, no hand-written signal unblocking.
  env='/tmp/inventory.json'
  def adapter(action):
   return run('/usr/bin/env','ADZERO_ADAPTER_INVENTORY='+env,'/usr/bin/ucode','-S','/usr/libexec/adzero/adapter.uc','--',action)
  cycles=[]
  for cycle in range(5):
   adapter('apply')
   status=json.loads(adapter('status').stdout)
   assert status['runtime']['state']=='ready',status
   assert run('/sbin/uci','-q','get','passwall.main.dns_shunt').stdout.strip()=='chinadns-ng'
   for tcp in [False,True]:
    for kind in [1,28]:
     assert query('ads.example',kind,tcp)==dict(rcode=0,answers=0)
     for domain in ['chatgpt.example','codex.example','cn.example']:assert query(domain,kind,tcp)==dict(rcode=0,answers=1)
   # More requests than the TCP worker limit must continue to complete.
   for n in range(8):assert query(tcp=True)['answers']==1
   time.sleep(.1);health=signals();assert health==dict(blocked_sigchld=False,zombies=0),health
   before=(ROOT/'tmp/restarts').read_text();adapter('apply');assert (ROOT/'tmp/restarts').read_text()==before
   if cycle==1:
    write('var/run/adblock-fast/dnsmasq.servers','server=/ads.example/\nserver=/new-ad.example/\nserver=/track.example/\n')
    adapter('apply');assert query('new-ad.example')==dict(rcode=0,answers=0)
   toggles=[]
   for wanted in ['0','1']:
    count=len((ROOT/'tmp/restarts').read_text().splitlines())
    run('/sbin/uci','set','adzero.main.routing_enabled='+wanted);run('/sbin/uci','commit','adzero')
    adapter('reconfigure-passwall')
    assert len((ROOT/'tmp/restarts').read_text().splitlines())==count+1
    assert query(tcp=True)['answers']==1 and query('ads.example')['answers']==0
    assert signals()==dict(blocked_sigchld=False,zombies=0)
    toggles.append(dict(enabled=wanted=='1',restarts=1))
   adapter('remove');assert (ROOT/'etc/passwall/rules/block_host').read_text()=='user.example\n'
   assert signals()['blocked_sigchld'] is False
   cycles.append(dict(cycle=cycle+1,health=health,repeat_apply_restarted=False,routing_toggles=toggles))
  started=time.monotonic();bounded=uc("print(system(['/usr/libexec/timeout-coreutils','-k','.2','1','/bin/sleep','3']));\n")
  assert bounded.stdout.strip()=='124' and time.monotonic()-started<2.5,bounded
  # Exact reported native set shape: compare --check on fresh private sets.
  run('/usr/sbin/nft','add','table','inet','passwall')
  checks={}
  for name in ['psw_chn','psw_gfw','psw_shunt']:
   run('/usr/sbin/nft','add','set','inet','passwall',name,'{ type ipv4_addr; flags interval,timeout; auto-merge; timeout 2d; gc-interval 1h; }')
   checks[name]=run('/usr/sbin/nft','--check','add','element','inet','passwall',name,'{ 192.0.2.254 }',success=False).returncode
  report=dict(old_timed_launch=dict(signals=old,tcp_results=outcomes),production_cycles=cycles,timeout_exit=124,nft_check_exit=checks,nft_scope='fresh namespace sets and development kernel; does not explain or repair router ENOENT',production_sha256={n:hashlib.sha256((SOURCE/n).read_bytes()).hexdigest() for n in ['adapter.uc','proxy-state.uc']},native_sha256={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['usr/sbin/dnsmasq','usr/libexec/timeout-coreutils','usr/bin/ucode']},chinadns=json.loads((BASE/'chinadns-binary.json').read_text()),packages=json.loads((BASE/'packages.json').read_text()),scope='official OpenWrt 25.12.5 x86 userspace, native rc.common/dnsmasq-full 2.93, pinned upstream ChinaDNS-NG and PassWall generator; private net/mount namespaces; init body/node API/upstreams fixtures; no Windows/router/transparent proxy acceptance')
  (BASE/'health-proof.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
 finally:
  run('/bin/sh','/etc/rc.common','/etc/init.d/passwall','stop',success=False)
  upstream.shutdown();upstream.server_close()
  tcp_upstream.shutdown();tcp_upstream.server_close()
  subprocess.run(['umount',str(ROOT/'proc')],check=True)
if __name__=='__main__':raise SystemExit(main())
