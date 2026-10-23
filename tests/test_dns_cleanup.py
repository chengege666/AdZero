"""Native cleanup planner against missing tables, collisions and IO failures."""
import json,os,shlex,subprocess,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
UCODE=shlex.split(os.environ.get('ADZERO_UCODE',''))
@unittest.skipUnless(UCODE,'requires actual ucode')
class CleanupTest(unittest.TestCase):
 def call(self,results,prior=True):
  data=dict(results=results,prior=dict(lan=dict(address='192.168.50.1',device='br-lan',mask=24)) if prior is True else prior)
  p=subprocess.run(UCODE+[str(ROOT/'scripts/dns_cleanup_fixture.uc')],input=json.dumps(data),text=True,capture_output=True,timeout=5)
  self.assertEqual(p.returncode,0,p.stderr);return json.loads(p.stdout)
 def nft(self,exists=False,comment=None):
  rows=[dict(table=dict(family='inet',name='adzero_dns_enhance',comment=comment))] if exists else []
  return dict(code=0,output=json.dumps(dict(nftables=rows)))
 def empty(self):return dict(code=1,output='conntrack v1.4.8 (conntrack-tools): 0 flow entries have been deleted.\n')
 def test_missing_table_still_purges_only_owned_destination(self):
  r=self.call([self.nft(),dict(code=0),self.empty()]);self.assertIsNone(r['error'])
  self.assertEqual(len(r['calls']),3)
  for argv in r['calls'][1:]:
   self.assertEqual(argv[:4],['conntrack','-D','-f','ipv4'])
   self.assertIn('5354',argv);self.assertIn('192.168.50.1',argv);self.assertNotIn('-F',argv)
 def test_foreign_table_is_never_deleted(self):
  r=self.call([self.nft(True),self.nft(True,'another owner')]);self.assertIsNotNone(r['error'])
  self.assertEqual(len(r['calls']),2)
 def test_failed_table_delete_never_claims_cleanup(self):
  r=self.call([self.nft(True),self.nft(True,'AdZero DNS enhance v1'),dict(code=1,output='permission denied')])
  self.assertIsNotNone(r['error']);self.assertEqual(len(r['calls']),3)
 def test_inventory_failure_is_not_treated_as_absence(self):
  r=self.call([dict(code=1,output='permission denied')]);self.assertIsNotNone(r['error']);self.assertEqual(len(r['calls']),1)
 def test_failed_conntrack_and_missing_intent_are_not_success(self):
  r=self.call([self.nft(),dict(code=1,output='conntrack: Operation not permitted')]);self.assertIsNotNone(r['error'])
  self.assertEqual(len(r['calls']),2)
  r=self.call([self.nft(True),self.nft(True,'AdZero DNS enhance v1')],None);self.assertIsNotNone(r['error'])
  self.assertEqual(len(r['calls']),2)
 def test_repeated_cleanup_after_retirement_is_empty(self):
  r=self.call([self.nft()],None);self.assertIsNone(r['error']);self.assertEqual(len(r['calls']),1)
