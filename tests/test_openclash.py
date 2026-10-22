"""OpenClash's temporary hook target, quick-start and suppressed error boundary.

Uses real ucode/Ruby; native init invocation is a focused fixture here. Pinned
native shell stages and real Mihomo DNS are exercised by check_openclash_runtime.
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'luci-app-adzero/root/usr/libexec/adzero'
UCODE = shlex.split(os.environ.get('ADZERO_UCODE', ''))


@unittest.skipUnless(UCODE and shutil.which('ruby'), 'real OpenWrt ucode and Ruby required')
class OpenClashTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='adzero-openclash-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {**os.environ, 'ADZERO_ADAPTER_ROOT': str(self.root),
                    'ADZERO_ADAPTER_INVENTORY': str(self.root/'inventory.json')}
        self.write('inventory.json', json.dumps({'plugins': [{'id':'openclash','installed':True,'enabled':True,'runtime':'running','active':True}]}))
        self.write('etc/config/adblock-fast', "config adblock-fast 'config'\n option dns 'dnsmasq.servers'\n")
        self.write('etc/config/openclash', "config openclash 'config'\n option enable '1'\n option config_path '/etc/openclash/config/selected profile.yaml'\n")
        self.write('var/run/adblock-fast/dnsmasq.servers', 'server=/ads.example/\nserver=/track.example/\n')
        self.source = self.write('etc/openclash/config/selected profile.yaml', 'dns:\n  enable: true\n  nameserver: [223.5.5.5]\n  enhanced-mode: fake-ip\nproxies: &items []\nother-proxies: *items\nrules: [MATCH,DIRECT]\n')
        self.custom = self.write('etc/openclash/custom/openclash_custom_overwrite.sh', '#!/bin/sh\n# User script retained\nexit 0\n')
        self.original = self.custom.read_text()
        self.write('etc/openclash/core/clash_meta', '#!/bin/sh\n[ ! -f "$ADZERO_ADAPTER_ROOT/fail-core" ]\n', executable=True)
        # Execute the installed managed shell line, with just its absolute
        # command redirected into this prefixed fixture (no direct hook call).
        wrapper = self.write('test-adapter', '#!/bin/sh\nexec '+shlex.join(UCODE+[str(LIB/'adapter.uc'),'--'])+' "$@"\n', executable=True)
        self.generated = self.root/'etc/openclash/selected profile.yaml'
        self.write('etc/init.d/openclash', '''#!/bin/sh
set -eu
cd "$ADZERO_ADAPTER_ROOT"
echo restart >> restarts
if [ -f tmp/openclash.change ]; then exit 0; fi
cp 'etc/openclash/config/selected profile.yaml' 'tmp/selected profile.yaml'
sed 's|/usr/libexec/adzero/adapter|'''+str(wrapper)+'''|' etc/openclash/custom/openclash_custom_overwrite.sh > test-hook
# Native OpenClash ignores the custom script's exit code and suppresses stderr.
sh ./test-hook '/tmp/selected profile.yaml' >/dev/null 2>&1 || :
mv 'tmp/selected profile.yaml' 'etc/openclash/selected profile.yaml'
touch tmp/openclash.change
''')
        (self.root/'tmp').mkdir(exist_ok=True)
        self.write('tmp/openclash.change', 'native quick-start cache\n')

    def write(self, path, content, executable=False):
        target=self.root/path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        if executable:target.chmod(0o755)
        return target

    def run_adapter(self, action, *args, success=True):
        result=subprocess.run(UCODE+[str(LIB/'adapter.uc'),'--',action,*args],
                              env=self.env,text=True,capture_output=True,timeout=12)
        self.assertEqual(result.returncode==0,success,result.stderr)
        return result

    def test_selected_temporary_yaml_and_provider_only_update_bypass_quick_start(self):
        self.run_adapter('apply')
        config=json.loads(self.generated.read_text())
        self.assertEqual(config['other-proxies'],[])
        self.assertEqual(config['dns']['nameserver-policy']['rule-set:adzero-dns'],['rcode://name_error'])
        self.assertEqual(config['rules'][0],'RULE-SET,adzero-dns,REJECT')
        self.assertEqual(len((self.root/'restarts').read_text().splitlines()),1)
        self.run_adapter('apply')
        self.assertEqual(len((self.root/'restarts').read_text().splitlines()),1)
        self.write('var/run/adblock-fast/dnsmasq.servers','server=/ads.example/\nserver=/new.example/\n')
        self.run_adapter('apply')
        self.assertEqual(len((self.root/'restarts').read_text().splitlines()),2)
        self.assertIn('+.new.example',(self.root/'etc/openclash/rule_provider/adzero.txt').read_text())
        self.run_adapter('remove')
        self.assertEqual(self.custom.read_text(),self.original)
        self.assertEqual(self.generated.read_text(),self.source.read_text())
        self.assertFalse((self.root/'etc/adzero/adapter.json').exists())
        self.assertFalse((self.root/'etc/openclash/rule_provider/adzero.txt').exists())
        self.assertEqual(len((self.root/'restarts').read_text().splitlines()),3)

    def test_suppressed_core_error_is_reported_immediately_and_original_restored(self):
        self.write('fail-core','')
        started=time.monotonic()
        result=self.run_adapter('apply',success=False)
        self.assertLess(time.monotonic()-started,5)
        self.assertIn('OpenClash core rejected the adapted configuration',result.stderr)
        self.assertNotIn('did not confirm',result.stderr)
        self.assertEqual(self.custom.read_text(),self.original)
        self.assertEqual(self.generated.read_text(),self.source.read_text())
        self.assertFalse((self.root/'etc/adzero/adapter.json').exists())

    def test_core_validation_uses_only_native_safe_paths_without_changing_parent(self):
        self.env['SAFE_PATHS']='/untrusted/inherited:/tmp'
        self.write('etc/openclash/core/clash_meta', '''#!/bin/sh
printf '%s' "$SAFE_PATHS" > "$ADZERO_ADAPTER_ROOT/validation-safe-paths"
[ "$SAFE_PATHS" = "$ADZERO_ADAPTER_ROOT/usr/share/openclash:$ADZERO_ADAPTER_ROOT/etc/ssl" ]
''', executable=True)
        self.run_adapter('apply')
        self.assertEqual((self.root/'validation-safe-paths').read_text(),
                         str(self.root)+'/usr/share/openclash:'+str(self.root)+'/etc/ssl')
        self.assertEqual(self.env['SAFE_PATHS'],'/untrusted/inherited:/tmp')
        self.run_adapter('remove')
        self.assertEqual(self.custom.read_text(),self.original)

    def test_disabled_native_dns_has_specific_error_and_preserves_native_config(self):
        self.source.write_text(self.source.read_text().replace('enable: true','enable: false'))
        result=self.run_adapter('apply',success=False)
        self.assertIn('OpenClash DNS is disabled',result.stderr)
        self.assertEqual(self.generated.read_text(),self.source.read_text())
        self.assertEqual(self.custom.read_text(),self.original)

    def test_hook_refuses_unselected_files_traversal_and_symlinks(self):
        self.run_adapter('apply')
        journal=self.root/'etc/adzero/adapter.json'
        saved=journal.read_text()
        outside=self.write('tmp/unrelated.yaml','private: unchanged\n')
        for path in ['/tmp/unrelated.yaml','/etc/openclash/config/selected profile.yaml',
                     '/tmp/../etc/openclash/selected profile.yaml']:
            with self.subTest(path=path):
                journal.write_text(saved)
                self.run_adapter('hook-openclash',path,success=False)
                self.assertEqual(outside.read_text(),'private: unchanged\n')
                self.assertNotIn('adzero-dns',self.source.read_text())
        journal.write_text(saved)
        (self.root/'tmp/selected profile.yaml').symlink_to(outside)
        self.run_adapter('hook-openclash','/tmp/selected profile.yaml',success=False)
        self.assertEqual(outside.read_text(),'private: unchanged\n')

    def test_invalid_selected_path_fails_before_owned_file_changes(self):
        self.write('etc/config/openclash',"config openclash 'config'\n option config_path '/tmp/other.yaml'\n")
        self.run_adapter('apply',success=False)
        self.assertEqual(self.custom.read_text(),self.original)
        self.assertFalse((self.root/'etc/openclash/rule_provider/adzero.txt').exists())
        self.assertFalse((self.root/'restarts').exists())
        self.assertFalse((self.root/'etc/adzero/adapter.json').exists())

    def test_later_custom_override_cannot_be_reported_as_loaded(self):
        init=self.root/'etc/init.d/openclash'
        init.write_text(init.read_text().replace("touch tmp/openclash.change", "cp 'etc/openclash/config/selected profile.yaml' 'etc/openclash/selected profile.yaml'\ntouch tmp/openclash.change"))
        result=self.run_adapter('apply',success=False)
        self.assertIn('OpenClash custom configuration hook failed',result.stderr)
        self.assertEqual(self.custom.read_text(),self.original)
        self.assertFalse((self.root/'etc/adzero/adapter.json').exists())

    def test_yaml_bridge_does_not_require_the_optional_ruby_json_package(self):
        guard=self.write('ruby-no-json.rb', '''module Kernel
alias adzero_original_require require
def require(name)
  raise LoadError, 'ruby-json intentionally unavailable' if name == 'json'
  adzero_original_require(name)
end
end
''')
        self.env['RUBYOPT']='-r'+str(guard)
        self.run_adapter('apply')
        self.assertIn('adzero-dns',self.generated.read_text())

    def test_emoji_and_control_characters_in_subscription_survive_conversion(self):
        name='🚀 节点选择 🇭🇰'
        payload={'dns':{'enable':True,'nameserver':['223.5.5.5']},
                 'proxy-groups':[{'name':name,'type':'select','proxies':['DIRECT']}],
                 'rules':['MATCH,'+name],
                 'custom-text':'引号 " / 反斜杠 \\ 字面量 \\U0001F680 与控制符 \x1b\x07\x0b\u0085\u00a0\u2028\u2029'}
        # A raw NEL is a YAML 1.1 line break; encode it explicitly to test
        # conversion of the intended character rather than YAML folding.
        self.source.write_text(json.dumps(payload,ensure_ascii=False).replace('\u0085','\\u0085'))
        self.run_adapter('apply')
        converted=json.loads(self.generated.read_text())
        self.assertEqual(converted['proxy-groups'],payload['proxy-groups'])
        self.assertEqual(converted['custom-text'],payload['custom-text'])
        self.assertIn('MATCH,'+name,converted['rules'])

    def test_unicode_proxy_configuration_accepts_both_start_orders_with_routing(self):
        name='🚀 节点选择 🇭🇰'
        config={'dns':{'enable':True,'nameserver':['8.8.8.8']},
                'proxy-groups':[{'name':name,'type':'select','proxies':['DIRECT']}],
                'rules':['MATCH,'+name]}
        self.source.write_text(json.dumps(config,ensure_ascii=False))
        self.write('etc/config/adzero',"config adzero 'main'\n option enabled '1'\n option routing_enabled '1'\n")
        dhcp=self.write('etc/config/dhcp',"config dnsmasq 'main'\n list server '8.8.8.8'\n")
        self.write('etc/init.d/dnsmasq','#!/bin/sh\nexit 0\n')
        data=self.write('country.json',json.dumps({'domain_raw':'server=/cn.example/114.114.114.114\n','cidr_raw':'223.5.5.0/24\n'}))
        self.env.update(ADZERO_ROUTING_DATA_FIXTURE=str(data),ADZERO_ROUTING_DATA_PROGRAM=str(LIB/'routing-data'),ADZERO_UCODE=shlex.join(UCODE))
        inventory=self.root/'inventory.json';active=inventory.read_text()
        for order in ('openclash_first','adzero_first'):
            with self.subTest(order=order):
                before=dhcp.read_text()
                if order=='adzero_first':
                    inventory.write_text('{"plugins":[]}')
                    self.run_adapter('apply')
                    self.assertEqual(json.loads(self.run_adapter('status').stdout)['routing']['mode'],'direct')
                inventory.write_text(active)
                self.run_adapter('apply')
                status=json.loads(self.run_adapter('status').stdout)
                self.assertEqual((status['plugin'],status['stage'],status['routing']['mode']),('openclash','configured_unverified','proxy'))
                generated=json.loads(self.generated.read_text())
                self.assertEqual(generated['dns']['nameserver'],['tcp://1.1.1.1:53#'+name])
                self.run_adapter('remove')
                self.assertEqual(self.custom.read_text(),self.original)
                # libuci restores the value and normalizes whitespace.
                self.assertEqual(dhcp.read_text().split(),before.split())
