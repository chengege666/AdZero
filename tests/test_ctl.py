#!/usr/bin/env python3
"""Local-only mock tests. They never call real UCI, init services or the network."""
import json
import os
import subprocess
import shlex
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CTL = ROOT / "luci-app-adzero/root/usr/libexec/adzero/ctl"

MOCK_UCI = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
f = Path(os.environ["MOCK_CONFIG"])
data = json.loads(f.read_text())
args = sys.argv[1:]
if args and args[0] == "-q": args = args[1:]
if not args: sys.exit(2)
cmd = args[0]
if cmd == "get":
    v = data.get(args[1])
    if v is None: sys.exit(1)
    print(v)
elif cmd == "set":
    key, val = args[1].split("=", 1)
    if key == os.environ.get("MOCK_UCI_FAIL_KEY"): sys.exit(17)
    data[key] = val
    f.write_text(json.dumps(data))
elif cmd == "delete":
    key = args[1]
    data = {k: v for k, v in data.items() if k != key and not k.startswith(key + '.')}
    f.write_text(json.dumps(data))
elif cmd == "show":
    if os.environ.get("MOCK_UCI_FAIL_SHOW") == '1': sys.exit(17)
    prefix = args[1]
    for key, val in data.items():
        if key == prefix or key.startswith(prefix + '.'):
            print(key + '=' + (val if '.' not in key[len('adblock-fast.'):] else repr(val)))
elif cmd in ("commit", "revert"):
    pass
else:
    sys.exit(2)
'''
MOCK_BACKEND = r'''#!/bin/sh
printf '%s\n' "$1" >> "$MOCK_LOG"
if [ "$1" = restart ] && [ -f "$MOCK_FAIL_ONCE" ]; then
    rm -f "$MOCK_FAIL_ONCE"
    echo "simulated one-time restart failure" >&2
    exit 17
fi
if [ "$1" = restart ] && [ -f "$MOCK_FAIL" ]; then
    echo "simulated persistent restart failure" >&2
    exit 17
fi
exit 0
'''


class AdZeroTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.conf = base / "config.json"
        self.conf.write_text(json.dumps({
            "adzero.main.enabled": "0",
            "adblock-fast.config.enabled": "0",
            "adblock-fast.config.force_dns": "1",
            "adblock-fast.config.download_allow_insecure": "1",
            "adblock-fast.config.dns": "dnsmasq.servers",
            "adblock-fast.config": "adblock-fast",
        }))
        self.log = base / "backend.log"
        self.backend_fail = base / "backend_fail"
        self.fail_once = base / "backend_fail_once"
        self.state = base / "adzero_state"
        self.lock = base / "adzero_lock"
        self.nailink = base / "nailink"
        self.daed_config = base / "daed_config"
        self.daed_version = base / "daed_version"
        self.daed_check = base / "daed_check"
        self.uci = base / "mock_uci"
        self.backend = base / "mock_adblock_fast"
        self.uci.write_text(MOCK_UCI)
        self.backend.write_text(MOCK_BACKEND)
        self.uci.chmod(0o700)
        self.backend.chmod(0o700)
        self.adapter = base / "mock_adapter"
        self.adapter.write_text('#!/bin/sh\nif [ "$1" = status ]; then echo \'{"plugin":"none","stage":"inactive","domains":0}\'; fi\nexit 0\n')
        self.adapter.chmod(0o700)
        self.env = {
            **os.environ,
            "ADZERO_UCI": str(self.uci),
            "ADZERO_ADAPTER": str(self.adapter),
            "ADZERO_BACKEND_INIT": str(self.backend),
            "ADZERO_STATE_DIR": str(self.state),
            "ADZERO_LOCK_DIR": str(self.lock),
            "ADZERO_NAILINK_CONFIG": str(self.nailink),
            "ADZERO_DAED_CONFIG": str(self.daed_config),
            "ADZERO_DAED_VERSION": str(self.daed_version),
            "ADZERO_DAED_CHECK": str(self.daed_check),
            "ADZERO_PIDOF": "/bin/false",
            "ADZERO_PROBE": "/bin/false",
            "MOCK_CONFIG": str(self.conf),
            "MOCK_LOG": str(self.log),
            "MOCK_FAIL": str(self.backend_fail),
            "MOCK_FAIL_ONCE": str(self.fail_once),
        }

    def run_ctl(self, command, success=True):
        result = subprocess.run(
            shlex.split(os.environ.get("ADZERO_TEST_SHELL", "/bin/sh")) + [str(CTL), command],
            text=True, capture_output=True, env=self.env, timeout=8
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def config(self):
        return json.loads(self.conf.read_text())

    def status(self):
        return json.loads(self.run_ctl("status").stdout)

    def test_initial_status(self):
        self.assertEqual(self.status()["state"], "disabled")
        self.assertFalse(self.status()["managed"])

    def test_enable_disable_and_idempotency(self):
        self.run_ctl("enable")
        self.assertEqual(self.status()["state"], "configured_unverified")
        self.assertTrue((self.state / "managed").exists())
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "1")
        self.assertEqual(self.config()["adzero.main.enabled"], "1")
        before = self.log.read_text()
        self.run_ctl("enable")
        self.assertEqual(self.log.read_text(), before)
        self.run_ctl("disable")
        self.assertEqual(self.status()["state"], "disabled")
        self.assertFalse((self.state / "managed").exists())
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "0")

    def test_external_backend_must_not_be_taken_over(self):
        config = self.config()
        config["adblock-fast.config.enabled"] = "1"
        self.conf.write_text(json.dumps(config))
        self.assertEqual(self.status()["state"], "external_owner")
        self.run_ctl("enable", success=False)
        self.run_ctl("disable")
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "1")
        self.assertFalse(self.log.exists())

    def test_failed_start_restores_backend(self):
        self.fail_once.touch()
        result = self.run_ctl("enable", success=False)
        self.assertIn("wildcard/light-onlydomains.txt", result.stderr)
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "0")
        self.assertEqual(self.config()["adblock-fast.config.force_dns"], "1")
        self.assertEqual(self.config()["adzero.main.enabled"], "0")
        self.assertFalse((self.state / "managed").exists())

    def test_failed_backend_does_not_disclose_user_subscription(self):
        config = self.config()
        secret_url = "https://user.example/list?token=private-value"
        config.update({"adblock-fast.userlist": "file_url", "adblock-fast.userlist.url": secret_url})
        self.conf.write_text(json.dumps(config))
        self.fail_once.touch()
        result = self.run_ctl("enable", success=False)
        self.assertNotIn(secret_url, result.stderr)
        self.assertNotIn("默认规则", result.stderr)
        self.assertEqual(self.config(), config)

    def test_refresh_only_managed(self):
        self.run_ctl("refresh", success=False)
        self.run_ctl("enable")
        self.run_ctl("refresh")
        self.assertIn("dl\n", self.log.read_text())

    def test_unknown_dns_mode_fails_closed(self):
        config = self.config()
        config["adblock-fast.config.dns"] = "custom.unknown"
        self.conf.write_text(json.dumps(config))
        self.run_ctl("enable", success=False)
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "0")

    def test_nailink_detection_is_not_dns_verification(self):
        self.nailink.touch()
        status = self.status()
        self.assertTrue(status["nailink_detected"])
        self.assertEqual(status["state"], "disabled")
        self.assertEqual(status["resolver"], "dnsmasq.servers")

    def test_concurrent_mutation_guard(self):
        self.lock.mkdir()
        self.run_ctl("enable", success=False)
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "0")

    def test_detect_adguardhome_conflict(self):
        mock_pidof = Path(self.tmp.name) / "mock_pidof"
        mock_pidof.write_text("#!/bin/sh\nexit 0\n")
        mock_pidof.chmod(0o700)
        self.env["ADZERO_PIDOF"] = str(mock_pidof)
        self.assertTrue(self.status()["adguardhome_running"])
        self.run_ctl("enable", success=False)
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "0")

    def test_owned_restart_failure_keeps_existing_ownership(self):
        self.state.mkdir()
        (self.state / "managed").touch()
        config = self.config()
        config["adblock-fast.config.enabled"] = "1"
        self.conf.write_text(json.dumps(config))
        self.backend_fail.touch()
        self.run_ctl("enable", success=False)
        self.assertTrue((self.state / "managed").exists())
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "1")

    def test_failed_disable_restores_owned_backend(self):
        self.run_ctl("enable")
        self.backend_fail.touch()
        self.run_ctl("disable", success=False)
        self.assertTrue((self.state / "managed").exists())
        self.assertEqual(self.config()["adzero.main.enabled"], "1")
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "1")

    def test_stale_marker_can_be_cleared_without_external_side_effect(self):
        self.state.mkdir()
        (self.state / "managed").touch()
        (self.state / "force_dns.previous").write_text("1\n")
        (self.state / "download_allow_insecure.previous").write_text("1\n")
        self.run_ctl("disable")
        self.assertFalse((self.state / "managed").exists())
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "0")

    def test_missing_backend_never_sets_enabled(self):
        self.env["ADZERO_BACKEND_INIT"] = str(Path(self.tmp.name) / "missing_service")
        self.assertEqual(self.status()["state"], "unavailable")
        self.run_ctl("enable", success=False)
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "0")



    def test_force_dns_one_click_temporarily_disables_and_restores(self):
        self.assertEqual(self.config()["adblock-fast.config.force_dns"], "1")
        self.run_ctl("enable")
        self.assertEqual(self.config()["adblock-fast.config.force_dns"], "0")
        self.assertEqual((self.state / "force_dns.previous").read_text(), "1\n")
        self.assertEqual(self.status()["force_dns"], "off")
        self.run_ctl("disable")
        self.assertEqual(self.config()["adblock-fast.config.force_dns"], "1")

    def test_force_dns_unset_uses_default_and_restores_absence(self):
        config = self.config()
        del config["adblock-fast.config.force_dns"]
        self.conf.write_text(json.dumps(config))
        self.assertEqual(self.status()["force_dns"], "default_on")
        self.run_ctl("enable")
        self.assertEqual(self.config()["adblock-fast.config.force_dns"], "0")
        self.run_ctl("disable")
        self.assertNotIn("adblock-fast.config.force_dns", self.config())

    def test_force_dns_previously_disabled_remains_disabled(self):
        config = self.config()
        config["adblock-fast.config.force_dns"] = "0"
        self.conf.write_text(json.dumps(config))
        self.run_ctl("enable")
        self.run_ctl("disable")
        self.assertEqual(self.config()["adblock-fast.config.force_dns"], "0")

    def test_firewall_set_modes_are_blocked_without_changes(self):
        for mode in ("dnsmasq.nftset", "dnsmasq.ipset",
                     "smartdns.ipset", "smartdns.nftset", "dnsmasq.conf"):
            with self.subTest(mode=mode):
                config = self.config()
                config["adblock-fast.config.dns"] = mode
                self.conf.write_text(json.dumps(config))
                status = self.status()
                self.assertFalse(status["dns_mode_safe"])
                self.assertTrue(status["dns_review_needed"])
                self.run_ctl("enable", success=False)
                self.assertEqual(self.config()["adblock-fast.config.force_dns"], "1")
                self.assertEqual(self.config()["adblock-fast.config.enabled"], "0")
                self.assertFalse((self.state / "managed").exists())

    def test_safe_resolver_modes_are_reported(self):
        for mode in ("dnsmasq.servers", "dnsmasq.addnhosts",
                     "smartdns.domainset", "unbound.adb_list"):
            with self.subTest(mode=mode):
                config = self.config()
                config["adblock-fast.config.dns"] = mode
                self.conf.write_text(json.dumps(config))
                self.assertTrue(self.status()["dns_mode_safe"])

    def test_persistent_start_failure_leaves_recovery_marker(self):
        self.backend_fail.touch()
        message = self.run_ctl("enable", success=False).stderr
        self.assertIn("回滚未确认", message)
        self.assertTrue((self.state / "managed").exists())
        self.assertTrue((self.state / "force_dns.previous").exists())
        self.assertEqual(self.config()["adblock-fast.config.force_dns"], "1")
        self.assertEqual(self.status()["state"], "inconsistent")
        self.backend_fail.unlink()
        self.run_ctl("disable")
        self.assertFalse((self.state / "managed").exists())
        self.assertEqual(self.status()["state"], "disabled")

    def test_manual_force_dns_edit_is_not_overwritten_on_disable(self):
        self.run_ctl("enable")
        config = self.config()
        config["adblock-fast.config.force_dns"] = "1"
        self.conf.write_text(json.dumps(config))
        self.assertEqual(self.status()["state"], "inconsistent")
        self.run_ctl("disable")
        self.assertEqual(self.config()["adblock-fast.config.force_dns"], "1")

    def test_disable_accepts_mode_changed_by_external_configuration(self):
        self.run_ctl("enable")
        config = self.config()
        config["adblock-fast.config.dns"] = "dnsmasq.nftset"
        self.conf.write_text(json.dumps(config))
        self.run_ctl("disable")
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "0")

    def test_missing_force_dns_backup_fails_closed(self):
        self.run_ctl("enable")
        (self.state / "force_dns.previous").unlink()
        self.run_ctl("disable", success=False)
        self.assertTrue((self.state / "managed").exists())
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "1")

    def test_invalid_force_dns_value_rejected(self):
        config = self.config()
        config["adblock-fast.config.force_dns"] = "not-a-boolean"
        self.conf.write_text(json.dumps(config))
        self.run_ctl("enable", success=False)
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "0")

    def test_nailink_real_daed_paths_detected(self):
        self.daed_version.write_text("0.6.27\n")
        config = self.config()
        config["daed.main.enabled"] = "1"
        self.conf.write_text(json.dumps(config))
        status = self.status()
        self.assertTrue(status["nailink_detected"])
        self.assertTrue(status["nailink_enabled"])
        self.assertFalse(status["nailink_running"])
        self.assertTrue(status["dns_review_needed"])
        self.assertFalse(status["client_dns_verified"])

    def test_nailink_runtime_detection_is_not_configuration_only(self):
        self.daed_config.touch()
        self.daed_check.write_text("#!/bin/sh\nexit 0\n")
        self.daed_check.chmod(0o700)
        mock_pidof = Path(self.tmp.name) / "mock_pidof_daed"
        mock_pidof.write_text("#!/bin/sh\n[ \"$1\" = 'daed' ]\n")
        mock_pidof.chmod(0o700)
        self.env["ADZERO_PIDOF"] = str(mock_pidof)
        status = self.status()
        self.assertTrue(status["nailink_detected"])
        self.assertTrue(status["nailink_running"])
        self.assertFalse(status["adguardhome_running"])

    def test_dnsmasq_port_is_hint_not_verification(self):
        config = self.config()
        config["dhcp.@dnsmasq[0].port"] = "5353"
        self.conf.write_text(json.dumps(config))
        status = self.status()
        self.assertEqual(status["dnsmasq_port_hint"], "nonstandard")
        self.assertTrue(status["dns_review_needed"])
        self.assertFalse(status["client_dns_verified"])

    def test_unmanaged_backend_is_never_mutated_even_when_force_dns_default_on(self):
        config = self.config()
        config["adblock-fast.config.enabled"] = "1"
        self.conf.write_text(json.dumps(config))
        self.run_ctl("disable")
        self.assertEqual(self.config()["adblock-fast.config.force_dns"], "1")
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "1")
        self.assertFalse(self.log.exists())

    def test_refresh_rejects_external_reenable_of_forced_dns(self):
        self.run_ctl("enable")
        config = self.config()
        config["adblock-fast.config.force_dns"] = "1"
        self.conf.write_text(json.dumps(config))
        count_before = self.log.read_text().count("dl\n")
        self.run_ctl("refresh", success=False)
        self.assertEqual(self.log.read_text().count("dl\n"), count_before)

    def test_refresh_rejects_lost_restore_backup(self):
        self.run_ctl("enable")
        (self.state / "force_dns.previous").unlink()
        self.run_ctl("refresh", success=False)
        self.assertNotIn("dl\n", self.log.read_text())

    def test_inconsistent_unowned_state_rejects_enable(self):
        config = self.config()
        config["adzero.main.enabled"] = "1"
        self.conf.write_text(json.dumps(config))
        self.assertEqual(self.status()["state"], "inconsistent")
        self.run_ctl("enable", success=False)
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "0")
        self.assertFalse((self.state / "managed").exists())

    def test_tls_download_strict_during_protection_and_restored(self):
        self.assertEqual(self.status()["tls_download"], "insecure")
        self.run_ctl("enable")
        self.assertEqual(self.status()["tls_download"], "strict")
        self.assertEqual(self.config()["adblock-fast.config.download_allow_insecure"], "0")
        self.assertEqual((self.state / "download_allow_insecure.previous").read_text(), "1\n")
        self.run_ctl("disable")
        self.assertEqual(self.config()["adblock-fast.config.download_allow_insecure"], "1")

    def test_tls_download_unset_restores_absence(self):
        conf = self.config()
        del conf["adblock-fast.config.download_allow_insecure"]
        self.conf.write_text(json.dumps(conf))
        self.assertEqual(self.status()["tls_download"], "default_insecure")
        self.run_ctl("enable")
        self.assertEqual(self.config()["adblock-fast.config.download_allow_insecure"], "0")
        self.run_ctl("disable")
        self.assertNotIn("adblock-fast.config.download_allow_insecure", self.config())

    def test_tls_download_previously_strict_preserved(self):
        conf = self.config()
        conf["adblock-fast.config.download_allow_insecure"] = "0"
        self.conf.write_text(json.dumps(conf))
        self.run_ctl("enable")
        self.run_ctl("disable")
        self.assertEqual(self.config()["adblock-fast.config.download_allow_insecure"], "0")

    def test_tls_download_manual_external_change_does_not_get_overwritten(self):
        self.run_ctl("enable")
        conf = self.config()
        conf["adblock-fast.config.download_allow_insecure"] = "1"
        self.conf.write_text(json.dumps(conf))
        self.assertEqual(self.status()["state"], "inconsistent")
        self.run_ctl("refresh", success=False)
        self.run_ctl("disable")
        self.assertEqual(self.config()["adblock-fast.config.download_allow_insecure"], "1")

    def test_tls_download_invalid_rejected_before_backup_writes(self):
        conf = self.config()
        conf["adblock-fast.config.download_allow_insecure"] = "strange"
        self.conf.write_text(json.dumps(conf))
        self.run_ctl("enable", success=False)
        self.assertFalse(self.state.exists())
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "0")

    def test_orphan_restore_backup_not_silently_overwritten(self):
        self.state.mkdir()
        (self.state / "download_allow_insecure.previous").write_text("1\n")
        self.assertEqual(self.status()["state"], "inconsistent")
        self.run_ctl("enable", success=False)
        self.assertEqual((self.state / "download_allow_insecure.previous").read_text(), "1\n")

    def test_tls_backup_missing_keeps_recovery_marker(self):
        self.run_ctl("enable")
        (self.state / "download_allow_insecure.previous").unlink()
        self.run_ctl("disable", success=False)
        self.assertTrue((self.state / "managed").exists())
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "1")

    def test_reject_insecure_custom_curl_parameters(self):
        for extra in ("--insecure", "--proxy-insecure", "-k", "--retry 2 -k"):
            with self.subTest(extra=extra):
                conf = self.config()
                conf["adblock-fast.config.curl_additional_param"] = extra
                self.conf.write_text(json.dumps(conf))
                self.run_ctl("enable", success=False)
                self.assertEqual(self.config()["adblock-fast.config.enabled"], "0")
                self.assertFalse((self.state / "managed").exists())

    def test_no_log_leak_of_custom_curl_parameters(self):
        secret = "private-value"
        conf = self.config()
        conf["adblock-fast.config.curl_additional_param"] = "--insecure " + secret
        self.conf.write_text(json.dumps(conf))
        result = self.run_ctl("enable", success=False)
        self.assertNotIn(secret, result.stderr)

    def test_reject_rule_refresh_if_insecure_flag_added_later(self):
        self.run_ctl("enable")
        conf = self.config()
        conf["adblock-fast.config.curl_additional_param"] = "--insecure"
        self.conf.write_text(json.dumps(conf))
        self.run_ctl("refresh", success=False)
        self.assertNotIn("dl\n", self.log.read_text())
        self.run_ctl("disable")

    def test_safe_custom_curl_parameters_allowed(self):
        conf = self.config()
        conf["adblock-fast.config.curl_additional_param"] = "--retry 2"
        self.conf.write_text(json.dumps(conf))
        self.run_ctl("enable")
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "1")
        self.run_ctl("disable")

    def test_default_rule_is_created_and_removed_without_touching_disabled_lists(self):
        config = self.config()
        config.update({"adblock-fast.userlist": "file_url", "adblock-fast.userlist.url": "https://example.test/list", "adblock-fast.userlist.enabled": "0"})
        self.conf.write_text(json.dumps(config))
        self.run_ctl("enable")
        self.assertEqual(self.config()["adblock-fast.adzero_default.enabled"], "1")
        self.assertTrue(self.config()["adblock-fast.adzero_default.url"].startswith("https://"))
        self.assertEqual(self.status()["rule_sources"], "configured")
        self.run_ctl("disable")
        self.assertEqual(self.config(), config)

    def test_existing_enabled_rule_is_used_without_default_insertion(self):
        config = self.config()
        config.update({"adblock-fast.@file_url[0]": "file_url", "adblock-fast.@file_url[0].url": "https://example.test/list", "adblock-fast.@file_url[0].enabled": "1"})
        self.conf.write_text(json.dumps(config))
        self.run_ctl("enable")
        self.assertNotIn("adblock-fast.adzero_default", self.config())
        self.run_ctl("disable")
        self.assertEqual(self.config(), config)

    def test_allow_list_alone_does_not_replace_default_blocklist(self):
        config = self.config()
        config.update({"adblock-fast.allow": "file_url", "adblock-fast.allow.url": "https://example.test/allow", "adblock-fast.allow.action": "allow"})
        self.conf.write_text(json.dumps(config))
        self.run_ctl("enable")
        self.assertIn("adblock-fast.adzero_default", self.config())

    def test_default_rule_partial_creation_failure_is_rolled_back(self):
        before = self.config()
        self.env["MOCK_UCI_FAIL_KEY"] = "adblock-fast.adzero_default.url"
        self.run_ctl("enable", success=False)
        self.assertEqual(self.config(), before)
        self.assertFalse((self.state / "managed").exists())
        self.assertFalse((self.state / "default_rule.owned").exists())

    def test_changed_default_rule_is_preserved_when_disabling(self):
        self.run_ctl("enable")
        config = self.config()
        config["adblock-fast.adzero_default.url"] = "https://user.example.test/list"
        self.conf.write_text(json.dumps(config))
        self.run_ctl("disable")
        self.assertEqual(self.config()["adblock-fast.adzero_default.url"], "https://user.example.test/list")
        self.assertFalse((self.state / "default_rule.owned").exists())

    def test_user_extra_option_on_default_rule_is_preserved(self):
        self.run_ctl("enable")
        config = self.config()
        config["adblock-fast.adzero_default.custom"] = "keep"
        self.conf.write_text(json.dumps(config))
        self.run_ctl("disable")
        self.assertEqual(self.config()["adblock-fast.adzero_default.custom"], "keep")

    def test_empty_sources_after_external_change_are_not_reported_as_enabled(self):
        self.run_ctl("enable")
        config = self.config()
        config["adblock-fast.adzero_default.enabled"] = "0"
        self.conf.write_text(json.dumps(config))
        self.assertEqual(self.status()["state"], "inconsistent")
        self.run_ctl("refresh", success=False)

    def test_combined_insecure_and_indirect_curl_flags_are_rejected(self):
        for extra in ("-sSk", "-ks", "--config /private/file", "-K/private/file", "--retry\t2\n-k"):
            with self.subTest(extra=extra):
                config = self.config()
                config["adblock-fast.config.curl_additional_param"] = extra
                self.conf.write_text(json.dumps(config))
                self.run_ctl("enable", success=False)
                self.assertFalse(self.state.exists())

    def test_real_probe_is_composed_into_status(self):
        self.env.update(ADZERO_PROBE=str(CTL.with_name("probe")), ADZERO_PROBE_ROOT=self.tmp.name, ADZERO_OPKG="/missing-opkg", ADZERO_APK="/missing-apk", ADZERO_UBUS="/missing-ubus")
        compatibility = self.status()["compatibility"]
        self.assertEqual(compatibility["schema_version"], 1)
        self.assertEqual(len(compatibility["plugins"]), 5)
        self.assertEqual(compatibility["dns"]["client_path"], "unverified")

    def test_rule_restore_read_failure_retains_recovery_markers(self):
        self.run_ctl("enable")
        self.env["MOCK_UCI_FAIL_SHOW"] = "1"
        self.run_ctl("disable", success=False)
        self.assertTrue((self.state / "managed").exists())
        self.assertTrue((self.state / "default_rule.owned").exists())
        del self.env["MOCK_UCI_FAIL_SHOW"]
        self.run_ctl("disable")
        self.assertNotIn("adblock-fast.adzero_default", self.config())

if __name__ == "__main__":
    unittest.main()
