"""Real ucode policy compilation; service, router and packet checks are separate."""
import base64
import ipaddress
import json
import os
import shutil
from pathlib import Path
import shlex
import subprocess
import unittest
import test_adapters as adapters
import test_controls as controls

ROOT=Path(__file__).resolve().parents[1]
UCODE=shlex.split(os.environ.get('ADZERO_UCODE',''))

@unittest.skipUnless(UCODE,'requires actual OpenWrt ucode')
class RoutingCompilerTest(unittest.TestCase):
    def compile(self,operation,*args,ok=True):
        p=subprocess.run(UCODE+[str(ROOT/'scripts/routing_transform.uc')],input=json.dumps({'operation':operation,'arguments':args}),text=True,capture_output=True)
        self.assertEqual(p.returncode==0,ok,p.stdout+p.stderr)
        return json.loads(p.stdout) if ok else None

    def test_domain_source_extracts_only_domains_not_the_supplied_server(self):
        self.assertEqual(self.compile('domain_list','# source\nserver=/example.cn/114.114.114.114\nserver=/cn/114.114.114.114\nserver=/example.cn/114.114.114.114\n'),['cn','example.cn'])
        for raw in ('server=/bad;command.cn/114.114.114.114','<html>','server=/bad..cn/1.1.1.1','server=/123/1.1.1.1',''):
            self.compile('domain_list',raw,ok=False)

    def test_cidr_v4_v6_and_network_boundaries(self):
        raw='223.5.5.0/24\n2400:3200::/32\n::1/128\n'
        self.assertEqual(self.compile('cidr_list',raw),sorted(raw.splitlines()))
        for invalid in ('0.0.0.0/0','256.0.0.0/8','223.5.5.1/24','2400::1/32','1::2::/48','::/129','::gg/64','1.2.3/24'):
            self.compile('cidr_list',invalid,ok=False)

    def test_geoip_protobuf_contains_ipv4_and_ipv6(self):
        blob=base64.b64decode(self.compile('geoip',['223.5.5.0/24','2400:3200::/32']))
        self.assertIn(b'ADZERO',blob)
        for addr in ('223.5.5.0','2400:3200::'):self.assertIn(ipaddress.ip_address(addr).packed,blob)

    def test_passwall_specific_domestic_rules_cannot_escape_parent_blockers(self):
        self.assertEqual(self.compile('expand_blockers',['ads.example'],['sub.ads.example','deep.sub.ads.example','notads.example','www.cn.example']),['ads.example','deep.sub.ads.example','sub.ads.example'])

    def test_dae_dns_preserves_existing_exceptions_and_adds_both_groups(self):
        raw='upstream { local: "udp://127.0.0.1:5353" }\nrouting { request { qname(user.example) -> local\n fallback: local } response { fallback: accept } }'
        result=self.compile('dae_dns',raw)
        self.assertIn('qname(user.example) -> local',result)
        self.assertIn('adzero_global: "tcp://1.1.1.1:53"',result)
        self.assertIn('upstream(adzero_cn, adzero_global) -> accept',result)
        self.assertLess(result.index('qname(user.example)'),result.index('qname(ext:'))
        self.assertEqual(self.compile('dae_dns',result),result)
        self.compile('dae_dns','routing { request { fallback: asis } }',ok=False)

    def test_dae_routes_preserve_explicit_rules_and_force_dns_transport(self):
        raw='domain(full: user.example) -> direct\nfallback: proxy\n'
        result=self.compile('dae_routing',raw,'proxy')
        self.assertIn('dip(1.1.1.1) && dport(53) -> proxy',result)
        self.assertIn('dip(ext:"adzero-cn-geoip.dat:adzero") -> direct',result)
        self.assertLess(result.index('user.example'),result.index('domain(ext:'))
        self.assertLess(result.index('domain(ext:'),result.index('fallback:'))
        for target in ('DIRECT','direct','',None):
            if target=='DIRECT':continue
            self.compile('dae_routing',raw,target,ok=False)

    def test_mihomo_policy_and_actual_connection_rules_share_the_target(self):
        original={'mode':'global','dns':{'enable':True,'nameserver':['8.8.8.8'],'fallback':['9.9.9.9'],'nameserver-policy':{'+.user.example':['192.168.1.1']},'fake-ip-filter':['+.lan']},'proxy-groups':[{'name':'My Proxy','type':'select','proxies':['node']}],'rules':['DOMAIN,user.example,DIRECT','MATCH,My Proxy']}
        result=self.compile('mihomo',original,'/tmp/cn-domains.txt','/tmp/cn-ips.txt')
        self.assertEqual(result['target'],'My Proxy')
        config=result['config'];self.assertEqual(config['mode'],'rule')
        self.assertEqual(config['rules'][0],'DOMAIN,user.example,DIRECT')
        self.assertEqual(config['rules'][-1],'MATCH,My Proxy')
        self.assertIn('RULE-SET,adzero-cn-domain,DIRECT',config['rules'])
        self.assertEqual(config['dns']['nameserver'],['tcp://1.1.1.1:53#My Proxy'])
        self.assertEqual(config['dns']['direct-nameserver'],['223.5.5.5','119.29.29.29'])
        self.assertNotIn('fallback',config['dns'])
        self.assertEqual(config['dns']['nameserver-policy']['+.user.example'],['192.168.1.1'])
        self.assertIn('+.lan',config['dns']['fake-ip-filter'])
        self.assertEqual(self.compile('mihomo',config,'/tmp/cn-domains.txt','/tmp/cn-ips.txt')['config'],config)

    def test_mihomo_does_not_guess_an_absent_or_direct_proxy_target(self):
        for target in ('DIRECT','REJECT','missing'):
            self.compile('mihomo',{'dns':{'enable':True},'rules':['MATCH,'+target]},'/tmp/cn.txt','/tmp/ip.txt',ok=False)

@unittest.skipUnless(UCODE,'requires actual OpenWrt ucode')
class RoutingAdapterTest(unittest.TestCase):
    setUp=adapters.AdapterTransactionTest.setUp
    write=adapters.AdapterTransactionTest.write
    run_adapter=adapters.AdapterTransactionTest.run_adapter
    def select(self,*plugins):
        adapters.AdapterTransactionTest.select(self,*plugins)
        self.write('etc/config/adzero',"config adzero 'main'\n option enabled '1'\n option routing_enabled '1'\n")
        self.write('etc/config/dhcp',"config dnsmasq 'main'\n list server '8.8.8.8'\n list server '/lan/192.168.1.1'\n")
        fixture=self.write('routing-fixture.json',json.dumps({'domain_raw':'server=/cn.example/114.114.114.114\n','cidr_raw':'223.5.5.0/24\n2400:3200::/32\n'}))
        self.env['ADZERO_ROUTING_DATA_FIXTURE']=str(fixture)
        self.env['ADZERO_ROUTING_DATA_PROGRAM']=str(ROOT/'luci-app-adzero/root/usr/libexec/adzero/routing-data')
        self.env['ADZERO_UCODE']=shlex.join(UCODE)
        self.write('etc/init.d/dnsmasq','#!/bin/sh\nexit 0\n')
        self.write('etc/config/passwall',"config global 'main'\n option enabled '1'\n option node 'chosen'\n option dns_mode 'xray'\n option chn_list '0'\nconfig nodes 'chosen'\n option type 'Xray'\n")
        self.write('usr/share/passwall/app.sh','# direct_dns_mode USE_DEFAULT_DNS\n')
        self.write('usr/share/passwall/rules/chnlist','cn.example\n')
        self.write('usr/share/passwall/rules/chnroute','223.5.5.0/24\n')

    def test_no_proxy_uses_only_domestic_defaults_and_restores_original_dns(self):
        self.select()
        before=(self.root/'etc/config/dhcp').read_text()
        self.run_adapter('apply');self.run_adapter('apply')
        text=(self.root/'etc/config/dhcp').read_text()
        self.assertNotIn('8.8.8.8',text);self.assertIn('223.5.5.5',text);self.assertIn('/lan/192.168.1.1',text)
        self.assertEqual(json.loads(self.run_adapter('status').stdout)['routing']['mode'],'direct')
        self.run_adapter('remove')
        after=(self.root/'etc/config/dhcp').read_text()
        self.assertIn('8.8.8.8',after);self.assertNotIn('223.5.5.5',after);self.assertNotIn('noresolv',after)

    def test_direct_mode_rejects_multiple_dnsmasq_instances_without_mutating(self):
        self.select();p=self.root/'etc/config/dhcp';p.write_text(p.read_text()+"config dnsmasq 'other'\n")
        original=p.read_text();self.run_adapter('apply',success=False);self.assertEqual(p.read_text(),original)

    def test_passwall_updates_dns_and_connection_flags_without_replacing_node(self):
        self.run_adapter('apply')
        after=(self.root/'etc/config/passwall').read_text()
        for expected in ("option chn_list 'direct'","option use_default_dns 'remote'","option direct_dns '223.5.5.5:53'","option remote_dns '1.1.1.1:53'","option node 'chosen'"):self.assertIn(expected,after)
        self.run_adapter('remove');restored=(self.root/'etc/config/passwall').read_text()
        self.assertIn("option chn_list '0'",restored);self.assertNotIn('use_default_dns',restored)

    def test_passwall_missing_country_data_is_not_success(self):
        (self.root/'usr/share/passwall/rules/chnroute').unlink()
        self.run_adapter('apply',success=False)
        self.assertNotIn('remote_dns',(self.root/'etc/config/passwall').read_text())

    def test_stopped_passwall_restores_then_uses_domestic_dns_without_restarting_proxy(self):
        counter=self.root/'restarts'
        self.write('etc/init.d/passwall','#!/bin/sh\necho restart >> '+shlex.quote(str(counter))+'\n')
        self.run_adapter('apply')
        inventory=Path(self.env['ADZERO_ADAPTER_INVENTORY'])
        data=json.loads(inventory.read_text());data['plugins'][0]['runtime']='stopped';inventory.write_text(json.dumps(data))
        self.run_adapter('apply')
        self.assertEqual(counter.read_text().splitlines(),['restart'])
        self.assertNotIn('remote_dns',(self.root/'etc/config/passwall').read_text())
        self.assertEqual(json.loads(self.run_adapter('status').stdout)['routing']['mode'],'direct')
        self.assertIn('223.5.5.5',(self.root/'etc/config/dhcp').read_text())

    def test_restore_retains_later_manual_passwall_route_choice(self):
        self.run_adapter('apply')
        path=self.root/'etc/config/passwall'
        path.write_text(path.read_text().replace("option chn_list 'direct'","option chn_list 'proxy'"))
        self.run_adapter('remove')
        self.assertIn("option chn_list 'proxy'",path.read_text())

    def test_nailink_updates_both_profiles_and_restores_without_starting_stopped_core(self):
        self.select('nailink')
        p=self.write('profiles.json',json.dumps({'dns':{'id':'dns','dns':{'string':'upstream { local: "udp://223.5.5.5:53" }\nrouting { request { fallback: local } response { fallback: accept } }'}},'traffic':{'id':'route','routing':{'string':'domain(full: user.example) -> direct\nfallback: proxy\n','fallback':{'val':'proxy'}}},'running':True,'runs':0}))
        api=self.write('bin/api','''#!/usr/bin/env python3
import json,sys
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'profiles.json';data=json.loads(p.read_text());r=json.loads(Path(sys.argv[1]).read_text());q=r['query'];v=r['variables']
if 'general{' in q:out={'general':{'dae':{'running':data['running']}}}
elif 'routings(' in q:out={'routings':[data['traffic']],'groups':[{'name':'proxy'}]}
elif 'dnss(' in q:out={'dnss':[data['dns']]}
elif 'updateDns' in q:data['dns']['dns']['string']=v['dns'];out={'updateDns':{'id':'dns'}}
elif 'updateRouting' in q:data['traffic']['routing']['string']=v['routing'];out={'updateRouting':{'id':'route'}}
elif 'run(dry:false)' in q:data['running']=True;data['runs']+=1;out={'run':0}
else:out={}
p.write_text(json.dumps(data));print(json.dumps(out))
''');api.chmod(0o755);self.env['ADZERO_NAILINK_API_FIXTURE']=str(api)
        before=json.loads(p.read_text());self.run_adapter('apply');after=json.loads(p.read_text())
        self.assertIn('adzero_global',after['dns']['dns']['string']);self.assertIn('adzero-cn-geoip.dat',after['traffic']['routing']['string'])
        self.run_adapter('apply');self.assertEqual(json.loads(p.read_text())['runs'],after['runs'])
        stopped=json.loads(p.read_text());stopped['running']=False;p.write_text(json.dumps(stopped))
        self.run_adapter('apply');restored=json.loads(p.read_text())
        self.assertFalse(restored['running']);self.assertEqual(restored['dns'],before['dns']);self.assertEqual(restored['traffic'],before['traffic'])
        self.assertEqual(json.loads(self.run_adapter('status').stdout)['routing']['mode'],'direct')

    @unittest.skipUnless(shutil.which('yq'),'real yq required')
    def test_nikki_split_is_idempotent_and_preserves_custom_exceptions(self):
        self.select('nikki')
        self.write('etc/config/nikki',"config nikki 'config'\n option enabled '1'\nconfig mixin 'mixin'\n option mixin_file_content '1'\n option dns_nameserver '1'\n option dns_nameserver_policy '1'\n option mode 'global'\n")
        mixin=self.write('etc/nikki/mixin.yaml',json.dumps({'nikki-rules':['DOMAIN,user.cn.example,My Proxy']}))
        before=mixin.read_bytes()
        base=self.write('etc/nikki/base.json',json.dumps({'mode':'global','dns':{'enable':True,'nameserver':['8.8.8.8'],'nameserver-policy':{'+.user.example':['192.168.1.1']},'fake-ip-filter':['+.lan']},'proxy-groups':[{'name':'My Proxy','type':'select','proxies':['node']}],'rules':['MATCH,My Proxy']}))
        run=self.write('etc/nikki/run/config.yaml',base.read_text())
        counter=self.root/'restarts'
        script='#!/bin/sh\necho restart >> '+shlex.quote(str(counter))+'\nyq -o=json eval-all \'. as $item ireduce ({}; . * $item ) | .rules = .nikki-rules + .rules | del(.nikki-rules)\' '+shlex.join([str(base),str(mixin)])+' > '+shlex.quote(str(run))+'\n'
        self.write('etc/init.d/nikki',script)
        self.run_adapter('apply');after=json.loads(run.read_text())
        self.assertEqual(after['mode'],'rule');self.assertEqual(after['dns']['nameserver'],['tcp://1.1.1.1:53#My Proxy'])
        self.assertLess(after['rules'].index('DOMAIN,user.cn.example,My Proxy'),after['rules'].index('RULE-SET,adzero-cn-domain,DIRECT'))
        self.assertEqual(after['dns']['nameserver-policy']['+.user.example'],['192.168.1.1'])
        self.run_adapter('apply');self.assertEqual(counter.read_text().splitlines(),['restart'])
        self.run_adapter('remove');self.assertEqual(mixin.read_bytes(),before)
        self.assertIn("option dns_nameserver '1'",(self.root/'etc/config/nikki').read_text())

    @unittest.skipUnless(shutil.which('ruby'),'real Ruby required')
    def test_openclash_generated_config_contains_dns_and_connection_rules(self):
        self.select('openclash')
        custom=self.write('etc/openclash/custom/openclash_custom_overwrite.sh','#!/bin/sh\nexit 0\n')
        base=self.write('etc/openclash/source.json',json.dumps({'mode':'global','dns':{'enable':True,'nameserver':['8.8.8.8']},'proxy-groups':[{'name':'My Proxy','type':'select','proxies':['node']}],'rules':['DOMAIN,user.example,DIRECT','MATCH,My Proxy']}))
        run=self.root/'etc/openclash/config.yaml';self.write('etc/openclash/core/clash_meta','#!/bin/sh\nexit 0\n').chmod(0o755)
        adapter=UCODE+[str(ROOT/'luci-app-adzero/root/usr/libexec/adzero/adapter.uc'),'--','hook-openclash','/etc/openclash/config.yaml']
        self.write('etc/init.d/openclash','#!/bin/sh\ncp '+shlex.join([str(base),str(run)])+'\nif grep -q "ADZERO MANAGED BEGIN" '+shlex.quote(str(custom))+'; then\n'+shlex.join(adapter)+'\nfi\n')
        self.run_adapter('apply');config=json.loads(run.read_text())
        self.assertEqual(config['mode'],'rule');self.assertIn('RULE-SET,adzero-cn-domain,DIRECT',config['rules'])
        self.assertEqual(config['dns']['nameserver'],['tcp://1.1.1.1:53#My Proxy'])
        self.run_adapter('remove');self.assertEqual(json.loads(run.read_text()),json.loads(base.read_text()))

@unittest.skipUnless(UCODE,'requires actual OpenWrt ucode')
class RoutingControllerTest(unittest.TestCase):
    def setUp(self):
        self.fixture=controls.ControlsTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root
        self.fixture.write('inventory.json',json.dumps({'plugins':[],'dns':{'active_proxy_count':0}}))
        self.fixture.write('etc/config/dhcp',"config dnsmasq 'main'\n list server '8.8.8.8'\n")
        self.fixture.write('etc/init.d/dnsmasq','#!/bin/sh\nexit 0\n',True)

    def test_routing_toggle_preserves_filtering_and_restores_original_dns(self):
        f=self.fixture;f.ctl('enable');f.ctl('routing-on')
        s=f.status();self.assertEqual(s['state'],'configured_unverified');self.assertTrue(s['policy']['routing_enabled']);self.assertEqual(s['adapter']['routing']['mode'],'direct')
        self.assertEqual(f.query('ads.example')['match'],'exact')
        f.ctl('routing-off');self.assertFalse(f.status()['policy']['routing_enabled']);self.assertEqual(f.status()['state'],'configured_unverified')
        self.assertIn('8.8.8.8',(self.root/'etc/config/dhcp').read_text())
        self.assertFalse((self.root/'etc/adzero/routing-pending.json').exists())

    def test_pause_disable_and_reenable_keep_choice_but_restore_network(self):
        f=self.fixture;f.ctl('enable');f.ctl('routing-on');f.ctl('pause','300')
        self.assertEqual(f.status()['state'],'paused');self.assertIn('8.8.8.8',(self.root/'etc/config/dhcp').read_text())
        f.ctl('resume');self.assertEqual(f.status()['adapter']['routing']['mode'],'direct')
        f.ctl('disable');self.assertTrue(f.status()['policy']['routing_enabled']);self.assertEqual(f.status()['state'],'disabled')
        f.ctl('enable');self.assertEqual(f.status()['adapter']['routing']['mode'],'direct')

    def test_failed_dns_reload_rolls_back_preference_and_keeps_ad_filtering(self):
        f=self.fixture;f.ctl('enable');flag=f.write('fail-dns-once','1')
        f.write('etc/init.d/dnsmasq','#!/bin/sh\nif [ -f '+shlex.quote(str(flag))+' ]; then rm '+shlex.quote(str(flag))+'; exit 1; fi\nexit 0\n',True)
        f.ctl('routing-on',ok=False);s=f.status()
        self.assertFalse(s['policy']['routing_enabled']);self.assertEqual(s['state'],'configured_unverified');self.assertEqual(f.query('ads.example')['match'],'exact')
        self.assertIn('8.8.8.8',(self.root/'etc/config/dhcp').read_text());self.assertFalse((self.root/'etc/adzero/routing-pending.json').exists())

if __name__=='__main__':unittest.main()
