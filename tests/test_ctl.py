#!/usr/bin/env python3
"""Local-only mock tests. They never call real UCI, init services or the network."""
import json
import os
import subprocess
import shlex
import tempfile
import time
import unittest
from pathlib import Path
from lock_fixture import install as install_lock

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
if [ "$1" != stop ] && [ -f "$MOCK_FAIL_ONCE" ]; then
    rm -f "$MOCK_FAIL_ONCE"
    echo "simulated one-time restart failure" >&2
    exit 17
fi
if [ -f "$MOCK_FAIL" ]; then
    echo "simulated persistent restart failure" >&2
    exit 17
fi
if [ "$1" = stop ]; then
    printf stopped > "$MOCK_BACKEND_RUNTIME"
elif [ "${MOCK_FALSE_SUCCESS:-0}" = 1 ]; then
    printf failed > "$MOCK_BACKEND_RUNTIME"
elif [ "${MOCK_NOOP_START:-0}" != 1 ]; then
    printf ready > "$MOCK_BACKEND_RUNTIME"
fi
exit "${MOCK_HOOK_RC:-0}"
'''
MOCK_BACKEND_CHECK = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
path = Path(os.environ["MOCK_BACKEND_RUNTIME"])
state = path.read_text() if path.exists() else "stopped"
conf = json.loads(Path(os.environ["MOCK_CONFIG"]).read_text())
ready = state == "ready" and conf["adblock-fast.config.enabled"] == "1" and not Path(os.environ["MOCK_BAD_HEALTH"]).exists()
print(json.dumps({"state": "ready" if ready else state, "domains": 2 if ready else 0}))
action = sys.argv[1]
if action == 'download-error': sys.exit(0 if os.environ.get("MOCK_DOWNLOAD_ERROR") == '1' else 1)
if action == 'stopped': sys.exit(0 if state == 'stopped' else 1)
sys.exit(0 if ready else 1)
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
        self.backend_check = base / "mock_backend_check"
        self.runtime = base / "backend_runtime"
        self.bad_health = base / "backend_bad_health"
        self.uci.write_text(MOCK_UCI)
        self.backend.write_text(MOCK_BACKEND)
        self.uci.chmod(0o700)
        self.backend.chmod(0o700)
        self.backend_check.write_text(MOCK_BACKEND_CHECK)
        self.backend_check.chmod(0o700)
        self.adapter = base / "mock_adapter"
        self.adapter.write_text('#!/bin/sh\nif [ "$1" = status ]; then echo \'{"plugin":"none","stage":"inactive","domains":0}\'; fi\nexit 0\n')
        self.adapter.chmod(0o700)
        policy = base / 'mock_policy'
        policy.write_text('''#!/bin/sh
case "$1" in
 status) echo '{"allowed":[],"pending":false,"pause":null}' ;;
 pending|is-paused|pause-due|has-allowed|cache-live|cache-restamp) exit 1 ;;
esac
exit 0
''')
        policy.chmod(0o700)
        self.env = {
            **os.environ,
            "ADZERO_UCI": str(self.uci),
            "ADZERO_ADAPTER": str(self.adapter),
            "ADZERO_POLICY": str(policy),
            "ADZERO_SOURCES": str(policy),
            "ADZERO_BACKEND_INIT": str(self.backend),
            "ADZERO_BACKEND_CHECK": str(self.backend_check),
            "ADZERO_STATE_DIR": str(self.state),
            "ADZERO_LOCK_DIR": str(self.lock),
            "ADZERO_LOCK_PROGRAM": install_lock(base,shlex.split(os.environ.get('ADZERO_UCODE',''))),
            "ADZERO_LOCK_WAIT_SECONDS": "0",
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
            "MOCK_BACKEND_RUNTIME": str(self.runtime),
            "MOCK_BAD_HEALTH": str(self.bad_health),
        }

    def run_ctl(self, command, success=True):
        result = subprocess.run(
            shlex.split(os.environ.get("ADZERO_TEST_SHELL", "/bin/sh")) + [str(CTL), command],
            text=True, capture_output=True, env=self.env, timeout=20
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def config(self):
        return json.loads(self.conf.read_text())

    def pool_failure(self,restore=True):
        job=Path(self.tmp.name)/'job';job.mkdir();self.env['ADZERO_JOB_CONTEXT']=str(job)
        self.adapter.write_text('#!/bin/sh\ncase "$1" in\n apply) printf dns_pool_not_ready > "$ADZERO_JOB_CONTEXT/reason"; exit 1;;\n remove) exit '+('0' if restore else '1')+';;\n status) echo \'{"plugin":"none","stage":"inactive","domains":0}\';;\nesac\nexit 0\n')
        before=self.config();self.run_ctl('enable',success=False)
        self.assertEqual((job/'reason').read_text(),'dns_pool_not_ready')
        return job,before

    def test_dns_pool_failed_enable_records_confirmed_rollback(self):
        job,before=self.pool_failure()
        self.assertEqual((job/'recovery').read_text(),'restored')
        self.assertEqual(self.config(),before);self.assertFalse((self.state/'managed').exists())

    def test_dns_pool_failed_rollback_never_claims_original_settings_restored(self):
        job,_=self.pool_failure(False)
        self.assertEqual((job/'recovery').read_text(),'unconfirmed');self.assertTrue((self.state/'managed').exists())

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
        self.assertNotIn("默认规则", result.stderr)
        self.assertEqual(self.config()["adblock-fast.config.enabled"], "0")
        self.assertEqual(self.config()["adblock-fast.config.force_dns"], "1")
        self.assertEqual(self.config()["adzero.main.enabled"], "0")
        self.assertFalse((self.state / "managed").exists())

    def test_hook_exit_one_after_success_allows_enable_refresh_and_disable(self):
        self.env["MOCK_HOOK_RC"] = "1"
        before = self.config()
        self.run_ctl("enable")
        self.assertEqual(self.status()["state"], "configured_unverified")
        self.run_ctl("refresh")
        self.run_ctl("disable")
        self.assertEqual(self.config(), before)
        self.assertEqual(self.log.read_text().splitlines(), ["stop", "start", "stop", "dl", "stop"])

    def test_exit_zero_without_successful_state_is_rolled_back(self):
        before = self.config()
        self.env["MOCK_FALSE_SUCCESS"] = "1"
        result = self.run_ctl("enable", success=False)
        self.assertEqual(self.config(), before)
        self.assertNotIn("规则下载", result.stderr)
        self.assertFalse((self.state / "managed").exists())

    def test_actual_download_error_can_show_public_default_url(self):
        self.env.update(MOCK_FALSE_SUCCESS="1", MOCK_DOWNLOAD_ERROR="1")
        result = self.run_ctl("enable", success=False)
        self.assertIn("wildcard/light-onlydomains.txt", result.stderr)
        self.assertFalse((self.state / "managed").exists())

    def test_prior_success_cannot_mask_noop_start_with_exit_one(self):
        self.runtime.write_text("ready")
        self.env.update(MOCK_HOOK_RC="1", MOCK_NOOP_START="1")
        self.run_ctl("enable", success=False)
        self.assertEqual(self.runtime.read_text(), "stopped")
        self.assertEqual(self.config()["adzero.main.enabled"], "0")

    def test_lost_live_backend_state_is_not_reported_as_enabled(self):
        self.run_ctl("enable")
        self.bad_health.touch()
        self.assertEqual(self.status()["state"], "inconsistent")
        self.run_ctl("enable", success=False)
        self.run_ctl("reconcile", success=False)
        self.assertTrue((self.state / "managed").exists())

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

    def test_backend_download_size_does_not_orphan_owned_default_rule(self):
        before = self.config()
        self.run_ctl("enable")
        config = self.config()
        config["adblock-fast.adzero_default.size"] = "1398563"
        self.conf.write_text(json.dumps(config))
        self.run_ctl("disable")
        self.assertEqual(self.config(), before)

    def test_non_numeric_extra_metadata_is_preserved(self):
        self.run_ctl("enable")
        config = self.config()
        config["adblock-fast.adzero_default.size"] = "user-custom-value"
        self.conf.write_text(json.dumps(config))
        self.run_ctl("disable")
        self.assertEqual(self.config()["adblock-fast.adzero_default.size"], "user-custom-value")

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

    @unittest.skipUnless(os.environ.get('ADZERO_UCODE'), 'requires actual OpenWrt ucode')
    def test_real_probe_is_composed_into_status(self):
        self.env.update(ADZERO_PROBE=str(CTL.with_name("probe")), ADZERO_PROBE_ROOT=self.tmp.name, ADZERO_OPKG="/missing-opkg", ADZERO_APK="/missing-apk", ADZERO_UBUS="/missing-ubus")
        compatibility = self.status()["compatibility"]
        self.assertEqual(compatibility["schema_version"], 1)
        self.assertEqual(len(compatibility["plugins"]), 7)
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

    def test_busy_lock_timeout_does_not_modify_or_remove_legacy_lock(self):
        before = self.config()
        self.lock.mkdir()
        result = self.run_ctl("disable", success=False)
        self.assertIn("等待操作锁超时", result.stderr)
        self.assertEqual(self.config(), before)
        self.assertTrue(self.lock.is_dir())
        self.assertEqual(list(self.lock.iterdir()), [])
        self.assertFalse(self.log.exists())

    def test_background_reconcile_reports_busy_without_waiting_or_mutation(self):
        self.lock.mkdir()
        owner = self.lock / "owner"
        owner.write_text("999999999 refresh\n")
        before = self.config()
        result = self.run_ctl("reconcile", success=False)
        self.assertEqual(result.returncode,75)
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.config(), before)
        self.assertEqual(owner.read_text(), "999999999 refresh\n")
        self.assertFalse(self.log.exists())

    def test_verified_orphan_lock_is_recovered_without_reboot(self):
        self.lock.mkdir()
        (self.lock/'lease').write_text('AdZero kernel lease v1\n')
        (self.lock/'owner').write_text('999999999 reconcile\n')
        (self.lock/'identity').write_text('999999999 reconcile 1\n')
        self.run_ctl('disable')
        self.assertFalse(self.lock.exists())
        self.assertFalse(self.status()['operation']['locked'])

    def test_orphan_lock_with_unknown_files_is_not_removed(self):
        self.lock.mkdir()
        (self.lock/'lease').write_text('AdZero kernel lease v1\n')
        (self.lock/'owner').write_text('999999999 reconcile\n')
        (self.lock/'identity').write_text('999999999 reconcile 1\n')
        unknown=self.lock/'external';unknown.write_text('keep')
        self.run_ctl('disable',success=False)
        self.assertEqual(unknown.read_text(),'keep')

    def test_kernel_lease_prevents_stealing_a_live_orphan_child(self):
        import fcntl
        lease=Path(str(self.lock)+'.lease')
        with lease.open('a') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.lock.mkdir()
            (self.lock/'lease').write_text('AdZero kernel lease v1\n')
            (self.lock/'owner').write_text('999999999 reconcile\n')
            (self.lock/'identity').write_text('999999999 reconcile 1\n')
            self.run_ctl('disable',success=False)
            self.assertTrue(self.lock.exists())
        self.run_ctl('disable')
        self.assertFalse(self.lock.exists())

    def test_killed_controller_keeps_lease_until_its_child_finishes(self):
        self.run_ctl('enable')
        held=Path(self.tmp.name)/'hold';held.touch()
        child_pid=Path(self.tmp.name)/'active-child'
        self.adapter.write_text('''#!/usr/bin/env python3
import fcntl,sys,time
from pathlib import Path
if sys.argv[1]=='apply':
 fcntl.fcntl(9,fcntl.F_GETFD)
 Path('''+repr(str(child_pid))+''').write_text(str(__import__('os').getpid()))
 while Path('''+repr(str(held))+''').exists():time.sleep(.02)
''')
        command=shlex.split(os.environ.get('ADZERO_TEST_SHELL','/bin/sh'))+[str(CTL),'reconcile']
        first=subprocess.Popen(command,env=self.env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            deadline=time.monotonic()+8
            while not child_pid.exists() and first.poll() is None and time.monotonic()<deadline:time.sleep(.02)
            self.assertTrue(child_pid.exists(),'the active mutation must inherit descriptor 9')
            first.kill();first.wait(timeout=5)
            self.run_ctl('disable',success=False)
            self.assertTrue(self.lock.exists(),'the still-active orphan child must retain serialization')
        finally:
            held.unlink(missing_ok=True)
            if first.poll() is None:first.kill();first.wait(timeout=5)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            if child_pid.exists() and not Path('/proc/'+child_pid.read_text()).exists():break
            time.sleep(.02)
        self.run_ctl('disable')

    def test_reused_pid_does_not_keep_a_verified_orphan_lock_busy(self):
        child=subprocess.Popen(['sleep','10'])
        try:
            self.lock.mkdir()
            (self.lock/'lease').write_text('AdZero kernel lease v1\n')
            (self.lock/'owner').write_text(f'{child.pid} reconcile\n')
            (self.lock/'identity').write_text(f'{child.pid} reconcile 1\n')
            self.run_ctl('disable')
            self.assertFalse(self.lock.exists())
            self.assertIsNone(child.poll())
        finally:child.terminate();child.wait(timeout=5)

    def test_status_can_be_read_while_mutation_lock_exists(self):
        self.lock.mkdir()
        self.assertEqual(self.status()["state"], "disabled")
        self.assertEqual(self.status()["operation"], {"active": False, "locked": True})
        self.assertTrue(self.lock.is_dir())

    def test_live_reconcile_identity_and_timeout_leave_filtering_untouched(self):
        self.run_ctl("enable")
        held = Path(self.tmp.name) / "hold"
        ready = Path(self.tmp.name) / "ready"
        held.touch()
        self.env.update(MOCK_LOCK_HOLD=str(held), MOCK_LOCK_READY=str(ready))
        self.adapter.write_text('''#!/usr/bin/env python3
import os, sys, time
from pathlib import Path
if sys.argv[1] == 'apply':
    Path(os.environ['MOCK_LOCK_READY']).touch()
    while Path(os.environ['MOCK_LOCK_HOLD']).exists(): time.sleep(0.02)
if sys.argv[1] == 'status': print('{"plugin":"nailink","stage":"restoring","domains":2}')
''')
        command = shlex.split(os.environ.get("ADZERO_TEST_SHELL", "/bin/sh")) + [str(CTL), "reconcile"]
        first = subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and first.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists())
            status = self.status()
            self.assertEqual(status["state"], "inconsistent")  # raw transaction state stays honest
            self.assertEqual(status["operation"], {"active": True, "locked": True, "action": "reconcile"})
            self.assertNotIn(str(first.pid), json.dumps(status["operation"]))
            identity = (self.lock / "identity").read_text()
            (self.lock / "identity").write_text(f"{first.pid} reconcile 0\n")
            self.assertFalse(self.status()["operation"]["active"], "a reused PID cannot mask a recovery error")
            (self.lock / "identity").write_text(identity)
            before = self.config()
            jobs = Path(self.tmp.name) / "job"
            jobs.mkdir()
            self.env["ADZERO_JOB_CONTEXT"] = str(jobs)
            result = self.run_ctl("disable", success=False)
            self.assertIn("等待操作锁超时", result.stderr)
            self.assertEqual((jobs / "reason").read_text(), "lock_busy")
            self.assertEqual(self.config(), before)
            self.assertIsNone(first.poll())
            self.assertEqual((self.lock / "identity").read_text(), identity)
            held.unlink()
            out, err = first.communicate(timeout=15)
            self.assertEqual(first.returncode, 0, out + err)
            self.assertFalse(self.lock.exists())
            self.assertEqual(self.status()["operation"], {"active": False, "locked": False})
        finally:
            held.unlink(missing_ok=True)
            if first.poll() is None:
                first.kill()
                first.communicate(timeout=5)

    def test_extended_mutation_locks_are_reported_as_active_operations(self):
        child=subprocess.Popen(['sleep','30'])
        try:
            self.lock.mkdir()
            start=Path(f'/proc/{child.pid}/stat').read_text().rsplit(') ',1)[1].split()[19]
            before=self.config()
            for action in ('temporary','temporary-expire','enhance-save','dns-switch'):
                with self.subTest(action=action):
                    record=f'{child.pid} {action}'
                    (self.lock/'owner').write_text(record+'\n')
                    (self.lock/'identity').write_text(record+' '+start+'\n')
                    self.assertEqual(self.status()['operation'],{'active':True,'locked':True,'action':action})
            self.assertEqual(self.config(),before)
        finally:
            child.terminate();child.wait(timeout=5)

    def test_dead_unknown_or_linked_owner_is_not_reported_as_live(self):
        self.lock.mkdir()
        owner, identity = self.lock / "owner", self.lock / "identity"
        for value in ("999999999 reconcile", "1 secret-value", "malformed"):
            owner.write_text(value + "\n")
            identity.write_text(value + " 1\n")
            before = (owner.read_bytes(), identity.read_bytes())
            self.assertEqual(self.status()["operation"], {"active": False, "locked": True})
            self.assertEqual((owner.read_bytes(), identity.read_bytes()), before)
        identity.unlink()
        identity.symlink_to(self.conf)
        self.assertEqual(self.status()["operation"], {"active": False, "locked": True})

    def test_background_reconcile_after_disable_is_a_quiet_noop(self):
        before = self.config()
        result = self.run_ctl("reconcile")
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.config(), before)
        self.assertFalse(self.lock.exists())
        self.assertFalse(self.log.exists())

    def test_missing_lock_parent_is_not_misreported_as_busy(self):
        self.env["ADZERO_LOCK_DIR"] = str(self.lock / "missing_parent" / "lock")
        result = self.run_ctl("enable", success=False)
        self.assertIn("无法创建操作锁", result.stderr)
        self.assertFalse(self.state.exists())

    def test_invalid_lock_wait_is_rejected_without_changes(self):
        for value in ("-1", "61", "infinite", "99999999999999999999999999999999"):
            with self.subTest(value=value):
                self.env["ADZERO_LOCK_WAIT_SECONDS"] = value
                self.run_ctl("enable", success=False)
                self.assertFalse(self.lock.exists())
                self.assertFalse(self.state.exists())

    def test_release_preserves_replaced_owner_record(self):
        self.adapter.write_text('#!/bin/sh\nif [ "$1" = apply ]; then printf "999999999 refresh\\n" > "$ADZERO_LOCK_DIR/owner"; fi\nexit 0\n')
        self.run_ctl("enable")
        self.assertEqual((self.lock / "owner").read_text(), "999999999 refresh\n")

    def test_failed_operation_releases_its_own_lock(self):
        self.env["MOCK_UCI_FAIL_KEY"] = "adblock-fast.config.enabled"
        self.run_ctl("enable", success=False)
        self.assertFalse(self.lock.exists())

    def test_foreground_waits_for_real_owner_then_disables_without_overlap(self):
        held = Path(self.tmp.name) / "hold"
        ready = Path(self.tmp.name) / "ready"
        held.touch()
        self.env.update(MOCK_LOCK_HOLD=str(held), MOCK_LOCK_READY=str(ready), ADZERO_LOCK_WAIT_SECONDS="5")
        self.adapter.write_text('''#!/usr/bin/env python3
import os, sys, time
from pathlib import Path
if sys.argv[1] == 'apply':
    Path(os.environ['MOCK_LOCK_READY']).touch()
    while Path(os.environ['MOCK_LOCK_HOLD']).exists(): time.sleep(0.02)
if sys.argv[1] == 'status': print('{"plugin":"none","stage":"inactive","domains":0}')
''')
        command = shlex.split(os.environ.get("ADZERO_TEST_SHELL", "/bin/sh")) + [str(CTL)]
        first = subprocess.Popen(command + ["enable"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
        second = None
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and first.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists(), "first controller never reached adapter apply")
            self.assertEqual((self.lock / "owner").read_text(), f"{first.pid} enable\n")
            second = subprocess.Popen(command + ["disable"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
            time.sleep(0.15)
            self.assertIsNone(second.poll(), "disable should wait, not fail or enter concurrently")
            self.assertEqual(self.config()["adzero.main.enabled"], "1")
            self.assertEqual((self.lock / "owner").read_text(), f"{first.pid} enable\n")
            held.unlink()
            first_out, first_err = first.communicate(timeout=15)
            second_out, second_err = second.communicate(timeout=15)
            self.assertEqual(first.returncode, 0, first_err + first_out)
            self.assertEqual(second.returncode, 0, second_err + second_out)
            self.assertIn("正在等待当前操作", second_err)
            self.assertEqual(self.config()["adzero.main.enabled"], "0")
            self.assertEqual(self.config()["adblock-fast.config.enabled"], "0")
            self.assertFalse(self.lock.exists())
        finally:
            held.unlink(missing_ok=True)
            for proc in (first, second):
                if proc is not None and proc.poll() is None:
                    proc.kill()
                    proc.communicate(timeout=5)

if __name__ == "__main__":
    unittest.main()
