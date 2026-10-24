"""Run the real watcher shell with deterministic time/inventory fixtures."""
import json,os,shlex,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SHELL=shlex.split(os.environ.get('ADZERO_TEST_SHELL','/bin/sh'))
@unittest.skipIf(os.name=='nt','requires POSIX shell')
class Watch(unittest.TestCase):
 def test_stable_switch_reconciles_early_but_overlap_does_not_bounce(self):
  with tempfile.TemporaryDirectory() as d:
   home=Path(d);(home/'bin').mkdir();(home/'etc/adzero').mkdir(parents=True)
   def write(name,text):p=home/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);p.chmod(0o755);return p
   (home/'tick').write_text('0')
   common='#!/usr/bin/env python3\nimport json\nfrom pathlib import Path\nh=Path('+repr(d)+');n=int((h/"tick").read_text())\n'
   write('bin/uci',common+'print("1" if n<8 else "0")\n')
   write('bin/sleep',common+'(h/"tick").write_text(str(n+1))\n')
   write('bin/jsonfilter',common+'import sys\nv=json.load(sys.stdin)["dns"];print(json.dumps(v["active_proxies"]));print(json.dumps(v["uncertain_proxies"]))\n')
   write('usr/libexec/adzero/probe',common+'paths=[["nailink"],["nailink"],["nailink","passwall"],["nailink"],["passwall"],["passwall"],["passwall"],["passwall"]];print(json.dumps({"dns":{"active_proxies":paths[n],"uncertain_proxies":[]}}))\n')
   write('usr/libexec/adzero/ctl',common+'with (h/"calls").open("a") as f:f.write(str(n)+"\\n")\n')
   text=(ROOT/'luci-app-adzero/root/usr/libexec/adzero/watch').read_text().replace('/usr/libexec/adzero/',d+'/usr/libexec/adzero/').replace('/etc/adzero/',d+'/etc/adzero/')
   script=write('watch',text)
   p=subprocess.run(SHELL+[str(script)],env={**os.environ,'PATH':str(home/'bin')+':'+os.environ['PATH']},text=True,capture_output=True,timeout=10)
   self.assertEqual(p.returncode,0,p.stderr);self.assertEqual((home/'calls').read_text().splitlines(),['0','1','5'])
