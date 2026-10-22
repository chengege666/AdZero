"""Actual OpenWrt ucode/libuci policy transactions on an isolated filesystem."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UCODE = shlex.split(os.environ.get('ADZERO_UCODE',''))
PROGRAM = ROOT/'luci-app-adzero/root/usr/libexec/adzero/policy.uc'

@unittest.skipUnless(UCODE,'requires actual OpenWrt ucode/UCI')
class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='adzero-policy-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {**os.environ,'ADZERO_POLICY_ROOT':str(self.root),'ADZERO_STATE_DIR':str(self.root/'etc/adzero')}
        self.write('etc/config/adzero',"config adzero 'main'\n option enabled '1'\n")
        self.write('etc/config/adblock-fast',"config adblock-fast 'config'\n option dns 'dnsmasq.servers'\n list allowed_domain 'original.example'\n")
        self.write('var/run/adblock-fast/dnsmasq.servers','server=/ads.example/\nserver=/other.example/\n')
        self.write('proc/sys/kernel/random/boot_id','fixture-boot-1\n')
        self.write('proc/uptime','1000.80 99\n')

    def write(self,path,data):
        p=self.root/path; p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data);return p

    def run_policy(self,*args,ok=True):
        result=subprocess.run(UCODE+[str(PROGRAM),'--',*args],env=self.env,text=True,capture_output=True,timeout=15)
        self.assertEqual(result.returncode==0,ok,result.stderr+result.stdout)
        return result

    def status(self): return json.loads(self.run_policy('status').stdout)
    def query(self,name): return json.loads(self.run_policy('lookup',name).stdout)

    def test_query_exact_parent_none_and_url_without_network(self):
        before={str(p):p.read_bytes() for p in (self.root/'etc/config').glob('*')}
        self.assertEqual(self.query(' HTTPS://Ads.Example/path?q=x ')['match'],'exact')
        item=self.query('login.ads.example.')
        self.assertEqual((item['match'],item['scope']),('parent','ads.example'))
        self.assertEqual(self.query('normal.example')['match'],'none')
        self.assertEqual(before,{str(p):p.read_bytes() for p in (self.root/'etc/config').glob('*')})

    def test_domain_input_is_strictly_data(self):
        for name in ('ads.example;id','$(id).example','https://user:pass@ads.example/','*.example','127.0.0.1','localhost','file:///etc/passwd','bad..example','-bad.example','a'*64+'.example','测试.example','https://ads.example:bad/'):
            with self.subTest(name=name): self.run_policy('lookup',name,ok=False)

    def test_scope_must_match_fresh_rules(self):
        self.run_policy('begin-allow','login.ads.example','example',ok=False)
        self.run_policy('begin-allow','normal.example','ads.example',ok=False)
        self.run_policy('begin-allow','login.ads.example','login.ads.example',ok=False)
        self.assertFalse((self.root/'etc/adzero/allow-pending.json').exists())

    def test_allow_commit_restore_preserves_original_and_personal_choice(self):
        self.run_policy('begin-allow','sub.ads.example','ads.example')
        self.assertEqual(self.status()['allowed'],['ads.example'])
        backend=(self.root/'etc/config/adblock-fast').read_text()
        self.assertIn('original.example',backend);self.assertIn('ads.example',backend)
        self.assertTrue(self.status()['pending'])
        self.run_policy('finish')
        self.assertEqual(self.query('sub.ads.example')['match'],'allowed')
        self.run_policy('restore')
        self.assertNotIn('ads.example',(self.root/'etc/config/adblock-fast').read_text())
        self.assertIn('original.example',(self.root/'etc/config/adblock-fast').read_text())
        self.assertEqual(self.status()['allowed'],['ads.example'])
        self.run_policy('apply')
        self.assertIn('ads.example',(self.root/'etc/config/adblock-fast').read_text())

    def test_allow_failure_rollback_is_repeatable_and_keeps_pending_until_finish(self):
        before=(self.root/'etc/config/adblock-fast').read_text()
        self.run_policy('begin-allow','ads.example','ads.example')
        self.run_policy('rollback');self.run_policy('rollback')
        self.assertEqual(self.status()['allowed'],[])
        self.assertTrue(self.status()['pending'])
        self.assertIn('original.example',(self.root/'etc/config/adblock-fast').read_text())
        self.run_policy('finish'); self.assertFalse(self.status()['pending'])

    def test_revoke_returns_to_original_lists(self):
        self.run_policy('begin-allow','ads.example','ads.example');self.run_policy('finish')
        self.run_policy('begin-revoke','ads.example','ads.example');self.run_policy('finish')
        self.assertEqual(self.status()['allowed'],[])
        self.assertNotIn('ads.example',(self.root/'etc/config/adblock-fast').read_text())

    def test_external_edit_is_not_overwritten(self):
        self.run_policy('begin-allow','ads.example','ads.example');self.run_policy('finish')
        text=(self.root/'etc/config/adblock-fast').read_text()+"\n list allowed_domain 'external.example'\n"
        self.write('etc/config/adblock-fast',text)
        self.run_policy('restore',ok=False)
        self.assertEqual((self.root/'etc/config/adblock-fast').read_text(),text)
        self.run_policy('validate',ok=False)

    def test_active_allow_mirror_must_match_and_disabled_choices_can_persist(self):
        self.run_policy('begin-allow','ads.example','ads.example');self.run_policy('finish')
        self.run_policy('validate')
        self.run_policy('restore')
        self.run_policy('validate')  # Backend fixture has no enabled flag yet.
        self.write('etc/config/adblock-fast', (self.root/'etc/config/adblock-fast').read_text()+"\n option enabled '1'\n")
        self.run_policy('validate',ok=False)

    def test_query_formats_keep_suffix_semantics_explicit(self):
        for mode,raw,expected in [('dnsmasq.addnhosts','0.0.0.0 ads.example\n0.0.0.0 other.example\n','none'),
                                  ('smartdns.domainset','ads.example\nother.example\n','parent'),
                                  ('unbound.adb_list','local-zone: "ads.example." always_nxdomain\nlocal-zone: "other.example." always_nxdomain\n','parent')]:
            with self.subTest(mode=mode):
                self.write('etc/config/adblock-fast',"config adblock-fast 'config'\n option dns '"+mode+"'\n")
                path='var/lib/unbound/adb_list.adblock-fast' if mode=='unbound.adb_list' else 'var/run/adblock-fast/'+mode
                self.write(path,raw)
                self.assertEqual(self.query('sub.ads.example')['match'],expected)

    def test_overlapping_operations_and_allow_all_are_rejected(self):
        self.run_policy('begin-allow','ads.example','ads.example')
        self.run_policy('begin-allow','other.example','other.example',ok=False)
        self.run_policy('restore')
        self.write('var/run/adblock-fast/dnsmasq.servers','server=/ads.example/\n')
        self.run_policy('begin-allow','ads.example','ads.example',ok=False)

    def test_pause_uses_uptime_and_expires_across_reboot(self):
        self.run_policy('pause-begin','300');self.run_policy('pause-stage','paused')
        self.assertEqual(self.status()['pause']['remaining'],300)
        self.write('proc/uptime','1100.4 2\n')
        self.assertEqual(self.status()['pause']['remaining'],200)
        self.run_policy('pause-due',ok=False)
        self.write('proc/sys/kernel/random/boot_id','fixture-boot-2\n')
        self.assertEqual(self.status()['pause']['remaining'],0)
        self.run_policy('pause-due')

    def test_retry_backoff_and_manual_recovery(self):
        self.run_policy('pause-begin','300');self.write('proc/uptime','1301.0 2\n')
        self.run_policy('pause-stage','paused','resume_failed')
        self.run_policy('pause-due',ok=False)
        self.run_policy('is-paused')
        self.write('proc/uptime','1332.0 2\n');self.run_policy('pause-due')
        self.run_policy('pause-clear');self.assertIsNone(self.status()['pause'])

    def test_invalid_or_partial_pause_is_not_reported_as_paused(self):
        self.run_policy('pause-begin','15',ok=False)
        self.run_policy('pause-begin','900');self.run_policy('is-paused',ok=False)
        self.run_policy('pause-begin','1800',ok=False)
        self.run_policy('pause-stage','recovery_required');self.run_policy('is-paused',ok=False)

    def control_input(self,allowed=None,blocked=None):
        before={k:self.status()[k] for k in ('allowed','blocked')}
        return str(self.write('controls.json',json.dumps({'before':before,'after':{'allowed':allowed or [],'blocked':blocked or []}})))

    def test_batch_controls_preserve_external_rules_and_restore_ownership(self):
        config=self.root/'etc/config/adblock-fast'
        config.write_text(config.read_text()+" list blocked_domain 'original-block.example'\n")
        self.run_policy('begin-controls',self.control_input(['ads.example'],['custom.example','other-custom.example']))
        self.assertEqual(self.status()['blocked'],['custom.example','other-custom.example'])
        self.assertTrue(self.status()['pending'])
        self.run_policy('confirm');self.run_policy('finish');self.run_policy('validate')
        self.assertIn('custom.example',config.read_text());self.assertIn('original-block.example',config.read_text())
        self.run_policy('restore')
        self.assertNotIn('custom.example',config.read_text());self.assertIn('original-block.example',config.read_text())
        self.assertEqual(self.status()['blocked'],['custom.example','other-custom.example'])
        self.run_policy('has-allowed')

    def test_controls_rollback_restores_both_lists_and_retains_journal_until_finish(self):
        original=(self.root/'etc/config/adblock-fast').read_text()
        self.run_policy('begin-controls',self.control_input(['ads.example'],['custom.example']))
        self.run_policy('rollback');self.run_policy('rollback')
        self.assertEqual(self.status()['blocked'],[]);self.assertEqual(self.status()['allowed'],[])
        self.assertIn('original.example',(self.root/'etc/config/adblock-fast').read_text())
        self.assertNotIn('custom.example',(self.root/'etc/config/adblock-fast').read_text())
        self.assertTrue(self.status()['pending']);self.run_policy('finish');self.assertFalse(self.status()['pending'])

    def test_disabled_controls_save_choices_without_touching_external_backend(self):
        self.write('etc/config/adzero',"config adzero 'main'\n option enabled '0'\n")
        config=self.root/'etc/config/adblock-fast';before=config.read_bytes()
        path=self.control_input(['future.example'],['custom.example'])
        self.run_policy('begin-controls',path);self.run_policy('finish')
        self.assertEqual(config.read_bytes(),before);self.assertEqual(self.status()['blocked'],['custom.example'])

    def test_controls_reject_stale_overlapping_and_parent_scope_without_writes(self):
        for allowed,blocked in [(['sub.ads.example'],[]),(['ads.example'],['sub.ads.example']),(['*.example'],[])]:
            with self.subTest(allowed=allowed):
                before=(self.root/'etc/config/adblock-fast').read_bytes()
                self.run_policy('begin-controls',self.control_input(allowed,blocked),ok=False)
                self.assertFalse(self.status()['pending']);self.assertEqual((self.root/'etc/config/adblock-fast').read_bytes(),before)
        path=self.control_input([],['custom.example'])
        self.write('etc/config/adzero',"config adzero 'main'\n option enabled '1'\n list blocked_domain 'external.example'\n")
        self.run_policy('begin-controls',path,ok=False)

    def test_custom_block_mirror_refuses_external_overwrite(self):
        self.run_policy('begin-controls',self.control_input([],['custom.example']));self.run_policy('finish')
        config=self.root/'etc/config/adblock-fast';config.write_text(config.read_text().replace('custom.example','external-edit.example'))
        before=config.read_bytes();self.run_policy('validate',ok=False);self.run_policy('restore',ok=False)
        self.assertEqual(config.read_bytes(),before)

    def test_removing_last_custom_rules_can_rollback_after_mirrors_are_removed(self):
        self.run_policy('begin-controls',self.control_input(['ads.example'],['custom.example']));self.run_policy('finish')
        self.run_policy('begin-controls',self.control_input([],[]))
        self.assertFalse((self.root/'etc/adzero/allow-state.json').exists())
        self.assertFalse((self.root/'etc/adzero/block-state.json').exists())
        self.run_policy('rollback');self.run_policy('validate');self.run_policy('finish')
        self.assertEqual(self.status()['allowed'],['ads.example']);self.assertEqual(self.status()['blocked'],['custom.example'])
