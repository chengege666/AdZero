"""Real ucode/UCI; process/config files and init actions are isolated fixtures."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import unittest
import test_adapters as fixtures
ROOT, UCODE = fixtures.ROOT, fixtures.UCODE


@unittest.skipUnless(UCODE, 'requires native OpenWrt ucode')
class PassWallRuntimeTest(unittest.TestCase):
    setUp = fixtures.AdapterTransactionTest.setUp
    write = fixtures.AdapterTransactionTest.write
    select = fixtures.AdapterTransactionTest.select
    run_adapter = fixtures.AdapterTransactionTest.run_adapter

    def native(self, skip=False):
        self.write('proc/100/comm', 'dnsmasq_default\n')
        self.write('proc/100/stat', '100 dnsmasq fixture\n')
        self.write('proc/100/cmdline', '/tmp/etc/passwall/bin/dnsmasq_default\0-C\0/tmp/etc/passwall/acl/default/dnsmasq.conf\0')
        self.write('tmp/etc/passwall/acl/default/dnsmasq.conf', 'port=11400\nserver=127.0.0.1#15355\n')
        # The rc.common-shaped fixture is intentional: plain `sh init restart`
        # returns zero without invoking restart(). The separate chroot check
        # exercises the real rc.common and native DNS helper.
        self.write('etc/rc.common', '. "$1"\nshift\n"$@"\n')
        config = self.root/'tmp/etc/passwall/acl/default/dnsmasq.conf'
        fragment = self.write('tmp/etc/passwall/acl/default/dnsmasq.d/000-address.conf', '')
        count = self.root/'restarts'
        script = '#!/bin/sh /etc/rc.common\nrestart() {\n'
        script += 'echo restart >> '+shlex.quote(str(count))+'\n'
        if skip:
            script += '[ "$(wc -l < '+shlex.quote(str(count))+')" -ne 1 ] || return 0\n'
        script += "printf 'port=11400\\nconf-dir=/tmp/etc/passwall/acl/default/dnsmasq.d\\n' > "+shlex.quote(str(config))+'\n'
        script += "printf 'address=/.ads.example/\\naddress=/.track.example/\\n' > "+shlex.quote(str(fragment))+'\n}\n'
        self.write('etc/init.d/passwall', script)
        return config, fragment, count

    def test_rc_common_dispatch_and_zero_exit_skipped_restart_retry(self):
        config, _, count = self.native(skip=True)
        self.run_adapter('apply')
        self.assertEqual(count.read_text().splitlines(), ['restart','restart'])
        self.assertEqual(json.loads(self.run_adapter('status').stdout)['runtime']['state'], 'ready')
        self.run_adapter('apply')
        self.assertEqual(len(count.read_text().splitlines()), 2)

    def test_unchanged_source_repairs_runtime_without_rebuilding_rules(self):
        config, fragment, count = self.native()
        self.run_adapter('apply')
        source = self.root/'etc/passwall/rules/block_host'
        before = source.stat().st_mtime_ns
        config.write_text('port=11400\nserver=127.0.0.1#15355\n')
        self.assertEqual(json.loads(self.run_adapter('status').stdout)['runtime']['reason'], 'rules_not_included')
        self.run_adapter('apply')
        self.assertEqual(len(count.read_text().splitlines()), 2)
        self.assertEqual(source.stat().st_mtime_ns, before)
        fragment.write_text('address=/.old.example/\n')
        self.assertEqual(json.loads(self.run_adapter('status').stdout)['runtime']['reason'], 'rules_stale')
        self.run_adapter('apply')
        self.assertEqual(len(count.read_text().splitlines()), 3)

    def test_missing_runtime_is_operable_and_backs_off_then_manual_reload_retries(self):
        _, _, count = self.native()
        self.write('etc/init.d/passwall', '#!/bin/sh /etc/rc.common\nrestart() { echo restart >> '+shlex.quote(str(count))+'; }\n')
        self.run_adapter('apply')
        status = json.loads(self.run_adapter('status').stdout)
        self.assertEqual(status['stage'], 'configured_unverified')
        self.assertEqual(status['runtime']['state'], 'missing')
        self.run_adapter('apply')
        self.assertEqual(len(count.read_text().splitlines()), 2)
        journal=self.root/'etc/adzero/adapter.json'
        saved=json.loads(journal.read_text());saved.update(runtime_retries=3,runtime_retry_after=0)
        journal.write_text(json.dumps(saved))
        self.run_adapter('apply')
        self.assertEqual(len(count.read_text().splitlines()), 2)
        self.assertTrue(json.loads(self.run_adapter('status').stdout)['runtime_retry_exhausted'])
        self.native()
        self.env['ADZERO_ADAPTER_REFRESH']='1'
        self.run_adapter('apply')
        self.assertEqual(len(count.read_text().splitlines()), 3)
        self.assertEqual(json.loads(self.run_adapter('status').stdout)['runtime']['state'], 'ready')
        self.assertFalse(json.loads(self.run_adapter('status').stdout)['runtime_retry_exhausted'])
        self.run_adapter('remove')
        self.assertFalse((self.root/'etc/adzero/adapter.json').exists())

    def test_nondefault_acl_process_is_not_default_dns_proof(self):
        self.native()
        self.run_adapter('apply')
        self.write('proc/100/cmdline', '/tmp/etc/passwall/bin/dnsmasq_other\0-C\0/tmp/etc/passwall/acl/default/dnsmasq.conf\0')
        self.assertEqual(json.loads(self.run_adapter('status').stdout)['runtime']['reason'], 'dns_process_missing')

    def test_large_generated_fragments_are_not_read_again_each_tick(self):
        _, fragment, _=self.native()
        self.run_adapter('apply')
        fragment.write_text(fragment.read_text()+'# padding\n'*200000)
        module=ROOT/'luci-app-adzero/root/usr/libexec/adzero/proxy-state.uc'
        script=self.write('cache-probe.uc',"import * as fs from 'fs';\nimport * as p from '"+str(module)+"';\nlet reads=0;let check=p.dns_runtime('"+str(self.root)+"','passwall',(path,size)=>{reads++;return fs.readfile(path,size);});\nfor(let n=0;n<10;n++)if(check(['ads.example','track.example']).state!='ready')die('not ready');print(reads);\n")
        p=subprocess.run(UCODE+[str(script)],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(p.stdout,'1')

    def test_children_are_blocked_without_enabling_automatic_routing(self):
        self.write('etc/passwall/rules/direct_host', 'sub.ads.example\nnormal.example\n')
        self.run_adapter('apply')
        text=(self.root/'etc/passwall/rules/block_host').read_text()
        self.assertIn('sub.ads.example\n', text)
        self.assertNotIn('normal.example', text)

    def test_non_dnsmasq_mode_reports_unverified_instead_of_restart_loop(self):
        _, _, count=self.native()
        self.write('etc/config/passwall', "config global\n option enabled '1'\n option dns_shunt 'smartdns'\n")
        self.run_adapter('apply')
        self.assertEqual(json.loads(self.run_adapter('status').stdout)['runtime']['state'], 'unknown')
        self.run_adapter('apply')
        self.assertEqual(len(count.read_text().splitlines()), 1)

    def test_sigchld_health_is_rechecked_even_when_rules_are_cached(self):
        self.native();self.run_adapter('apply')
        self.write('proc/100/status','SigBlk:\t0000000000010000\n')
        value=json.loads(self.run_adapter('status').stdout)['runtime']
        self.assertEqual(value,dict(state='degraded',reason='dns_sigchld_blocked'))
        self.write('proc/100/status','SigBlk:\t0000000000000000\n')
        self.assertEqual(json.loads(self.run_adapter('status').stdout)['runtime']['state'],'ready')

    def test_chinadns_native_chain_requires_process_forward_and_block_group(self):
        self.native()
        self.write('etc/config/passwall',"config global\n option enabled '1'\n option dns_shunt 'chinadns-ng'\n")
        conf=self.root/'tmp/etc/passwall/acl/default/dnsmasq.conf'
        self.write('proc/101/comm','chinadns-ng\n')
        self.write('proc/101/stat','101 (chinadns-ng) S 1 '+'0 '*19+'\n')
        self.write('proc/101/cmdline','/tmp/etc/passwall/bin/chinadns-ng\0-C\0/tmp/etc/passwall/acl/default/chinadns_ng.conf\0')
        self.write('tmp/etc/passwall/acl/default/chinadns_ng.conf','bind-port 15354\ngroup null\ngroup-dnl /tmp/etc/passwall_tmp/user_rules/block_host\n')
        cache=self.write('tmp/etc/passwall_tmp/user_rules/block_host','ads.example\ntrack.example\n')
        self.write('etc/init.d/passwall','#!/bin/sh\nprintf "port=11400\\nserver=127.0.0.1#15354\\n" > '+shlex.quote(str(conf))+'\nprintf "ads.example\\ntrack.example\\n" > '+shlex.quote(str(cache))+'\n')
        self.run_adapter('apply')
        value=json.loads(self.run_adapter('status').stdout)
        self.assertEqual(value['runtime']['state'],'ready')
        self.assertIn("dns_shunt 'chinadns-ng'",(self.root/'etc/config/passwall').read_text())
        cache.write_text('old.example\n')
        self.assertEqual(json.loads(self.run_adapter('status').stdout)['runtime']['reason'],'rules_stale')
        (self.root/'proc/101/cmdline').unlink()
        self.assertEqual(json.loads(self.run_adapter('status').stdout)['runtime']['reason'],'chinadns_process_missing')

    def test_only_block_cache_is_invalidated_and_noop_keeps_it(self):
        self.run_adapter('apply')
        source=self.root/'var/run/adblock-fast/dnsmasq.servers'
        cache=self.write('tmp/etc/passwall_tmp/user_rules/block_host','old.example\n')
        marker=self.write('tmp/etc/passwall_tmp/user_rules/block_host_ok','')
        other=self.write('tmp/etc/passwall_tmp/user_rules/direct_host','keep.example\n')
        self.run_adapter('apply')
        self.assertTrue(cache.exists())
        source.write_text(source.read_text()+'server=/new.example/\n')
        self.run_adapter('apply')
        self.assertFalse(cache.exists());self.assertFalse(marker.exists())
        self.assertEqual(other.read_text(),'keep.example\n')


@unittest.skipUnless(UCODE, 'requires native OpenWrt ucode')
class SSRPlusAdapterTest(unittest.TestCase):
    write = fixtures.AdapterTransactionTest.write
    run_adapter = fixtures.AdapterTransactionTest.run_adapter
    select = fixtures.AdapterTransactionTest.select

    def setUp(self):
        fixtures.AdapterTransactionTest.setUp(self)
        self.select('ssrplus')
        self.write('etc/config/shadowsocksr', "config global 'main'\n option global_server 'chosen'\nconfig servers 'chosen'\n option type 'ss'\n")
        self.write('usr/share/shadowsocksr/gfw2ipset.sh', '# /etc/ssrplus/deny.list -> denylist.conf\n')
        self.write('etc/init.d/shadowsocksr', '#!/bin/sh\necho restart >> '+shlex.quote(str(self.root/'ssr-restarts'))+'\n')

    def test_apply_repeat_update_remove_preserves_original_list_and_node(self):
        path=self.write('etc/ssrplus/deny.list', 'user.example\n')
        original=(self.root/'etc/config/shadowsocksr').read_text()
        self.write('etc/ssrplus/gfw_list.conf', 'server=/sub.ads.example/127.0.0.1#5335\n')
        self.run_adapter('apply');self.run_adapter('apply')
        self.assertIn('sub.ads.example\n',path.read_text())
        self.assertEqual((self.root/'ssr-restarts').read_text().splitlines(),['restart'])
        self.assertEqual((self.root/'etc/config/shadowsocksr').read_text(),original)
        self.write('var/run/adblock-fast/dnsmasq.servers', 'server=/new.example/\n')
        self.run_adapter('apply')
        self.assertIn('new.example',path.read_text());self.assertNotIn('ads.example',path.read_text())
        self.run_adapter('remove')
        self.assertEqual(path.read_text(),'user.example\n')

    def test_split_and_unknown_native_interface_are_rejected_before_writes(self):
        config=self.write('etc/config/adzero', "config adzero 'main'\n option routing_enabled '1'\n")
        self.run_adapter('apply',success=False)
        self.assertFalse((self.root/'etc/adzero/adapter.json').exists())
        self.run_adapter('routing-check','0')
        config.write_text("config adzero 'main'\n option routing_enabled '0'\n")
        self.write('usr/share/shadowsocksr/gfw2ipset.sh','# incompatible version\n')
        self.run_adapter('apply',success=False)
        self.assertFalse((self.root/'etc/adzero/adapter.json').exists())

    def test_restoring_a_stopped_plugin_does_not_start_it(self):
        self.run_adapter('apply')
        self.inventory.write_text(json.dumps({'plugins':[{'id':'ssrplus','installed':True,'enabled':False,'runtime':'stopped'}]}))
        self.run_adapter('remove')
        self.assertEqual((self.root/'ssr-restarts').read_text().splitlines(),['restart'])
