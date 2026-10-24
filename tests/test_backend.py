"""Read-only backend readiness checks with real ucode/UCI and service fixtures."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UCODE = shlex.split(os.environ.get("ADZERO_UCODE", ""))


@unittest.skipUnless(UCODE, "requires real OpenWrt ucode")
class BackendStateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="adzero-backend-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'etc/config/adblock-fast'
        self.config.parent.mkdir(parents=True)
        self.config.write_text("config adblock-fast 'config'\n option dns 'dnsmasq.servers'\n option enabled '1'\n")
        self.output = self.root / 'var/run/adblock-fast/dnsmasq.servers'
        self.output.parent.mkdir(parents=True)
        self.output.write_text('server=/ads.example/\nserver=/tracker.example/\n')
        self.fixture = self.root / 'service.json'
        self.data = {"status":"statusSuccess", "errors":[], "warnings":[{"code":"warningMissingRecommendedPackages"}],
                     "entries":2, "dns":"dnsmasq.servers", "force_dns_active":False,
                     "outputFile":"/var/run/adblock-fast/dnsmasq.servers"}
        self.service = {"adblock-fast":{"data":self.data}, "dnsmasq":{"instances":{"cfg1":{"running":True}}}}

    def check(self, action='ready', success=True):
        self.fixture.write_text(json.dumps(self.service))
        before = self.config.read_bytes()
        result = subprocess.run(UCODE + [str(ROOT / 'luci-app-adzero/root/usr/libexec/adzero/backend.uc'), '--', action],
                                env={**os.environ, "ADZERO_BACKEND_ROOT":str(self.root),
                                     "ADZERO_BACKEND_SERVICE_FIXTURE":str(self.fixture)},
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        self.assertEqual(self.config.read_bytes(), before)
        return result.stdout.strip() if action=='failure' else json.loads(result.stdout)

    def test_success_with_recommended_warnings_is_ready(self):
        result = self.check()
        self.assertEqual((result['state'], result['domains'], result['warnings']), ('ready', 2, 1))
        self.assertTrue(result['rules_checked'])

    def test_inspect_reports_live_metadata_separately_from_full_verification(self):
        result = self.check('inspect')
        self.assertEqual((result['state'], result['domains']), ('ready', 2))
        self.assertFalse(result['rules_checked'])
        # Runtime status must still reject stale success and resolver failures.
        self.output.unlink()
        self.check('inspect', success=False)

    def test_inspect_keeps_runtime_error_guards(self):
        for key, value in (('status','statusFail'), ('force_dns_active',True), ('entries',500001), ('outputFile','/wrong/file')):
            with self.subTest(key=key):
                old=self.data[key];self.data[key]=value
                self.check('inspect', success=False)
                self.data[key]=old

    def test_inspect_rejects_resolver_down(self):
        self.service['dnsmasq']['instances']['cfg1']['running']=False
        self.check('inspect', success=False)

    def test_validated_cache_follows_content_not_file_time(self):
        self.check();cache=self.root/'tmp/adzero-rules-cache'
        proof=json.loads((cache/'proof.json').read_text())
        stamp=self.output.stat().st_mtime_ns
        self.output.write_text('server=/other.example/\nserver=/newer.example/\n')
        os.utime(self.output,ns=(stamp,stamp))
        self.assertEqual(self.check()['domains'],2)
        self.assertNotEqual(json.loads((cache/'proof.json').read_text())['source'],proof['source'])
        self.output.write_text('<html>not rules</html>\n')
        self.check(success=False)

    def test_corrupt_or_unavailable_cache_falls_back_to_strict_import(self):
        self.check();cache=self.root/'tmp/adzero-rules-cache'
        proof=json.loads((cache/'proof.json').read_text())
        data=cache/(proof['source']+'-0.json')
        data.write_text('["wrong.example"]')
        self.assertEqual(self.check()['domains'],2)
        (cache/'proof.json').write_text('{bad json')
        self.assertEqual(self.check()['domains'],2)
        cache.chmod(0o777)
        self.assertEqual(self.check()['domains'],2)

    def test_cache_is_bound_to_resolver_format(self):
        self.check()
        self.config.write_text(self.config.read_text().replace('dnsmasq.servers','smartdns.domainset'))
        self.data['dns']='smartdns.domainset';self.data['outputFile']='/var/run/adblock-fast/smartdns.domainset'
        other=self.output.with_name('smartdns.domainset');other.write_bytes(self.output.read_bytes())
        self.check(success=False)

    def test_failed_status_with_existing_rules_is_rejected(self):
        self.data['status'] = 'statusFail'
        self.check(success=False)

    def test_real_backend_errors_reject_success_and_do_not_leak_info(self):
        self.data['errors'] = [{"code":"errorDownloadingList", "info":"https://private.test/list?token=secret"}]
        result = self.check(success=False)
        self.assertEqual(result['download_errors'], 1)
        self.assertNotIn('secret', json.dumps(result))
        self.check('download-error')

    def test_only_known_error_codes_are_public(self):
        self.data['errors']=[{'code':'errorTooLittleRam','info':'https://private.example/?token=secret'},
                             {'code':'private-token-secret','info':'password'},
                             {'code':'errorTooLittleRam','info':'duplicate'}]
        result=self.check(success=False)
        self.assertEqual(result['error_codes'],['errorTooLittleRam'])
        self.assertNotIn('secret',json.dumps(result))
        self.assertEqual(self.check('failure'),'backend_memory')

    def test_failure_tokens_distinguish_processing_dns_files_and_downloads(self):
        for code,expected in [('errorParsingList','backend_processing'),('errorSorting','backend_processing'),
                              ('errorDNSReload','backend_dns'),('errorFailDNSReload','backend_dns'),
                              ('errorOutputFileCreate','backend_files'),('errorDownloadingList','source_download')]:
            with self.subTest(code=code):
                self.data['errors']=[{'code':code,'info':'private'}]
                self.assertEqual(self.check('failure'),expected)

    def test_domain_capacity_has_a_specific_readiness_and_failure_reason(self):
        self.data['entries']=500001
        self.assertEqual(self.check(success=False)['reason'],'domain_limit')
        self.assertEqual(self.check('inspect',success=False)['reason'],'domain_limit')
        self.assertEqual(self.check('failure'),'source_limit')

    def test_oversized_output_has_a_specific_failure_reason(self):
        with self.output.open('wb') as f:f.truncate(25000001)
        self.assertEqual(self.check(success=False)['reason'],'oversized_output')
        self.assertEqual(self.check('failure'),'source_limit')

    def test_resolver_down_and_unknown_failures_are_not_reported_as_capacity(self):
        self.service['dnsmasq']['instances']['cfg1']['running']=False
        self.assertEqual(self.check('failure'),'backend_dns')
        self.service['dnsmasq']['instances']['cfg1']['running']=True
        self.data['errors']=[{'code':'unknown-private-code','info':'token'}]
        self.assertEqual(self.check('failure'),'backend')

    def test_processed_rule_validation_is_distinguished_from_lifecycle_failure(self):
        self.output.write_text('server=/ads.example/\n<html>private-token</html>\n')
        result=self.check(success=False)
        self.assertEqual(result['reason'],'processed_rules_invalid')
        self.assertNotIn('private-token',json.dumps(result))
        self.assertEqual(self.check('failure'),'backend_processing')

    def test_missing_or_malformed_output_rejects_success(self):
        for raw in ('', '<html>not a rule list</html>\n'):
            self.output.write_text(raw)
            self.check(success=False)

    def test_wrong_output_mode_path_or_force_dns_are_not_accepted(self):
        for key, value in (('dns','dnsmasq.nftset'), ('outputFile','/private/file'), ('force_dns_active',True), ('entries',0)):
            with self.subTest(key=key):
                old = self.data[key]
                self.data[key] = value
                self.check(success=False)
                self.data[key] = old

    def test_stopped_is_independent_of_enabled_flag_and_keeps_cache(self):
        self.output.rename(self.output.with_suffix('.cache'))
        del self.service['adblock-fast']
        self.assertEqual(self.check('stopped')['state'], 'stopped')
        self.assertTrue(self.output.with_suffix('.cache').exists())

    def test_stale_success_is_neither_ready_nor_stopped(self):
        self.output.unlink()
        self.check(success=False)
        self.check('stopped', success=False)

    def test_resolver_must_be_running(self):
        self.service['dnsmasq']['instances']['cfg1']['running'] = False
        self.check(success=False)
        self.output.unlink()
        del self.service['adblock-fast']
        self.check('stopped', success=False)
