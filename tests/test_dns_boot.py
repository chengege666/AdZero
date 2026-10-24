"""Execute the real early procd script without touching host services."""
import os,shlex,subprocess,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SHELL=shlex.split(os.environ.get('ADZERO_TEST_SHELL','/bin/sh'))

class DNSBootTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  for name in ['etc/adzero','usr/libexec/adzero','bin']:(self.root/name).mkdir(parents=True)
  self.log=self.root/'events';self.env={**os.environ,'ADZERO_DNS_INIT_ROOT':str(self.root),'EVENTS':str(self.log),'PATH':str(self.root/'bin')+':'+os.environ['PATH'],'ENABLED':'1','ROUTING':'1','STRICT':'false'}
  self.write('bin/uci','#!/bin/sh\ncase "$3" in adzero.main.enabled) echo "$ENABLED";; adzero.main.routing_enabled) echo "$ROUTING";; adzero.main.dns_profile) echo "$STRICT";; esac\n')
  self.write('bin/jsonfilter','#!/bin/sh\ncat\n')
  self.write('usr/libexec/adzero/dns-guard','#!/bin/sh\necho "guard $*" >> "$EVENTS"\nexit "${GUARD_FAILURE:-0}"\n')
 def write(self,name,text):
  p=self.root/name;p.write_text(text);p.chmod(0o755)
 def start(self,expected=0):
  command='''procd_open_instance() { echo open >> "$EVENTS"; }
procd_set_param() { printf '%s\\n' "$*" >> "$EVENTS"; }
procd_close_instance() { echo close >> "$EVENTS"; }
. "$1"
start_service
'''
  r=subprocess.run(SHELL+['-c',command,'fixture',str(ROOT/'luci-app-adzero/root/etc/init.d/adzero-dns')],env=self.env,capture_output=True,text=True,timeout=5)
  self.assertEqual(r.returncode,expected,r.stdout+r.stderr)
  return self.log.read_text() if self.log.exists() else ''
 def marker(self):self.write('etc/adzero/dns-pool-needed','AdZero DNS pool v1\n')
 def test_default_mode_does_not_launch_optional_worker(self):self.assertEqual(self.start(),'')
 def test_saved_pool_starts_before_late_proxy_services(self):
  self.marker();text=self.start();self.assertIn('command ucode -S /usr/libexec/adzero/dns-pool.uc',text)
  script=(ROOT/'luci-app-adzero/root/etc/init.d/adzero-dns').read_text();self.assertIn('START=21',script)
 def test_strict_boot_reinstalls_guard_before_pool(self):
  self.marker();self.env['STRICT']='true';text=self.start();self.assertLess(text.index('guard boot-ensure'),text.index('open'))
 def test_strict_native_mihomo_starts_only_guard(self):
  self.env['STRICT']='true';self.assertEqual(self.start(),'guard boot-ensure\n')
 def test_failed_guard_never_starts_pool(self):
  self.marker();self.env.update(STRICT='true',GUARD_FAILURE='1');self.assertEqual(self.start(expected=1),'guard boot-ensure\n')
 def test_disabled_or_unowned_pool_never_starts(self):
  self.marker();self.env['ENABLED']='0';self.assertEqual(self.start(),'')
  self.env['ENABLED']='1';self.write('etc/adzero/dns-pool-needed','external marker\n');self.assertEqual(self.start(expected=1),'')
