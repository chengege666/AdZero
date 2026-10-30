"""Run the real watcher shell with deterministic time/inventory fixtures."""
import json,os,shlex,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SHELL=shlex.split(os.environ.get('ADZERO_TEST_SHELL','/bin/sh'))
@unittest.skipIf(os.name=='nt','requires POSIX shell')
class Watch(unittest.TestCase):
 def run_watch(self,failures=(),fail_code=75,ticks=8,core_switch=False):
  with tempfile.TemporaryDirectory() as d:
   home=Path(d);(home/'bin').mkdir();(home/'etc/adzero').mkdir(parents=True)
   def write(name,text):p=home/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);p.chmod(0o755);return p
   (home/'tick').write_text('0')
   common='#!/usr/bin/env python3\nimport json\nfrom pathlib import Path\nh=Path('+repr(d)+');n=int((h/"tick").read_text())\n'
   write('bin/uci',common+'print("1" if n<'+str(ticks)+' else "0")\n')
   write('bin/sleep',common+'(h/"tick").write_text(str(n+1))\n')
   write('bin/jsonfilter',common+'import sys\nv=json.load(sys.stdin)["dns"];print(json.dumps(v["active_proxies"]));print(json.dumps(v["uncertain_proxies"]));print(json.dumps(v.get("active_paths",[])))\n')
   source='paths=[["nailink"],["nailink"],["nailink","passwall"],["nailink"],["passwall"]];print(json.dumps({"dns":{"active_proxies":paths[min(n,4)],"uncertain_proxies":[]}}))\n'
   if core_switch: source='core="dae" if n<3 else "mihomo";print(json.dumps({"dns":{"active_proxies":["nailink"],"uncertain_proxies":[],"active_paths":[{"plugin":"nailink","core":core}]}}))\n'
   write('usr/libexec/adzero/probe',common+source)
   write('usr/libexec/adzero/ctl',common+'with (h/"calls").open("a") as f:f.write(str(n)+"\\n")\nimport sys\nsys.exit('+str(fail_code)+' if n in '+repr(list(failures))+' else 0)\n')
   write('bin/logger',common+'pass\n')
   text=(ROOT/'luci-app-adzero/root/usr/libexec/adzero/watch').read_text().replace('/usr/libexec/adzero/',d+'/usr/libexec/adzero/').replace('/etc/adzero/',d+'/etc/adzero/')
   script=write('watch',text)
   p=subprocess.run(SHELL+[str(script)],env={**os.environ,'PATH':str(home/'bin')+':'+os.environ['PATH']},text=True,capture_output=True,timeout=10)
   self.assertEqual(p.returncode,0,p.stderr);return (home/'calls').read_text().splitlines()
 def test_stable_switch_reconciles_early_but_overlap_does_not_bounce(self):
  self.assertEqual(self.run_watch(),['0','1','5'])
 def test_core_change_inside_nailink_reconciles_without_waiting_a_minute(self):
  self.assertEqual(self.run_watch(core_switch=True),['0','1','4'])
 def test_busy_lock_keeps_the_stable_switch_pending_until_next_tick(self):
  self.assertEqual(self.run_watch([5]),['0','1','5','6'])
 def test_repeated_failure_does_not_acknowledge_or_duplicate_a_finished_switch(self):
  self.assertEqual(self.run_watch([5,6]),['0','1','5','6','7'])
 def test_actual_failure_waits_a_minute_without_marking_the_path_complete(self):
  self.assertEqual(self.run_watch([5],fail_code=1,ticks=20),['0','1','5','17'])
