"""Real dae/eBPF and Mihomo/Fake-IP cases, called in the private enhance netns."""
from pathlib import Path
import gzip,hashlib,json,os,signal,struct,subprocess,time
from check_dns_core import SHA256 as MIHOMO_SHA
from check_dae import SHA256 as DAE_SHA
import tarfile

def check(base,root,source,run,write,query,clientrun,client_code,upstream,procs):
 repo=source.parents[4];art=repo/'artifacts/upstream'
 dae_archive=art/'dae-v2.1.1.tar.xz';mihomo_archive=art/'mihomo-linux-amd64-compatible-v1.19.32.gz'
 assert hashlib.sha256(dae_archive.read_bytes()).hexdigest()==DAE_SHA
 assert hashlib.sha256(mihomo_archive.read_bytes()).hexdigest()==MIHOMO_SHA
 core=base/'alias-native-core';core.mkdir(exist_ok=True)
 with tarfile.open(dae_archive) as tar:
  member=next(m for m in tar if m.isfile() and m.name.endswith('/bin/dae'))
  (core/'dae').write_bytes(tar.extractfile(member).read());(core/'dae').chmod(0o755)
 (core/'mihomo').write_bytes(gzip.decompress(mihomo_archive.read_bytes()));(core/'mihomo').chmod(0o755)
 (core/'config.dae').unlink(missing_ok=True)
 adapter=root/'usr/libexec/adzero/adapter';old_adapter=adapter.read_bytes();old_mode=adapter.stat().st_mode&0o777
 def publish(plugin,ctx):
  write('etc/adzero/adapter.json',json.dumps(dict(schema=1,plugin=plugin,stage='configured_unverified',files=[])),0o600)
  write('usr/libexec/adzero/probe',"#!/bin/sh\necho '"+json.dumps(dict(dns=dict(active_proxies=[plugin],uncertain_proxies=[])))+"'\n",0o755)
  write('usr/libexec/adzero/adapter',"#!/bin/sh\n[ \"$1\" = alias-context ] || exit 1\ncat /tmp/native-context.json\n",0o755)
  write('tmp/native-context.json',json.dumps(ctx),0o600)
 def transform(op,*args):
  write('tmp/native-transform.uc',"import * as fs from 'fs'; import * as lib from '/usr/libexec/adzero/dns-native-lib.uc';let p=json(fs.readfile(ARGV[0]));print(sprintf('%J',lib[p.op](...p.args)));\n")
  write('tmp/native-input.json',json.dumps(dict(op=op,args=args)),0o600)
  return json.loads(run('/usr/bin/ucode','-S','/tmp/native-transform.uc','/tmp/native-input.json').stdout)
 lan=dict(device='br-lan',address='192.168.50.1',mask=24)
 worker=None
 def start():
  nonlocal worker
  log=(base/'alias-enhance.log').open('a');worker=subprocess.Popen(['chroot',str(root),'/usr/libexec/adzero/dns-enhance','run'],stdout=log,stderr=log,start_new_session=True);procs.append(worker);log.close()
  for _ in range(40):
   value=json.loads(run('/usr/libexec/adzero/dns-enhance','status').stdout)
   if value['runtime']['state']=='active':return
   if worker.poll() is not None:break
   time.sleep(.2)
  raise AssertionError((value,(base/'alias-enhance.log').read_text()))
 def stop():
  worker.terminate();worker.wait(timeout=7)
 def config():
  write('etc/config/adzero',"config adzero 'main'\n option enabled '1'\n option dns_enhance '"+json.dumps(dict(enabled=True,cname=True,devices=[dict(ip='192.168.50.2',enabled=True,allowed=[],blocked=['device.example'])]))+"'\n")
 def direct(port,domain='normal.example'):
  code=client_code.replace("('192.168.50.1',53)",f"('192.168.50.1',{port})")
  return json.loads(clientrun(__import__('sys').executable,'-c',code,domain,'192.168.50.2','0','0').stdout)
 results={}
 try:
  run('/usr/sbin/nft','delete','table','inet','passwall')
  config()
  subprocess.run(['sysctl','-w','net.ipv4.conf.br-lan.forwarding=1','net.ipv6.conf.br-lan.forwarding=1','net.ipv4.conf.br-lan.send_redirects=0','net.ipv4.conf.all.send_redirects=0'],check=True,capture_output=True)
  subprocess.run(['mount','-t','bpf','bpf','/sys/fs/bpf'],check=True)
  dns=transform('nai_dns',f'upstream {{ local: "udp://127.0.0.1:{upstream}" }}\nrouting {{ request {{ fallback: local }} response {{ fallback: accept }} }}',lan)
  routing=transform('nai_routing','fallback: direct\n',lan)
  path=core/'config.dae';path.write_text('global { disable_waiting_network: true\nlan_interface: br-lan\nlog_level: info\n}\ndns { '+dns+' }\nrouting { '+routing+' }\n');path.chmod(0o600)
  log=(base/'alias-dae.log').open('w');dae=subprocess.Popen([str(core/'dae'),'run','--disable-pidfile','--disable-sudo','-c',str(path)],stdout=log,stderr=log);procs.append(dae);log.close()
  for _ in range(40):
   try:
    if direct(5355)['answers']==1:break
   except Exception:pass
   if dae.poll() is not None:raise AssertionError((base/'alias-dae.log').read_text())
   time.sleep(.15)
  else:raise AssertionError('native dae listener unavailable')
  ctx=dict(plugin='nailink',port=5355,lan=lan);publish('nailink',ctx)
  write('tmp/native-operation.json',json.dumps(ctx),0o600);run('/usr/libexec/adzero/dns-native','install','/tmp/native-operation.json')
  assert query('shop.example')['answers']==2,'native must_direct/NAT path did not reach dae'
  start()
  for tcp in (False,True):
   assert query('shop.example',tcp=tcp)['answers']==0
   assert query('normal.example',tcp=tcp)['answers']==1
   assert query('alias-device.example',tcp=tcp)['answers']==0
   assert query('alias-device.example','192.168.50.3',tcp=tcp)['answers']==2
   for kind in (64,65):assert query('service.example',tcp=tcp,kind=kind)['answers']==0
  run('/sbin/uci','add_list','adzero.main.allowed_domain=shop.example');run('/sbin/uci','commit','adzero');time.sleep(1.2)
  assert query('shop.example')['answers']==2
  run('/sbin/uci','delete','adzero.main.allowed_domain');run('/sbin/uci','commit','adzero');time.sleep(1.2)
  assert query('shop.example',source_port=53020)['answers']==0
  stop();assert query('shop.example',source_port=53020)['answers']==2,'worker exit lost native fallback'
  # Kill rather than gracefully stop, then explicitly recover the owned entry.
  start();assert query('shop.example',source_port=53021)['answers']==0
  os.killpg(worker.pid,signal.SIGKILL);worker.wait(timeout=4);run('/usr/libexec/adzero/dns-enhance','cleanup')
  assert query('shop.example',source_port=53021)['answers']==2
  results['nailink']=dict(real_dae=True,real_ebpf=True,udp_tcp_alias=True,https_svcb=True,device_exception=True,global_allow=True,graceful_native_fallback=True,crash_native_fallback=True)
  dae.terminate();dae.wait(timeout=7);run('/usr/libexec/adzero/dns-native','cleanup','/tmp/native-operation.json')
  # Existing Mihomo DNS/API; production enhancement never edits this config.
  original=dict(mode='rule',**{'external-controller':'127.0.0.1:19090','secret':'alias-private','rules':['MATCH,DIRECT'],'dns':dict(enable=True,listen='0.0.0.0:17874',**{'enhanced-mode':'fake-ip','fake-ip-range':'198.18.0.1/16','nameserver':[f'udp://127.0.0.1:{upstream}']})})
  config_path=core/'mihomo.json';config_path.write_text(json.dumps(original));before=config_path.read_bytes()
  log=(base/'alias-mihomo.log').open('w');mihomo=subprocess.Popen([str(core/'mihomo'),'-d',str(core),'-f',str(config_path)],stdout=log,stderr=log);procs.append(mihomo);log.close()
  for _ in range(30):
   try:
    if direct(17874)['answers']>=1:break
   except Exception:pass
   time.sleep(.15)
  else:raise AssertionError((base/'alias-mihomo.log').read_text())
  ctx=transform('mihomo',original,lan);publish('openclash',ctx)
  write('tmp/openclash-dns.nft','add table inet openclash\nadd chain inet openclash dns { type nat hook prerouting priority -100; policy accept; }\nadd rule inet openclash dns iifname "br-lan" ip daddr 192.168.50.1 meta l4proto { tcp, udp } th dport 53 redirect to :17874\n')
  run('/usr/sbin/nft','-f','/tmp/openclash-dns.nft');start()
  for tcp in (False,True):
   assert query('shop.example',tcp=tcp)['answers']==0,'Fake-IP hid an alias'
   normal=query('normal.example',tcp=tcp);assert normal['answers']>=1,(tcp,normal,(base/'alias-enhance.log').read_text(),(base/'alias-mihomo.log').read_text())
   for kind in (64,65):assert query('service.example',tcp=tcp,kind=kind)['answers']==0
  wire_code=client_code.replace('rcode=r[3]&15','rcode=r[3]&15,wire=r.hex()')
  clean=json.loads(clientrun(__import__('sys').executable,'-c',wire_code,'normal.example','192.168.50.2','0','0').stdout)
  baseline=json.loads(clientrun(__import__('sys').executable,'-c',wire_code.replace("('192.168.50.1',53)","('192.168.50.1',17874)"),'normal.example','192.168.50.2','0','0').stdout)
  assert bytes.fromhex(clean['wire'])[-4:]==bytes.fromhex(baseline['wire'])[-4:] and bytes.fromhex(clean['wire'])[-4:-2]==bytes([198,18]),'clean Fake-IP mapping changed'
  run('/sbin/uci','add_list','adzero.main.allowed_domain=shop.example');run('/sbin/uci','commit','adzero');time.sleep(1.2)
  assert query('shop.example')['answers']>=1
  value=json.loads(run('/usr/libexec/adzero/dns-enhance','status').stdout)['runtime'];assert value['inspection']['checked']>=1,value
  assert config_path.read_bytes()==before,'enhancement rewrote native settings'
  stop();assert query('normal.example')['answers']>=1
  results['openclash']=dict(real_mihomo=True,fake_ip_preserved=True,clean_mapping_identical=True,real_resolver_api=True,authenticated_api=True,udp_tcp_alias=True,https_svcb=True,global_allow=True,config_unchanged=True,native_fallback=True)
  return results
 finally:
  if worker and worker.poll() is None:worker.terminate();worker.wait(timeout=7)
  adapter.write_bytes(old_adapter);adapter.chmod(old_mode)
