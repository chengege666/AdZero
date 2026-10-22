"""Real ucode/libuci source transactions, with a no-network downloader fixture."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import unittest
import test_controls

ROOT=test_controls.ROOT
UCODE=test_controls.UCODE
PROGRAM=ROOT/'luci-app-adzero/root/usr/libexec/adzero/sources.uc'

@unittest.skipUnless(UCODE,'requires actual OpenWrt ucode/UCI')
class SourcesTest(unittest.TestCase):
    def setUp(self):
        self.fixture=test_controls.ControlsTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root;self.env=self.fixture.env
        self.body=self.fixture.write('source-body','new-ads.example\nnew-track.example\n')
        fetch=self.fixture.write('bin/fetch','#!/bin/sh\n[ ! -f "$ADZERO_SOURCES_ROOT/fetch-fail" ] || exit 1\ncp "$ADZERO_SOURCES_ROOT/source-body" "$2"\n',True)
        self.env['ADZERO_SOURCE_FETCH_FIXTURE']=str(fetch)

    def run_source(self,*args,ok=True):
        p=subprocess.run(UCODE+[str(PROGRAM),'--',*args],env=self.env,text=True,capture_output=True,timeout=30)
        self.assertEqual(p.returncode==0,ok,p.stdout+p.stderr);return p
    def data(self): return json.loads(self.run_source('list').stdout)
    def add(self,**kwargs): return self.run_source('begin','add','',kwargs.get('name','My list'),kwargs.get('url','https://rules.example/list.txt'),kwargs.get('kind','domains'),ok=kwargs.get('ok',True))

    def test_add_offline_disabled_global_and_persist_explicit_choices(self):
        self.add();data=self.data();self.assertEqual(data['items'][0]['domains'],2);self.assertTrue(data['pending'])
        self.run_source('finish');self.assertFalse(self.data()['pending'])
        self.assertTrue((self.root/'etc/adzero/sources-selected').exists())
        self.assertEqual(self.fixture.status()['state'],'disabled')
        self.fixture.ctl('disable');self.assertEqual(len(self.data()['items']),1)

    def test_duplicate_and_stale_url_are_rejected(self):
        self.add();self.run_source('finish');self.add(ok=False)
        item=self.data()['items'][0]
        self.run_source('begin','remove',item['id'],'https://changed.example/list',ok=False)
        self.assertEqual(len(self.data()['items']),1)

    def test_disabling_or_removing_a_source_does_not_redownload_unchanged_sources_for_precheck(self):
        self.add();self.run_source('finish');item=self.data()['items'][0]
        self.fixture.write('fetch-fail','1')
        self.run_source('begin','toggle',item['id'],item['url'],'0');self.run_source('finish')
        self.assertFalse(self.data()['items'][0]['enabled'])
        self.run_source('begin','remove',item['id'],item['url']);self.run_source('finish')
        self.assertEqual(self.data()['items'],[])

    def test_add_and_enable_precheck_only_the_changed_source(self):
        fetch=self.fixture.write('bin/fetch','#!/bin/sh\necho "$1" >> "$ADZERO_SOURCES_ROOT/fetches"\ncp "$ADZERO_SOURCES_ROOT/source-body" "$2"\n',True)
        self.env['ADZERO_SOURCE_FETCH_FIXTURE']=str(fetch)
        self.add();self.run_source('finish')
        self.add(url='https://second.example/list');self.run_source('finish')
        log=self.root/'fetches'
        self.assertEqual(log.read_text().splitlines(),['https://rules.example/list.txt','https://second.example/list'])
        item=self.data()['items'][1]
        self.run_source('begin','toggle',item['id'],item['url'],'0');self.run_source('finish')
        self.run_source('begin','toggle',item['id'],item['url'],'1');self.run_source('finish')
        self.assertEqual(log.read_text().splitlines()[-1],item['url'])
        self.assertEqual(len(log.read_text().splitlines()),2)
        self.run_source('begin','refresh');self.run_source('finish')
        self.assertEqual(len(log.read_text().splitlines()),4)

    def test_toggle_and_remove_restore_original_exact_config(self):
        original=(self.root/'etc/config/adblock-fast').read_bytes()
        self.add();self.run_source('rollback');self.run_source('rollback');self.run_source('discard')
        self.assertEqual((self.root/'etc/config/adblock-fast').read_bytes(),original)
        self.add();self.run_source('finish');item=self.data()['items'][0]
        self.run_source('begin','toggle',item['id'],item['url'],'0');self.run_source('finish')
        self.assertFalse(self.data()['items'][0]['enabled'])
        self.run_source('begin','remove',item['id'],item['url']);self.run_source('finish');self.assertEqual(self.data()['items'],[])

    def test_invalid_download_does_not_commit_any_changes(self):
        original=(self.root/'etc/config/adblock-fast').read_bytes()
        for raw in ['', '<html>error</html>','@@||allowed.example^\n','ads.example\nexample.com##.ad']:
            self.body.write_text(raw);self.add(ok=False)
            self.assertEqual((self.root/'etc/config/adblock-fast').read_bytes(),original)
            self.assertFalse(self.data()['pending'])
        self.fixture.write('fetch-fail','1');self.add(ok=False)

    def test_source_urls_and_names_are_data(self):
        for url in ['http://rules.example/list','https://user:pass@rules.example/list','https://rules.example:8443/list','file:///etc/passwd','https://rules.example/list#fragment','https://rules.example/\nls']:
            self.add(url=url,ok=False)
        self.add(name='bad\nname',ok=False)
        self.add(url='https://rules.example/a?token=example&v=1')
        self.run_source('rollback');self.run_source('discard')

    def test_original_options_preserved_and_concurrent_edit_blocks_restore(self):
        self.add();p=self.root/'etc/config/adblock-fast'
        p.write_text(p.read_text()+"\nconfig file_url 'external'\n option url 'https://external.example/file'\n")
        before=p.read_bytes();self.run_source('rollback',ok=False);self.assertEqual(p.read_bytes(),before)
        self.assertTrue(self.data()['pending'])

    def test_catalog_entry_uses_fixed_url_and_records_validation(self):
        self.run_source('begin','add','hagezi-light','ignored','https://wrong.example/','hosts');self.run_source('finish')
        self.assertEqual(self.data()['items'][0]['catalog_id'],'hagezi-light')
        self.assertEqual(self.data()['items'][0]['format'],'domains')

    def test_legacy_source_refresh_detects_formats_without_rewriting_native_settings(self):
        p=self.root/'etc/config/adblock-fast'
        p.write_text(p.read_text()+"\nconfig file_url 'legacy'\n option enabled '1'\n option url 'https://legacy.example/list'\n")
        self.run_source('begin','refresh');self.run_source('finish')
        item=self.data()['items'][0]
        self.assertEqual((item['domains'],item['format'],item['validation']),(2,'domains','validated'))
        self.assertGreater(item['updated'],0)
        self.assertNotIn('option adzero_format',p.read_text())
        self.body.write_text('0.0.0.0 ads.example\n')
        self.run_source('begin','refresh');self.run_source('finish')
        self.assertEqual(self.data()['items'][0]['format'],'hosts')

    def test_legacy_backend_only_format_is_not_misreported_as_validated(self):
        p=self.root/'etc/config/adblock-fast'
        p.write_text(p.read_text()+"\nconfig file_url 'legacy'\n option enabled '1'\n option url 'https://legacy.example/list'\n")
        self.body.write_text('||ads.example^$third-party\n')
        self.run_source('begin','refresh');self.run_source('finish')
        item=self.data()['items'][0]
        self.assertEqual(item['validation'],'backend_only');self.assertIsNone(item['domains'])
        self.assertEqual(item['format'],'unknown')

    def test_legacy_source_full_refresh_keeps_protection_and_populates_metadata(self):
        self.fixture.ctl('enable')
        p=self.root/'etc/config/adblock-fast'
        p.write_text(p.read_text()+"\nconfig file_url 'legacy'\n option enabled '1'\n option url 'https://legacy.example/list'\n")
        self.fixture.ctl('source-refresh')
        self.assertEqual(self.fixture.status()['state'],'configured_unverified')
        self.assertEqual(self.data()['items'][0]['domains'],2)
        self.assertFalse(self.data()['pending'])

    def test_anonymous_sources_restore_and_reject_shifted_ids(self):
        p=self.root/'etc/config/adblock-fast'
        p.write_text(p.read_text()+"\nconfig file_url\n option url 'https://one.example/list'\n option enabled '1'\n\nconfig file_url\n option url 'https://two.example/list'\n option enabled '1'\n")
        original=p.read_bytes();items=self.data()['items']
        self.run_source('begin','remove',items[0]['id'],items[0]['url'])
        self.assertNotEqual(self.data()['items'][0]['id'],items[1]['id'])
        self.run_source('rollback');self.run_source('discard')
        self.assertEqual(p.read_bytes(),original)
        self.fixture.ctl('enable');before=p.read_bytes()
        self.fixture.write('fail-backend-once','1')
        self.fixture.ctl('source-remove',items[0]['id'],items[0]['url'],ok=False)
        self.assertEqual(p.read_bytes(),before)
        self.assertEqual(self.fixture.status()['state'],'configured_unverified')
        self.assertFalse(self.data()['pending'])
        self.fixture.ctl('source-remove',items[0]['id'],items[0]['url'])
        self.fixture.ctl('source-toggle',items[0]['id'],items[0]['url'],'0',ok=False)
        self.assertTrue(self.data()['items'][0]['enabled'])

    def test_uncommitted_external_uci_is_not_committed_or_discarded(self):
        p=self.root/'etc/config/adblock-fast';before=p.read_bytes()
        command=[self.env['ADZERO_UCI']]
        try:
            subprocess.run(command+['set','adblock-fast.config.external_pending=keep'],check=True)
            self.add(ok=False)
            self.assertEqual(p.read_bytes(),before)
            self.assertIn('external_pending',subprocess.check_output(command+['changes','adblock-fast'],text=True))
            self.assertFalse(self.data()['pending'])
        finally:
            subprocess.run(command+['revert','adblock-fast'],check=True)

    def test_format_parsers_are_strict_but_support_common_hosts_headers(self):
        for kind,raw in [('hosts','127.0.0.1 localhost\n255.255.255.255 broadcasthost\nfe80::1%lo0 localhost\n0.0.0.0 ads.example\n'),('adblock','[Adblock Plus 2.0]\n! comment\n||ads.example^\n')]:
            self.body.write_text(raw);self.add(kind=kind);self.run_source('rollback');self.run_source('discard')
        self.body.write_text('||ads.example^$third-party\n');self.add(kind='adblock',url='https://invalid.example/list',ok=False)

    def test_full_controller_applies_and_rolls_back_rule_changes(self):
        self.fixture.ctl('enable')
        self.fixture.ctl('source-add','','Fresh','https://rules.example/list','domains')
        self.assertEqual(self.fixture.status()['state'],'configured_unverified')
        before=(self.root/'etc/config/adblock-fast').read_bytes()
        self.fixture.write('fail-backend-once','1')
        self.fixture.ctl('source-add','','Another','https://second.example/list','domains',ok=False)
        self.assertEqual((self.root/'etc/config/adblock-fast').read_bytes(),before)
        self.assertEqual(self.fixture.status()['state'],'configured_unverified')
        self.assertFalse(self.data()['pending'])

    def test_offline_selection_forces_rebuild_on_next_enable(self):
        self.fixture.ctl('source-add','','Fresh','https://rules.example/list','domains')
        self.fixture.ctl('enable')
        self.assertEqual((self.root/'last-start-method').read_text(),'dl')

    def test_reenable_uses_only_a_config_and_content_verified_backend_cache(self):
        f=self.fixture;f.ctl('source-add','','Fresh','https://rules.example/list','domains')
        f.ctl('enable');f.ctl('disable');f.ctl('enable')
        self.assertEqual((self.root/'last-start-method').read_text(),'start')
        f.ctl('disable')
        cache=self.root/'var/run/adblock-fast/dnsmasq.servers.cache'
        cache.write_text('server=/stale.example/\n')
        f.ctl('enable');self.assertEqual((self.root/'last-start-method').read_text(),'dl')
        f.ctl('disable')
        p=self.root/'etc/config/adblock-fast';p.write_text(p.read_text().replace('https://rules.example/list','https://changed.example/list'))
        f.ctl('enable');self.assertEqual((self.root/'last-start-method').read_text(),'dl')

    def subscription_cycle(self, plugin):
        self.fixture.select(plugin)
        self.fixture.write('source-downloads.json',json.dumps({'https://rules.example/list':['new-ads.example','new-track.example']}))
        self.fixture.ctl('enable')
        self.fixture.ctl('allow','ads.example','ads.example')
        self.fixture.ctl('source-add','','Fresh','https://rules.example/list','domains')
        item=self.data()['items'][-1]
        self.assertEqual(self.fixture.status()['adapter']['plugin'],plugin)
        self.assertEqual(self.fixture.status()['adapter']['domains'],3)
        self.assertEqual(self.fixture.query('new-ads.example')['match'],'exact')
        self.assertEqual(self.fixture.query('ads.example')['match'],'allowed')
        self.fixture.ctl('source-toggle',item['id'],item['url'],'0')
        self.assertEqual(self.fixture.status()['adapter']['domains'],1)
        self.assertEqual(self.fixture.query('new-ads.example')['match'],'none')
        self.fixture.ctl('source-toggle',item['id'],item['url'],'1')
        self.assertEqual(self.fixture.status()['adapter']['domains'],3)
        self.fixture.ctl('source-remove',item['id'],item['url'])
        self.assertEqual(self.fixture.status()['adapter']['domains'],1)
        self.assertEqual(self.fixture.query('ads.example')['match'],'allowed')
        self.fixture.ctl('disable')
        self.assertFalse(self.data()['pending'])

    def test_passwall_subscription_cycle(self): self.subscription_cycle('passwall')
    def test_nailink_subscription_cycle(self): self.subscription_cycle('nailink')
    def test_openclash_subscription_cycle(self): self.subscription_cycle('openclash')
    def test_nikki_subscription_cycle(self): self.subscription_cycle('nikki')

    def test_paused_and_external_owner_cannot_change_sources(self):
        self.fixture.ctl('enable');self.fixture.ctl('pause','300')
        self.fixture.ctl('source-add','','Fresh','https://rules.example/list','domains',ok=False)
        self.fixture.ctl('disable')
        subprocess.run([self.env['ADZERO_UCI'],'set','adblock-fast.config.enabled=1'],check=True)
        subprocess.run([self.env['ADZERO_UCI'],'commit','adblock-fast'],check=True)
        self.fixture.ctl('source-add','','Fresh','https://rules.example/list','domains',ok=False)
