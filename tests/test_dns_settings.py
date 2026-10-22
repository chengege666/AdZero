"""Editable resolver profiles with actual UCI/ucode and isolated services."""
import copy
import json
import os
from pathlib import Path
import subprocess
import unittest
import test_routing as routing
import test_sources as sources

CUSTOM={'domestic':{'servers':['119.29.29.29','223.5.5.5'],'active':'119.29.29.29'},
        'foreign':{'servers':['8.8.8.8','1.1.1.1'],'active':'8.8.8.8'}}

@unittest.skipUnless(routing.UCODE,'requires actual OpenWrt ucode')
class DNSCompilerTest(unittest.TestCase):
    compile=routing.RoutingCompilerTest.compile

    def test_defaults_and_editable_address_library(self):
        default=self.compile('profile',None)
        self.assertEqual(default['domestic']['active'],'223.5.5.5')
        self.assertEqual(self.compile('profile',CUSTOM),CUSTOM)
        ipv6=copy.deepcopy(CUSTOM);ipv6['foreign']={'servers':['2606:4700:4700::1111'],'active':'2606:4700:4700::1111'}
        self.assertEqual(self.compile('profile',ipv6),ipv6)

    def test_invalid_or_ambiguous_dns_does_not_compile(self):
        for value in ['https://dns.example/dns-query','127.0.0.1','0.0.0.0','::1','::','ff02::1','999.1.2.3','1::2::3','1.1.1.1;id']:
            p=copy.deepcopy(CUSTOM);p['foreign']={'servers':[value],'active':value}
            with self.subTest(value=value):self.compile('profile',p,ok=False)
        for addresses,active in [([],''),(['1.1.1.1']*2,'1.1.1.1'),(['1.1.1.1'],'8.8.8.8')]:
            p=copy.deepcopy(CUSTOM);p['foreign']={'servers':addresses,'active':active};self.compile('profile',p,ok=False)

    def test_dae_dns_and_transport_use_selected_addresses_only(self):
        raw='upstream { local: "udp://223.5.5.5:53" }\nrouting { request { fallback: local } }'
        dns=self.compile('dae_dns',raw,CUSTOM)
        self.assertIn('adzero_cn: "udp://119.29.29.29:53"',dns)
        self.assertIn('adzero_global: "tcp://8.8.8.8:53"',dns)
        route=self.compile('dae_routing','fallback: proxy\n','proxy',CUSTOM)
        self.assertIn('dip(8.8.8.8) && dport(53) -> proxy',route)
        self.assertIn('dip(119.29.29.29) && dport(53) -> direct',route)

    def test_mihomo_and_ipv6_endpoints_use_selected_profile(self):
        cfg={'dns':{'enable':True},'rules':['MATCH,Proxy'],'proxy-groups':[{'name':'Proxy'}]}
        p=copy.deepcopy(CUSTOM);p['foreign']={'servers':['2606:4700:4700::1111'],'active':'2606:4700:4700::1111'}
        result=self.compile('mihomo',cfg,'/domains','/cidrs',p)['config']
        self.assertEqual(result['dns']['nameserver'],['tcp://[2606:4700:4700::1111]:53#Proxy'])
        self.assertEqual(result['dns']['direct-nameserver'],['119.29.29.29'])

@unittest.skipUnless(routing.UCODE,'requires actual OpenWrt ucode')
class DNSSettingsTest(unittest.TestCase):
    setUp=routing.RoutingControllerTest.setUp
    nailink=routing.RoutingControllerTest.nailink

    def plan(self,profile=CUSTOM):
        data=json.loads(self.fixture.ctl('sources-list').stdout)
        body={k:data[k] for k in ['revision','items']}
        body['items']=[{k:i[k] for k in ['id','name','url','format','enabled']} for i in data['items']]
        flag=self.fixture.status()['policy']['routing_enabled']
        body.update(routing_before=flag,routing_enabled=flag,dns_before=data['dns'],dns=profile)
        return self.fixture.write('dns-plan.json',json.dumps(body))

    def test_disabled_edit_is_saved_and_survives_reopen(self):
        f=self.fixture;plan=self.plan();f.ctl('settings-apply',str(plan))
        self.assertEqual(json.loads(f.ctl('sources-list').stdout)['dns'],CUSTOM)
        self.assertEqual(f.status()['state'],'disabled')
        self.assertFalse((self.root/'etc/adzero/adapter.json').exists())

    def test_nailink_dns_only_edit_uses_one_reload_and_no_backend_restart(self):
        f=self.fixture;p=self.nailink();f.ctl('enable');f.ctl('routing-on')
        plan=self.plan();before=json.loads(p.read_text())
        backend=Path(f.env['ADZERO_BACKEND_INIT']);backend.write_text('#!/bin/sh\necho called > "'+str(self.root/'backend-called')+'"\nexit 77\n')
        f.ctl('settings-apply',str(plan));after=json.loads(p.read_text())
        self.assertEqual(after['runs'],before['runs']+1)
        self.assertIn('tcp://8.8.8.8:53',after['dns']['dns']['string'])
        self.assertIn('dip(119.29.29.29) && dport(53) -> direct',after['traffic']['routing']['string'])
        self.assertFalse((self.root/'backend-called').exists())
        self.assertFalse((self.root/'etc/adzero/sources-pending.json').exists())

    def test_dns_edit_with_split_off_saves_without_reloading_proxy(self):
        f=self.fixture;p=self.nailink();f.ctl('enable');before=p.read_bytes()
        f.ctl('settings-apply',str(self.plan()))
        self.assertEqual(before,p.read_bytes());f.ctl('reconcile');self.assertEqual(before,p.read_bytes())
        f.ctl('routing-on');self.assertIn('tcp://8.8.8.8:53',p.read_text())

    def test_no_proxy_uses_only_selected_domestic_dns_and_restores_system(self):
        f=self.fixture;before=subprocess.check_output([f.env['ADZERO_UCI'],'export','dhcp'])
        plan=self.plan();body=json.loads(plan.read_text());body['routing_enabled']=True;plan.write_text(json.dumps(body))
        f.ctl('settings-apply',str(plan));f.ctl('enable')
        text=(self.root/'etc/config/dhcp').read_text()
        self.assertIn('119.29.29.29',text);self.assertNotIn('8.8.8.8',text)
        f.ctl('disable');self.assertEqual(before,subprocess.check_output([f.env['ADZERO_UCI'],'export','dhcp']))

    def test_backup_library_edit_does_not_reload_now_or_during_reconcile(self):
        f=self.fixture;p=self.nailink();f.ctl('enable');f.ctl('routing-on');before=p.read_bytes()
        profile=json.loads(f.ctl('sources-list').stdout)['dns'];profile['foreign']['servers'].append('9.9.9.9')
        f.ctl('settings-apply',str(self.plan(profile)));f.ctl('reconcile')
        self.assertEqual(p.read_bytes(),before)
        self.assertEqual(json.loads(f.ctl('sources-list').stdout)['dns'],profile)

    def test_concurrent_dns_edit_is_rejected_without_overwriting(self):
        f=self.fixture;plan=self.plan()
        other=copy.deepcopy(CUSTOM);other['foreign']['active']='1.1.1.1'
        subprocess.run([f.env['ADZERO_UCI'],'set','adzero.main.dns_profile='+json.dumps(other)],check=True)
        subprocess.run([f.env['ADZERO_UCI'],'commit','adzero'],check=True)
        f.ctl('settings-apply',str(plan),ok=False)
        self.assertEqual(json.loads(f.ctl('sources-list').stdout)['dns'],other)

    def test_failed_dns_edit_restores_old_profile_and_both_nailink_profiles(self):
        f=self.fixture;p=self.nailink();f.ctl('enable');f.ctl('routing-on')
        plan=self.plan();before=json.loads(p.read_text());old=json.loads(f.ctl('sources-list').stdout)['dns']
        f.write('fail-route-once','1');f.ctl('settings-apply',str(plan),ok=False)
        after=json.loads(p.read_text());self.assertEqual(after['dns'],before['dns']);self.assertEqual(after['traffic'],before['traffic'])
        self.assertEqual(json.loads(f.ctl('sources-list').stdout)['dns'],old)
        self.assertEqual(f.status()['state'],'configured_unverified')

@unittest.skipUnless(sources.UCODE,'requires actual OpenWrt ucode')
class ManualValidationTest(unittest.TestCase):
    def setUp(self):
        self.s=sources.SourcesTest();self.s.setUp();self.addCleanup(self.s.doCleanups)
        self.f=self.s.fixture;self.root=self.s.root

    def test_manual_validation_uses_local_snapshot_without_download_or_reload(self):
        self.s.add();self.s.run_source('finish');self.f.ctl('enable')
        item=self.s.data()['items'][0]
        subprocess.run([self.f.env['ADZERO_UCI'],'set',f"adblock-fast.{item['id']}.adzero_domains=99"],check=True)
        subprocess.run([self.f.env['ADZERO_UCI'],'commit','adblock-fast'],check=True)
        before=(self.root/'etc/adzero/adapter.json').read_bytes();fetches=(self.root/'fetch-count').read_text() if (self.root/'fetch-count').exists() else None
        self.f.write('fetch-fail','1');Path(self.f.env['ADZERO_BACKEND_INIT']).write_text('#!/bin/sh\nexit 77\n')
        self.f.ctl('source-verify')
        self.assertEqual(self.s.data()['items'][0]['domains'],2)
        self.assertEqual(before,(self.root/'etc/adzero/adapter.json').read_bytes())
        self.assertEqual(fetches,(self.root/'fetch-count').read_text() if (self.root/'fetch-count').exists() else None)

    def test_missing_or_corrupt_local_snapshot_is_not_reported_valid(self):
        self.s.add();self.s.run_source('finish')
        for body in (self.root/'tmp/adzero-source-cache').glob('*.body'):body.write_text('<html>error</html>')
        before=(self.root/'etc/config/adblock-fast').read_bytes()
        self.f.ctl('source-verify',ok=False);self.assertEqual(before,(self.root/'etc/config/adblock-fast').read_bytes())

    def test_unchanged_refresh_reuses_small_receipt_and_original_check_time(self):
        self.s.add();self.s.run_source('finish');item=self.s.data()['items'][0]
        subprocess.run([self.f.env['ADZERO_UCI'],'set',f"adblock-fast.{item['id']}.adzero_updated=1"],check=True)
        subprocess.run([self.f.env['ADZERO_UCI'],'commit','adblock-fast'],check=True)
        parsed=next((self.root/'tmp/adzero-source-cache').glob('*.parsed'));before=parsed.stat().st_mtime_ns
        self.s.run_source('begin','refresh');self.s.run_source('finish')
        self.assertEqual(self.s.data()['items'][0]['updated'],1)
        self.assertEqual(parsed.stat().st_mtime_ns,before)

    def test_manual_check_metadata_does_not_force_download_on_next_enable(self):
        self.s.add();self.s.run_source('finish');self.f.ctl('enable');self.f.ctl('source-verify')
        self.f.ctl('disable');self.f.write('fetch-fail','1');self.f.ctl('enable')
        self.assertEqual((self.root/'last-start-method').read_text(),'start')

    def test_legacy_snapshot_gets_a_small_receipt_without_rewriting_large_files(self):
        self.s.add();self.s.run_source('finish')
        cache=self.root/'tmp/adzero-source-cache';proof=next(cache.glob('*.proof'));p=json.loads(proof.read_text());p.pop('summary');proof.write_text(json.dumps(p))
        files={q:q.stat().st_mtime_ns for q in cache.iterdir() if q.suffix in ('.body','.parsed')}
        self.s.run_source('begin','refresh');self.s.run_source('finish')
        self.assertEqual(json.loads(proof.read_text())['summary']['domains'],2)
        self.assertTrue(all(q.stat().st_mtime_ns==mtime for q,mtime in files.items()))
