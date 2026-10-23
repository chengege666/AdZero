"""Execute the real init start_service with a procd recording fixture."""
import json,os,shlex,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SHELL=shlex.split(os.environ.get('ADZERO_TEST_SHELL','/bin/sh'))
@unittest.skipIf(os.name=='nt','native shell checks run under Linux/WSL')
class InitTest(unittest.TestCase):
 def check_workers(self,enabled,failover):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);bin_=p/'bin';bin_.mkdir()
   uci=bin_/'uci';uci.write_text('#!/bin/sh\ncase "$3" in adzero.main.enabled) echo 1;; adzero.main.dns_enhance) printf \'%s\' "$ENHANCE_CONFIG";; esac\n');uci.chmod(0o755)
   jf=bin_/'jsonfilter';jf.write_text('#!/usr/bin/env python3\nimport json,sys\nv=json.load(sys.stdin);print(str(v.get(sys.argv[-1][2:],False)).lower())\n');jf.chmod(0o755)
   script=p/'test.sh';script.write_text('''. "$INIT"
procd_open_instance() { printf '%s\n' "${1:-watch}"; }
procd_set_param() { :; }
procd_close_instance() { :; }
start_service
''')
   env={**os.environ,'PATH':str(bin_)+':'+os.environ['PATH'],'ENHANCE_CONFIG':json.dumps(dict(enabled=enabled,failover=failover)),'INIT':str(ROOT/'luci-app-adzero/root/etc/init.d/adzero')}
   r=subprocess.run(SHELL+[str(script)],env=env,text=True,capture_output=True,timeout=5);self.assertEqual(r.returncode,0,r.stderr)
   expected=['watch']+(['dns_enhance'] if enabled else [])+(['dns_monitor'] if failover else [])+['dns_handoff','observe']
   self.assertEqual(r.stdout.splitlines(),expected)
 def test_default_starts_no_optional_workers(self):self.check_workers(False,False)
 def test_only_enhanced_entry(self):self.check_workers(True,False)
 def test_only_monitor(self):self.check_workers(False,True)
 def test_both_optional_features(self):self.check_workers(True,True)
