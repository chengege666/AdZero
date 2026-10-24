"""Production ucode transformations and transactional file/UCI paths.

Requires the pinned OpenWrt runtime; service restart and inventory are fixtures.
Real Mihomo DNS behavior is checked separately by scripts/check_dns_core.py.
"""
import base64
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
import shutil

ROOT = Path(__file__).resolve().parents[1]
UCODE = shlex.split(os.environ.get("ADZERO_UCODE", ""))


@unittest.skipUnless(UCODE, "set ADZERO_UCODE to a real OpenWrt ucode runtime")
class TransformTest(unittest.TestCase):
    def transform(self, operation, *args, success=True):
        result = subprocess.run(UCODE + [str(ROOT / "scripts/adapter_transform.uc")],
                                input=json.dumps({"operation": operation, "arguments": args}),
                                text=True, capture_output=True)
        if not success:
            self.assertNotEqual(result.returncode, 0)
            return
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_export_keeps_allow_exceptions_out_and_normalizes(self):
        self.assertEqual(self.transform("domains", "server=/ADS.example/\nserver=/allowed.example/#\nserver=/ads.example/\n", "dnsmasq.servers"), ["ads.example"])
        self.transform("domains", "server=/example.com/\nserver=/safe.example.com/#\n", "dnsmasq.servers", success=False)
        self.transform("domains", "server=/bad;command.example/\n", "dnsmasq.servers", success=False)
        self.transform("domains", "#empty\n", "smartdns.domainset", success=False)

    def test_export_all_safe_backend_formats(self):
        for mode, raw in (("dnsmasq.addnhosts", "127.0.0.1 ads.example\n:: ads.example\n"),
                          ("smartdns.domainset", "ads.example\n"),
                          ("unbound.adb_list", 'local-zone: "ads.example." always_nxdomain\n')):
            self.assertEqual(self.transform("domains", raw, mode), ["ads.example"])

    def test_dae_preserves_upstreams_and_injects_before_existing_request_rules(self):
        raw = 'upstream { alidns: "udp://223.5.5.5:53" }\nrouting { request { qname(example.com) -> alidns\nfallback: alidns } response { fallback: accept } }'
        result = self.transform("dae_dns", raw)
        self.assertIn('qname(ext:"adzero-geosite.dat:adzero") -> reject', result)
        self.assertEqual(self.transform("strip_block", result).replace("{\n", "{"), raw)
        self.assertEqual(self.transform("dae_dns", result).count("ADZERO MANAGED BEGIN"), 1)
        self.assertEqual(self.transform("dae_dns", result), result)
        self.transform("dae_dns", "routing { response { fallback: accept } }", success=False)

    def test_mihomo_keeps_user_fields_and_reverses_own_entries(self):
        original = {"dns": {"nameserver-policy": {"+.existing.test": ["1.1.1.1"]}, "fake-ip-filter": ["+.lan"]}, "rules": ["MATCH,DIRECT"], "secret": "private"}
        result = self.transform("mihomo", original, "/tmp/adzero.txt", False)
        self.assertEqual(result["dns"]["fake-ip-filter"], ["rule-set:adzero-dns", "+.lan"])
        self.assertEqual(result["secret"], "private")
        removed = self.transform("mihomo", result, "/tmp/adzero.txt", True)
        self.assertEqual(removed["dns"], original["dns"])
        self.assertEqual(removed["rules"], original["rules"])
        self.transform("mihomo", {"dns": {"fake-ip-filter-mode": "whitelist"}}, "/tmp/adzero.txt", False, success=False)


@unittest.skipUnless(UCODE, "set ADZERO_UCODE to a real OpenWrt ucode runtime")
class AdapterTransactionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="adzero-adapter-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write("etc/config/adblock-fast", "config adblock-fast 'config'\n option dns 'dnsmasq.servers'\n")
        self.write("var/run/adblock-fast/dnsmasq.servers", "server=/ads.example/\nserver=/track.example/\n")
        self.inventory = self.root / "inventory.json"
        self.env = {**os.environ, "ADZERO_ADAPTER_ROOT": str(self.root), "ADZERO_ADAPTER_INVENTORY": str(self.inventory), "ADZERO_SERVICE_TIMEOUT": shutil.which('timeout') or '/usr/bin/timeout'}
        self.select("passwall")

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target

    def select(self, *plugins):
        self.inventory.write_text(json.dumps({"plugins": [{"id": p, "installed": True, "enabled": True, "runtime": "running"} for p in plugins]}))
        for plugin in plugins:
            self.write("etc/init.d/" + plugin, '#!/bin/sh\n[ ! -f "' + str(self.root / "fail") + '" ]\n')
        self.write("etc/config/passwall", "config global\n option enabled '1'\n option use_block_list '0'\n")

    def run_adapter(self, action, *args, success=True):
        result = subprocess.run(UCODE + [str(ROOT / "luci-app-adzero/root/usr/libexec/adzero/adapter.uc"), "--", action, *args], env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def test_passwall_apply_repeat_remove_preserves_original_and_flags(self):
        path = self.write("etc/passwall/rules/block_host", "user.example\n")
        self.run_adapter("apply")
        self.run_adapter("apply")
        self.assertEqual(path.read_text().count("ADZERO MANAGED BEGIN"), 1)
        self.assertIn("option use_block_list '1'", (self.root / "etc/config/passwall").read_text())
        status = json.loads(self.run_adapter("status").stdout)
        self.assertEqual((status["plugin"], status["domains"]), ("passwall", 2))
        self.run_adapter("remove")
        self.assertEqual(path.read_text(), "user.example\n")
        self.assertIn("option use_block_list '0'", (self.root / "etc/config/passwall").read_text())

    def test_multiplugin_conflict_and_empty_list_change_nothing(self):
        self.select("nikki", "openclash")
        self.run_adapter("apply", success=False)
        self.assertFalse((self.root / "etc/adzero/adapter.json").exists())

    def test_service_deadline_prerequisite_fails_before_proxy_changes(self):
        self.env['ADZERO_SERVICE_TIMEOUT']=str(self.root/'missing-timeout')
        for plugin in ('openclash','nikki','ssrplus'):
            with self.subTest(plugin=plugin):
                self.select(plugin)
                result=self.run_adapter('apply',success=False)
                self.assertIn('coreutils-timeout',result.stderr)
                self.assertFalse((self.root/'etc/adzero/adapter.json').exists())
                self.assertFalse((self.root/'etc/nikki/run/providers/rule/adzero.txt').exists())

    def test_stopped_nailink_manager_does_not_conflict_with_passwall(self):
        self.select('passwall')
        inventory=json.loads(self.inventory.read_text())
        inventory['plugins'].append({'id':'nailink','installed':True,'enabled':True,'runtime':'stopped','manager_runtime':'running','core_checked':True,'active':False})
        self.inventory.write_text(json.dumps(inventory))
        self.run_adapter('apply')
        self.assertEqual(json.loads(self.run_adapter('status').stdout)['plugin'],'passwall')

    def test_unknown_nailink_core_blocks_before_any_writes(self):
        self.inventory.write_text(json.dumps({'plugins':[],'dns':{'uncertain_proxies':['nailink']}}))
        self.run_adapter('apply',success=False)
        self.assertFalse((self.root/'etc/adzero/adapter.json').exists())

    def test_restoring_stopped_passwall_never_starts_it_even_without_routing(self):
        counter=self.root/'restarts'
        self.write('etc/init.d/passwall','#!/bin/sh\necho restart >> '+shlex.quote(str(counter))+'\n')
        self.run_adapter('apply')
        inventory=json.loads(self.inventory.read_text());inventory['plugins'][0]['runtime']='stopped'
        self.inventory.write_text(json.dumps(inventory))
        self.run_adapter('remove')
        self.assertEqual(counter.read_text().splitlines(),['restart'])

    def test_disabled_non_procd_passwall_is_not_restarted_on_restore(self):
        counter=self.root/'restarts'
        self.write('etc/init.d/passwall','#!/bin/sh\necho restart >> '+shlex.quote(str(counter))+'\n')
        self.run_adapter('apply')
        inventory=json.loads(self.inventory.read_text());inventory['plugins'][0].update(runtime='unknown',enabled=False)
        self.inventory.write_text(json.dumps(inventory))
        self.run_adapter('remove')
        self.assertEqual(counter.read_text().splitlines(),['restart'])

    def test_passwall_restart_failure_retains_recovery_when_restart_stays_broken(self):
        path = self.write("etc/passwall/rules/block_host", "user.example\n")
        self.write("fail", "fail")
        self.run_adapter("apply", success=False)
        self.assertEqual(path.read_text(), "user.example\n")
        self.assertTrue((self.root / "etc/adzero/adapter.json").exists())
        (self.root / "fail").unlink()
        self.run_adapter("remove")

    def test_passwall_external_edits_survive_disable(self):
        path = self.write("etc/passwall/rules/block_host", "user.example\n")
        self.run_adapter("apply")
        path.write_text(path.read_text() + "new-user.example\n")
        self.run_adapter("remove")
        self.assertIn("new-user.example", path.read_text())
        self.assertNotIn("ads.example", path.read_text())

    def test_update_failure_rolls_back_to_last_good_rules(self):
        path = self.write("etc/passwall/rules/block_host", "user.example\n")
        self.run_adapter("apply")
        previous = path.read_text()
        self.write("var/run/adblock-fast/dnsmasq.servers", "server=/new-ads.example/\n")
        self.write("fail-once", "fail")
        self.write("etc/init.d/passwall", '#!/bin/sh\nif [ -f "' + str(self.root / "fail-once") + '" ]; then rm "' + str(self.root / "fail-once") + '"; exit 1; fi\nexit 0\n')
        self.run_adapter("apply", success=False)
        self.assertEqual(path.read_text(), previous)
        self.assertEqual(json.loads(self.run_adapter("status").stdout)["stage"], "configured_unverified")

    def large_rules(self, prefix='ads'):
        return ''.join(f'server=/{prefix}{i}.example/\n' for i in range(5000))

    def test_large_provider_journal_stays_small_and_rollback_preserves_bytes(self):
        path=self.write('etc/passwall/rules/block_host','user.example\n')
        self.write('var/run/adblock-fast/dnsmasq.servers',self.large_rules())
        self.run_adapter('apply');previous=path.read_text()
        journal=self.root/'etc/adzero/adapter.json'
        self.assertLess(journal.stat().st_size,16384)
        self.assertIsInstance(json.loads(journal.read_text())['files'][0]['after'],dict)
        self.write('var/run/adblock-fast/dnsmasq.servers',self.large_rules('new'))
        once=self.write('fail-once','1')
        self.write('etc/init.d/passwall',f'#!/bin/sh\nif [ -f {shlex.quote(str(once))} ]; then rm {shlex.quote(str(once))}; exit 1; fi\nexit 0\n')
        self.run_adapter('apply',success=False)
        self.assertEqual(path.read_text(),previous)
        self.run_adapter('remove');self.assertEqual(path.read_text(),'user.example\n')
        self.assertFalse((self.root/'etc/adzero/providers').exists())

    def test_large_provider_does_not_erase_later_manual_block_entries(self):
        path=self.write('etc/passwall/rules/block_host','user.example\n')
        self.write('var/run/adblock-fast/dnsmasq.servers',self.large_rules())
        self.run_adapter('apply');path.write_text(path.read_text()+'manual.example\n')
        self.run_adapter('remove')
        self.assertEqual(path.read_text(),'user.example\nmanual.example\n')

    def test_modified_original_snapshot_refuses_unsafe_restoration(self):
        original=''.join(f'user{i}.example\n' for i in range(5000))
        path=self.write('etc/passwall/rules/block_host',original)
        self.run_adapter('apply');adapted=path.read_text()
        journal=self.root/'etc/adzero/adapter.json'
        before=json.loads(journal.read_text())['files'][0]['before']
        (self.root/'etc/adzero/providers'/before['sha256']).write_text('changed')
        self.run_adapter('remove',success=False)
        self.assertEqual(path.read_text(),adapted);self.assertTrue(journal.exists())

    @unittest.skipUnless(shutil.which("yq"), "real yq required")
    def test_nikki_native_mixin_merge_and_flag_restore(self):
        self.select("nikki")
        self.write("etc/config/nikki", "config nikki 'config'\n option enabled '1'\n option core_only '0'\nconfig mixin 'mixin'\n option mixin_file_content '0'\n")
        path = self.write("etc/nikki/mixin.yaml", "# user comment\n")
        base = self.write("etc/nikki/base.yaml", 'dns:\n  enable: true\n  enhanced-mode: fake-ip\n  fake-ip-filter: ["+.lan"]\nrules: ["MATCH,DIRECT"]\n')
        run = self.write("etc/nikki/run/config.yaml", base.read_text())
        script = '#!/bin/sh\nyq -o=json eval-all \'. as $item ireduce ({}; . * $item ) | .rules = .nikki-rules + .rules | del(.nikki-rules)\' "' + str(base) + '" "' + str(path) + '" > "' + str(run) + '"\n'
        self.write("etc/init.d/nikki", script)
        self.run_adapter("apply")
        adapted = json.loads(run.read_text())
        self.assertEqual(adapted["rules"], ["RULE-SET,adzero-dns,REJECT", "MATCH,DIRECT"])
        self.assertIn("+.lan", adapted["dns"]["fake-ip-filter"])
        self.assertIn("rule-set:adzero-dns", adapted["dns"]["fake-ip-filter"])
        provider = self.root / "etc/nikki/run/providers/rule/adzero.txt"
        self.assertIn("+.ads.example", provider.read_text())
        journal=self.root/'etc/adzero/adapter.json';value=json.loads(journal.read_text())
        entry=next(f for f in value['files'] if f['kind']=='owned')
        self.assertIsInstance(entry['after'],dict)
        # Existing installations retain the old base64 form until rewritten.
        entry['after']=base64.b64encode(provider.read_bytes()).decode()
        journal.write_text(json.dumps(value));journal.chmod(0o600)
        self.run_adapter("apply")
        self.run_adapter("remove")
        self.assertEqual(path.read_text(), "# user comment\n")
        self.assertFalse(provider.exists())
        self.assertIn("option mixin_file_content '0'", (self.root / "etc/config/nikki").read_text())

    @unittest.skipUnless(shutil.which("yq"), "real yq required")
    def test_nikki_disabled_existing_mixin_is_not_activated(self):
        self.select("nikki")
        self.write("etc/config/nikki", "config nikki 'config'\n option enabled '1'\nconfig mixin 'mixin'\n option mixin_file_content '0'\n")
        path = self.write("etc/nikki/mixin.yaml", 'secret: user-setting\n')
        self.run_adapter("apply", success=False)
        self.assertEqual(path.read_text(), 'secret: user-setting\n')
        self.assertFalse((self.root / "etc/nikki/run/providers/rule/adzero.txt").exists())

    @unittest.skipUnless(shutil.which("ruby"), "real Ruby YAML parser required")
    def test_openclash_hook_yaml_anchors_preserved_and_reverted(self):
        self.select("openclash")
        self.write("etc/config/openclash", "config openclash 'config'\n option config_path '/etc/openclash/config/config.yaml'\n")
        custom = self.write("etc/openclash/custom/openclash_custom_overwrite.sh", "#!/bin/sh\n# custom settings\nexit 0\n")
        base = self.write("etc/openclash/source.yaml", 'dns:\n  enable: true\n  enhanced-mode: fake-ip\n  fake-ip-filter: ["+.lan"]\nproxies: &proxies []\nother-proxies: *proxies\nrules: ["MATCH,DIRECT"]\n')
        run = self.root / "etc/openclash/config.yaml"
        core = self.write("etc/openclash/core/clash_meta", "#!/bin/sh\nexit 0\n")
        core.chmod(0o755)  # core-check fixture; real core behavior has a separate test
        adapter = UCODE + [str(ROOT / "luci-app-adzero/root/usr/libexec/adzero/adapter.uc"), "--", "hook-openclash", "/etc/openclash/config.yaml"]
        script = '#!/bin/sh\ncp ' + shlex.quote(str(base)) + ' ' + shlex.quote(str(run)) + '\nif grep -q "ADZERO MANAGED BEGIN" ' + shlex.quote(str(custom)) + '; then\n' + shlex.join(adapter) + '\nfi\n'
        self.write("etc/init.d/openclash", script)
        self.run_adapter("apply")
        adapted = json.loads(run.read_text())
        self.assertEqual(adapted["other-proxies"], [])
        self.assertEqual(adapted["dns"]["nameserver-policy"]["rule-set:adzero-dns"], ["rcode://name_error"])
        self.assertLess(custom.read_text().index("ADZERO MANAGED BEGIN"), custom.read_text().index("exit 0"))
        self.run_adapter("apply")
        self.run_adapter("remove")
        self.assertEqual(custom.read_text(), "#!/bin/sh\n# custom settings\nexit 0\n")
        self.assertEqual(base.read_text(), run.read_text())
        self.assertFalse((self.root / "etc/openclash/rule_provider/adzero.txt").exists())
