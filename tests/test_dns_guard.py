"""Actual ucode/UCI guard transactions; nft and services are isolated fixtures."""
import json,os,shlex,shutil,socketserver,struct,subprocess,tempfile,threading,time,unittest
from pathlib import Path
from test_dns_policy import PROFILE,read
from test_dns_enhance import answer
ROOT=Path(__file__).resolve().parents[1];UCODE=shlex.split(os.environ.get('ADZERO_UCODE',''))

@unittest.skipUnless(UCODE,'requires actual OpenWrt ucode/UCI')
class GuardTest(unittest.TestCase):
 def setUp(self):
  class UDP(socketserver.BaseRequestHandler):
   def handle(s):q,sock=s.request;sock.sendto(answer(q,[]),s.client_address)
  class TCP(socketserver.BaseRequestHandler):
   def handle(s):
    s.request.settimeout(2)
    try:q=read(s.request,struct.unpack('!H',read(s.request,2))[0]);r=answer(q,[]);s.request.sendall(struct.pack('!H',len(r))+r)
    except OSError:pass
  class TCPServer(socketserver.ThreadingTCPServer):allow_reuse_address=True;daemon_threads=True
  class UDPServer(socketserver.ThreadingUDPServer):allow_reuse_address=True;daemon_threads=True
  for port in [7874,11400]:
   for server,handler in [(UDPServer,UDP),(TCPServer,TCP)]:
    service=server(('127.0.0.1',port),handler);threading.Thread(target=service.serve_forever,kwargs={'poll_interval':.02},daemon=True).start();self.addCleanup(service.server_close);self.addCleanup(service.shutdown)
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  for name in ['etc/adzero','etc/config','etc/init.d','tmp','bin','usr/bin','usr/libexec/adzero']:(self.root/name).mkdir(parents=True,exist_ok=True)
  self.write('etc/config/adzero',"config adzero 'main'\n option enabled '1'\n option dns_profile '"+json.dumps({**PROFILE,'strict':True})+"'\n")
  self.write('etc/config/dhcp',"config dnsmasq 'main'\n list server '223.5.5.5'\n option noresolv '0'\n")
  self.write('etc/adzero/adapter.json',json.dumps(dict(plugin='openclash',stage='configured_unverified')))
  self.write('etc/init.d/dnsmasq','#!/bin/sh\necho restart >> "'+str(self.root/'restart.log')+'"\n',True)
  (self.root/'usr/bin/timeout').symlink_to(shutil.which('timeout'))
  self.write('bin/ubus','#!/bin/sh\nprintf \'%s\' \'{"l3_device":"br-lan","ipv4-address":[{"address":"192.168.2.1","mask":24}]}\'\n',True)
  self.write('bin/conntrack','#!/bin/sh\nexit 0\n',True)
  self.write('bin/nft','''#!/usr/bin/env python3
import os,json,sys
from pathlib import Path
r=Path(os.environ['ADZERO_GUARD_ROOT']);a=sys.argv[1:];p=r/'nft.json'
if a==['-j','list','tables']: print(json.dumps(dict(nftables=[dict(table=dict(family='inet',name='adzero_dns_guard'))] if p.exists() else [])))
elif a[:4]==['-j','list','table','inet']:print(p.read_text())
elif '-f' in a:
 if (r/'nft-fail').exists():sys.exit(1)
 if '-c' not in a:p.write_text(json.dumps(dict(nftables=[dict(table=dict(family='inet',name='adzero_dns_guard',comment='AdZero strict DNS v1'))])));(r/'last.nft').write_text(Path(a[-1]).read_text())
elif a[:2]==['delete','table']:p.unlink()
else:sys.exit(2)
''',True)
  self.write('usr/libexec/adzero/probe','#!/bin/sh\ncat "'+str(self.root/'inventory.json')+'"\n',True)
  self.write('inventory.json','{"dns":{"active_proxies":["openclash"]}}')
  self.env={**os.environ,'ADZERO_GUARD_ROOT':str(self.root),'PATH':str(self.root/'bin')+':'+os.environ['PATH']}
 def write(self,name,value,executable=False):
  p=self.root/name;p.write_text(value);p.chmod(0o755 if executable else 0o600);return p
 def run_guard(self,action,*args,ok=True):
  r=subprocess.run(UCODE+[str(ROOT/'luci-app-adzero/root/usr/libexec/adzero/dns-guard.uc'),action,*args],env=self.env,text=True,capture_output=True,timeout=10)
  self.assertEqual(r.returncode==0,ok,r.stdout+r.stderr);return r
 def state(self):return json.loads((self.root/'etc/adzero/dns-guard.json').read_text())
 def activate(self):
  self.run_guard('preflight');self.run_guard('hold');self.run_guard('pin','openclash','127.0.0.1#7874');self.run_guard('ready')
 def test_initial_hold_pin_ready_and_cleanup_preserve_original_dns(self):
  before=(self.root/'etc/config/dhcp').read_text();self.activate();self.assertEqual(self.state()['state'],'active')
  self.assertIn('127.0.0.1#7874',(self.root/'etc/config/dhcp').read_text());self.assertTrue(self.state()['bootstrap'])
  self.run_guard('cleanup');after=(self.root/'etc/config/dhcp').read_text()
  self.assertIn("list server '223.5.5.5'",after);self.assertIn("option noresolv '0'",after)
  self.assertFalse((self.root/'etc/adzero/dns-guard.json').exists());self.assertFalse((self.root/'nft.json').exists())
 def test_service_reload_does_not_close_an_active_guard(self):
  self.activate();self.run_guard('ensure');self.assertEqual(self.state()['state'],'active')
  stamp=(self.root/'etc/adzero/dns-guard.json').stat().st_mtime_ns;self.run_guard('ready');self.assertEqual(stamp,(self.root/'etc/adzero/dns-guard.json').stat().st_mtime_ns)
 def test_reboot_holds_saved_lan_before_network_ubus_is_available(self):
  self.activate();value=self.state();value['boot']='previous-boot';self.write('etc/adzero/dns-guard.json',json.dumps(value))
  (self.root/'nft.json').unlink();self.write('bin/ubus','#!/bin/sh\nexit 1\n',True)
  self.run_guard('boot-ensure');self.assertEqual(self.state()['state'],'held');self.assertEqual(self.state()['lan']['device'],'br-lan')
  self.assertIn('br-lan',(self.root/'last.nft').read_text());self.assertNotEqual(self.state()['boot'],'previous-boot')
  self.assertIn('127.0.0.1#7874',(self.root/'etc/config/dhcp').read_text())
 def test_openclash_native_restore_rebases_before_passwall_handoff(self):
  self.write('etc/config/dhcp',"config dnsmasq 'main'\n list server '127.0.0.1#7874'\n option noresolv '1'\n")
  self.write('etc/config/openclash',"config openclash 'config'\n option redirect_dns '1'\n list dnsmasq_server '223.5.5.5'\n option dnsmasq_noresolv '0'\n")
  self.activate()
  self.write('etc/config/dhcp',"config dnsmasq 'main'\n list server '223.5.5.5'\n option noresolv '0'\n")
  self.run_guard('hold');self.run_guard('pin','passwall','127.0.0.1#11400')
  self.assertEqual(self.state()['before'],dict(server=['223.5.5.5'],noresolv='0'))
  self.run_guard('cleanup');self.assertNotIn('7874',(self.root/'etc/config/dhcp').read_text())
 def test_openclash_cannot_learn_a_retired_passwall_pin_as_its_restore_dns(self):
  self.activate();self.run_guard('hold');self.run_guard('pin','passwall','127.0.0.1#11400')
  self.write('etc/config/openclash',"config openclash 'config'\n option redirect_dns '1'\n list dnsmasq_server '127.0.0.1#11400'\n option dnsmasq_noresolv '1'\n")
  self.write('etc/config/dhcp',"config dnsmasq 'main'\n list server '127.0.0.1#7874'\n option noresolv '1'\n")
  self.run_guard('hold');self.run_guard('pin','openclash','127.0.0.1#7874')
  cfg=(self.root/'etc/config/openclash').read_text();self.assertNotIn('11400',cfg);self.assertIn('223.5.5.5',cfg)
  self.run_guard('cleanup');self.assertIn('7874',(self.root/'etc/config/dhcp').read_text())
 def test_only_exact_old_lan_dns_udp_tuple_is_retired(self):
  line='ipv4 2 udp 17 117 src=192.168.2.107 dst=192.168.2.1 sport=51758 dport=53 src=192.168.2.1 dst=192.168.2.107 sport=11400 dport=51758 zone=0 id=17\n'
  self.write('flows',line)
  self.write('bin/conntrack','#!/bin/sh\nif [ "$1" = -L ]; then cat "'+str(self.root/'flows')+'"; else printf \'%s \' "$@" > "'+str(self.root/'deleted')+'"; fi\n',True)
  self.activate();args=(self.root/'deleted').read_text();self.assertIn('--sport 51758',args);self.assertIn('--reply-port-src 11400',args);self.assertIn('--orig-src 192.168.2.107',args);self.assertNotIn('-F',args)
 def test_proxy_handoff_keeps_firewall_held_until_new_ready(self):
  self.activate();self.run_guard('hold');self.assertEqual(self.state()['state'],'held')
  self.write('etc/adzero/adapter.json',json.dumps(dict(plugin='passwall',stage='configured_unverified')))
  self.run_guard('pin','passwall','127.0.0.1#11400');self.assertEqual(self.state()['state'],'held')
  self.run_guard('ready');self.assertEqual(self.state()['plugin'],'passwall');self.assertEqual(self.state()['state'],'active')
 def test_native_or_manual_dns_changes_cannot_be_overwritten_silently(self):
  self.activate();self.write('etc/config/dhcp',"config dnsmasq 'main'\n list server '9.9.9.9'\n option noresolv '0'\n")
  self.run_guard('hold');self.run_guard('pin','passwall','127.0.0.1#11400',ok=False)
  self.assertEqual(self.state()['state'],'held');self.assertFalse(self.state()['bootstrap'])
  self.run_guard('cleanup');self.assertIn('9.9.9.9',(self.root/'etc/config/dhcp').read_text())
 def test_nft_failure_and_foreign_table_retain_old_protection(self):
  self.activate();before=(self.root/'last.nft').read_bytes();self.write('nft-fail','1')
  self.run_guard('hold',ok=False);self.assertEqual(before,(self.root/'last.nft').read_bytes())
  (self.root/'nft-fail').unlink();self.write('nft.json','{"nftables":[{"table":{"family":"inet","name":"adzero_dns_guard","comment":"other"}}]}')
  self.run_guard('cleanup',ok=False);self.assertTrue((self.root/'etc/adzero/dns-guard.json').exists())
 def test_missing_pin_and_incomplete_adapter_cannot_open_dns(self):
  self.run_guard('hold');self.run_guard('ready',ok=False)
  self.run_guard('pin','openclash','127.0.0.1#99999',ok=False)
  self.run_guard('pin','openclash','127.0.0.1#7874');self.write('etc/adzero/adapter.json','{"plugin":"openclash","stage":"preparing"}')
  self.run_guard('ready',ok=False);self.assertEqual(self.state()['state'],'held')
 def test_watch_closes_after_proxy_identity_changes(self):
  self.activate();self.write('inventory.json','{"dns":{"active_proxies":["passwall"]}}')
  p=subprocess.Popen(UCODE+[str(ROOT/'luci-app-adzero/root/usr/libexec/adzero/dns-guard.uc'),'watch'],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  try:
   for _ in range(100):
    if self.state()['state']=='held':break
    time.sleep(.025)
   self.assertEqual(self.state()['state'],'held')
  finally:p.terminate();p.communicate(timeout=3)
 def test_changed_default_lan_is_held_and_never_reported_as_old_active_scope(self):
  self.activate();self.write('bin/ubus','#!/bin/sh\nprintf \'%s\' \'{"l3_device":"br-new","ipv4-address":[{"address":"192.168.3.1","mask":24}]}\'\n',True)
  self.run_guard('ensure');self.assertEqual(self.state()['state'],'held');self.assertEqual(self.state()['lan']['device'],'br-new')
  self.assertIn('br-new',(self.root/'last.nft').read_text())
