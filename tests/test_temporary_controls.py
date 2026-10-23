"""Expiry drives the real serialized controller, backend and adapter path."""
import unittest
import test_controls
@unittest.skipUnless(test_controls.UCODE,'requires actual ucode/UCI')
class TemporaryTest(unittest.TestCase):
 def setUp(self):
  self.f=test_controls.ControlsTest();self.f.setUp();self.addCleanup(self.f.doCleanups)
  self.f.ctl('enable')
 def test_due_exception_restores_without_browser_and_without_download_refetch(self):
  self.f.ctl('temporary','sub.ads.example','ads.example','600')
  self.assertEqual(self.f.query('ads.example')['match'],'allowed')
  self.f.write('proc/uptime','1601.0 0\n');self.f.ctl('reconcile')
  self.assertEqual(self.f.query('ads.example')['match'],'exact')
  self.assertEqual(self.f.status()['policy']['temporary'],[])
 def test_failed_exception_rolls_back_timer_and_list(self):
  self.f.write('fail-backend-once','1')
  self.f.ctl('temporary','ads.example','ads.example','600',ok=False)
  self.assertEqual(self.f.status()['policy']['temporary'],[])
  self.assertEqual(self.f.query('ads.example')['match'],'exact')
