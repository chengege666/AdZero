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
        return json.loads(result.stdout)

    def test_success_with_recommended_warnings_is_ready(self):
        result = self.check()
        self.assertEqual((result['state'], result['domains'], result['warnings']), ('ready', 2, 1))

    def test_failed_status_with_existing_rules_is_rejected(self):
        self.data['status'] = 'statusFail'
        self.check(success=False)

    def test_real_backend_errors_reject_success_and_do_not_leak_info(self):
        self.data['errors'] = [{"code":"errorDownloadingList", "info":"https://private.test/list?token=secret"}]
        result = self.check(success=False)
        self.assertEqual(result['download_errors'], 1)
        self.assertNotIn('secret', json.dumps(result))
        self.check('download-error')

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
