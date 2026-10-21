"""Read-only capability inventory on isolated firmware/process/UCI fixtures."""
import json
import os
from pathlib import Path
import subprocess
import shlex
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "luci-app-adzero/root/usr/libexec/adzero/probe"
COMMAND = r'''#!/usr/bin/env python3
import json, os, pathlib, re, sys
data = json.loads(pathlib.Path(os.environ['PROBE_FIXTURE']).read_text())
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
if name == 'uci':
    if args[:2] != ['-q', 'get']: raise SystemExit(91)
    key = args[2]
    if key not in data.get('uci', {}): raise SystemExit(1)
    print(data['uci'][key])
elif name == 'pidof':
    raise SystemExit(0 if args[0] in data.get('running', []) else 1)
elif name == 'uname':
    print(data.get('cpu', 'x86_64') if args == ['-m'] else '6.6.0-fixture')
elif name == 'opkg':
    assert args == ['print-architecture']
    print('arch all 1\narch noarch 1\narch generic 5\narch ' + data.get('arch', 'x86_64') + ' 10')
elif name == 'apk':
    assert args == ['--print-arch']
    print(data.get('arch', 'x86_64'))
elif name == 'ubus':
    assert args[:4] == ['-S', 'call', 'service', 'list']
    service = json.loads(args[4])['name']
    values = data.get('services', {}).get(service)
    print(json.dumps({service: {'instances': {'main': {'running': values}}}}) if values is not None else '{}')
elif name == 'jsonfilter':
    match = re.fullmatch(r'@\["([a-z0-9_-]+)"\]\.instances\.\*\.running', args[1])
    assert args[0] == '-e' and match
    service = json.load(sys.stdin).get(match[1], {})
    for instance in service.get('instances', {}).values():
        print(json.dumps(instance['running']))
else:
    raise SystemExit(90)
'''


class ProbeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = self.root / "fixture.json"
        self.data = {"uci": {}, "running": []}
        self.env = {**os.environ, "ADZERO_PROBE_ROOT": str(self.root), "PROBE_FIXTURE": str(self.fixture)}
        for name in ("uci", "pidof", "uname", "opkg", "apk", "ubus", "jsonfilter"):
            path = self.root / "bin" / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(COMMAND)
            path.chmod(0o755)
            self.env["ADZERO_" + name.upper()] = str(path)
        self.env["ADZERO_APK"] = str(self.root / "missing-apk")
        self.write("etc/openwrt_release", "DISTRIB_ID='OpenWrt'\nDISTRIB_RELEASE='24.10.8'\nDISTRIB_TARGET='x86/64'\n")
        self.write("www/luci-static/resources/view.js", "fixture")

    def write(self, name, content=""):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def probe(self):
        self.fixture.write_text(json.dumps(self.data))
        before = self.fixture.read_bytes()
        shell = shlex.split(os.environ.get("ADZERO_TEST_SHELL", "/bin/sh"))
        result = subprocess.run(shell + [str(PROBE)], env=self.env, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fixture.read_bytes(), before, "probe must not mutate UCI")
        return json.loads(result.stdout)

    def test_firmware_cpu_and_package_matrix(self):
        for vendor in ("OpenWrt", "ImmortalWrt", "iStoreOS"):
            for version, manager, cpu, arch in (
                ("24.10.8", "opkg", "x86_64", "x86_64"),
                ("25.12.5", "apk", "aarch64", "aarch64_cortex-a53"),
                ("24.10.3", "opkg", "armv7l", "arm_cortex-a7_neon-vfpv4"),
                ("25.12.6", "apk", "mips", "mips_24kc"),
                ("24.10.8", "opkg", "mips", "mipsel_24kc"),
                ("25.12.5", "apk", "riscv64", "riscv64_riscv64"),
                ("24.10.8", "opkg", "i686", "i386_pentium4"),
                ("25.12.5", "apk", "mips64", "mips64_octeonplus"),
            ):
                with self.subTest(vendor=vendor, version=version, arch=arch):
                    self.write("etc/openwrt_release", f"DISTRIB_ID='{vendor}'\nDISTRIB_RELEASE='{version}'\n")
                    self.env["ADZERO_OPKG"] = str(self.root / ("bin/opkg" if manager == "opkg" else "missing-opkg"))
                    self.env["ADZERO_APK"] = str(self.root / ("bin/apk" if manager == "apk" else "missing-apk"))
                    self.data.update(cpu=cpu, arch=arch)
                    status = self.probe()["platform"]
                    self.assertEqual(status["family"], vendor.lower())
                    self.assertEqual(status["version"], version)
                    self.assertEqual(status["cpu"], cpu)
                    self.assertEqual(status["package_arch"], arch)
                    self.assertEqual(status["package_manager"], manager)
                    self.assertEqual(status["validation"], "not_device_tested")

    def test_package_format_follows_installed_database_not_version(self):
        self.env["ADZERO_APK"] = str(self.root / "bin/apk")
        self.write("lib/apk/db/installed")
        self.assertEqual(self.probe()["platform"]["package_manager"], "apk")
        self.write("usr/lib/opkg/status")
        self.assertEqual(self.probe()["platform"]["package_manager"], "ambiguous")

    def test_two_binaries_without_database_are_ambiguous(self):
        self.env["ADZERO_APK"] = str(self.root / "bin/apk")
        self.assertEqual(self.probe()["platform"]["package_manager"], "ambiguous")

    def test_missing_tools_are_unknown(self):
        self.env["ADZERO_OPKG"] = str(self.root / "missing-opkg")
        self.assertEqual(self.probe()["platform"]["package_manager"], "unknown")

    def test_plugins_share_core_without_false_runtime_attribution(self):
        for name in ("daed", "passwall", "passwall2", "openclash", "nikki"):
            self.write("etc/config/" + name)
        self.data["running"] = ["mihomo", "xray", "sing-box"]
        self.data["uci"] = {"openclash.config.enable": "1", "nikki.config.enabled": "0"}
        status = self.probe()
        self.assertEqual(status["cores"], ["mihomo", "xray", "sing-box"])
        for plugin in status["plugins"]:
            self.assertEqual(plugin["runtime"], "unknown")
            self.assertEqual(plugin["integration"], "unverified")
        self.assertEqual(status["dns"]["proxy_count"], 5)
        self.assertEqual(status["dns"]["active_proxy_count"], 1)

    def test_exact_procd_service_and_daed_process(self):
        self.write("etc/config/openclash")
        self.write("etc/config/nikki")
        self.data["services"] = {"nikki": True, "openclash": False}
        self.data["running"] = ["daed"]
        self.data["uci"] = {"nikki.proxy.ipv4_dns_hijack": "1"}
        plugins = {p["id"]: p for p in self.probe()["plugins"]}
        self.assertEqual(plugins["nailink"]["runtime"], "running")
        self.assertEqual(plugins["nikki"]["runtime"], "running")
        self.assertEqual(plugins["nikki"]["dns_hint"], "plugin_redirect")
        self.assertEqual(plugins["openclash"]["runtime"], "stopped")

    def test_private_configuration_is_not_returned(self):
        self.write("etc/config/passwall")
        self.data["uci"] = {"passwall.@global[0].enabled": "1", "passwall.node.password": "SECRET-NODE-TOKEN"}
        self.assertNotIn("SECRET-NODE-TOKEN", json.dumps(self.probe()))

    def test_release_metadata_is_not_executed_and_json_is_escaped(self):
        payload = 'iStoreOS "测试" \\ $(touch SHOULD_NOT_EXIST)\t'
        self.write("etc/openwrt_release", "DISTRIB_ID='" + payload + "'\nDISTRIB_RELEASE='25.12.5'\n")
        self.assertEqual(self.probe()["platform"]["distribution"], payload)
        self.assertFalse((ROOT / "SHOULD_NOT_EXIST").exists())

    def test_memory_and_multiple_dns_instances_remain_unverified(self):
        self.write("proc/meminfo", "MemTotal: 32768 kB\n")
        self.data["uci"] = {"dhcp.@dnsmasq[0]": "dnsmasq", "dhcp.@dnsmasq[0].port": "0", "dhcp.@dnsmasq[1]": "dnsmasq"}
        status = self.probe()
        self.assertEqual(status["platform"]["resource_hint"], "low_memory")
        self.assertEqual(status["dns"]["dnsmasq_instances"], 2)
        self.assertEqual(status["dns"]["disabled_instances"], 1)
        self.assertEqual(status["dns"]["client_path"], "unverified")
        self.assertEqual(status["dns"]["ipv6_path"], "unverified")

    def test_future_version_is_reported_without_guessing_support(self):
        self.write("etc/openwrt_release", "DISTRIB_ID='OpenWrt'\nDISTRIB_RELEASE='99.01.0'\n")
        self.assertEqual(self.probe()["platform"]["release_track"], "unvalidated")

    def test_os_release_fallback(self):
        (self.root / "etc/openwrt_release").unlink()
        self.write("etc/os-release", 'NAME="ImmortalWrt"\nVERSION_ID="24.10.8"\n')
        self.assertEqual(self.probe()["platform"]["family"], "immortalwrt")
