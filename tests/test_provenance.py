"""Attribution follows applied bytes and refuses failed/unapplied refreshes."""
import json,unittest
import test_sources
@unittest.skipUnless(test_sources.UCODE,'requires actual ucode/UCI')
class ProvenanceTest(unittest.TestCase):
 def setUp(self):
  self.s=test_sources.SourcesTest();self.s.setUp();self.addCleanup(self.s.doCleanups)
  self.f=self.s.fixture;self.s.body.write_text('ads.example\ntracker.example\n')
  self.s.add(name='Verified list',url='https://rules.example/list?token=private-token');self.s.run_source('finish')
  self.f.ctl('enable')
 def test_applied_subscription_and_custom_source_without_private_urls(self):
  r=self.f.query('ads.example');p=r['provenance']
  self.assertEqual(p['state'],'known')
  self.assertIn('Verified list',[i['name'] for i in p['items']])
  self.assertIn('自定义拦截',[i['name'] for i in p['items']])
  self.assertNotIn('private-token',json.dumps(r));self.assertNotIn('https://',json.dumps(r))
 def test_refreshed_but_unapplied_source_not_attributed(self):
  self.s.body.write_text('other-list.example\n')
  self.s.run_source('begin','refresh')
  self.s.run_source('rollback');self.s.run_source('discard')
  r=self.f.query('ads.example')
  self.assertNotIn('Verified list',[i['name'] for i in r['provenance']['items']])
  self.assertTrue(r['provenance']['incomplete'])
 def test_unconfirmed_adapter_does_not_claim_source_applied(self):
  path=self.f.root/'etc/adzero/adapter.json';j=json.loads(path.read_text());j['stage']='recovery_required';path.write_text(json.dumps(j))
  self.assertEqual(self.f.query('ads.example')['provenance']['state'],'unavailable')
