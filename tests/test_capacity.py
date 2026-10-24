"""Device capacity, native count semantics and incremental source selections."""
import json,os,shlex,subprocess,tempfile,unittest
from pathlib import Path
import test_batch
ROOT=Path(__file__).resolve().parents[1]
UCODE=shlex.split(os.environ.get('ADZERO_UCODE',''))
@unittest.skipUnless(UCODE,'requires actual OpenWrt ucode/UCI')
class Capacity(unittest.TestCase):
 def call(self,operation,*arguments):
  p=subprocess.run(UCODE+[str(ROOT/'scripts/capacity_transform.uc')],input=json.dumps(dict(operation=operation,arguments=arguments)),text=True,capture_output=True,timeout=15)
  self.assertEqual(p.returncode,0,p.stderr);return json.loads(p.stdout)
 def test_device_tiers_and_unknown_hardware_are_bounded(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'proc/meminfo';path.parent.mkdir()
   self.assertEqual(self.call('limits',d)['total_domains'],500000)
   for kib,total,source in [(262144,500000,500000),(524288,1000000,750000),(1048576,1000000,750000),(1572864,2000000,1000000),(3962420,4000000,2000000)]:
    path.write_text(f'MemTotal: {kib} kB\n')
    value=self.call('limits',d);self.assertEqual((value['total_domains'],value['source_domains']),(total,source))
    self.assertGreaterEqual(value['total_domains'],value['source_domains'])
 def test_optimization_keeps_hosts_exact_and_domain_boundaries(self):
  values={'ads.example':True,'child.ads.example':True,'notads.example':True,'safe.ads.example':True}
  self.assertEqual(self.call('effective',values,[],'dnsmasq.servers'),2)
  self.assertEqual(self.call('effective',values,[],'dnsmasq.addnhosts'),4)
  self.assertEqual(self.call('effective',values,['ads.example'],'dnsmasq.servers'),1)
  self.assertEqual(self.call('effective',values,['notads.example'],'dnsmasq.servers'),1)
 def batch(self):
  b=test_batch.BatchTest();b.setUp();self.addCleanup(b.doCleanups);return b
 def test_already_enabled_source_does_not_leave_a_legacy_500k_increment_quota(self):
  b=self.batch();b.f.write('proc/meminfo','MemTotal: 3962420 kB\n')
  b.sources.body.write_text(''.join(f'a{n}.example\n' for n in range(240000)))
  p=b.plan();b.add(p,url='https://rules.example/first');b.apply(p);b.f.ctl('enable')
  b.sources.body.write_text(''.join(f'b{n}.example\n' for n in range(300000)))
  p=b.plan();b.add(p,'Second','https://rules.example/second');b.apply(p)
  c=b.sources.data()['capacity'];self.assertEqual(c['unique_domains'],540001)
  self.assertEqual(c['limit'],4000000);self.assertEqual(c['state'],'complete')
  self.assertEqual([v['domains'] for v in c['per_source']],[240000,300000])
 def test_same_domain_in_multiple_lists_is_not_repeated_capacity(self):
  b=self.batch();b.sources.body.write_text(''.join(f'a{n}.example\n' for n in range(300000)))
  p=b.plan();b.add(p,url='https://rules.example/first');b.apply(p)
  p=b.plan();b.add(p,'Second','https://rules.example/second');b.apply(p)
  c=b.sources.data()['capacity'];self.assertEqual(c['input_domains'],600001)
  self.assertEqual((c['unique_domains'],c['effective_domains']),(300001,300001))
 def test_parent_optimization_is_counted_before_the_final_device_limit(self):
  b=self.batch();b.sources.body.write_text('ads.example\n'+''.join(f'a{n}.ads.example\n' for n in range(300000)))
  p=b.plan();b.add(p,url='https://rules.example/first');b.apply(p)
  b.sources.body.write_text(''.join(f'b{n}.ads.example\n' for n in range(300000)))
  p=b.plan();b.add(p,'Second','https://rules.example/second');b.apply(p)
  c=b.sources.data()['capacity'];self.assertEqual(c['unique_domains'],600001)
  self.assertEqual(c['effective_domains'],1);self.assertEqual(c['state'],'complete')
