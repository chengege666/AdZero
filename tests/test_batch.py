"""Batch desired-config transactions with real OpenWrt UCI/ucode."""
import json
import shlex
import subprocess
import unittest
import test_sources
import test_routing


@unittest.skipUnless(test_sources.UCODE, 'requires actual OpenWrt UCI/ucode')
class BatchTest(unittest.TestCase):
    def setUp(self):
        self.sources = test_sources.SourcesTest()
        self.sources.setUp()
        self.addCleanup(self.sources.doCleanups)
        self.f = self.sources.fixture
        self.root = self.f.root
        self.fetches = self.root / 'fetches'
        fetch = self.f.write('bin/batch-fetch', '#!/bin/sh\necho fetched >> '+shlex.quote(str(self.fetches))+'\ncase "$1" in *invalid*) exit 1;; esac\ncp "$ADZERO_SOURCES_ROOT/source-body" "$2"\n', True)
        self.f.env['ADZERO_SOURCE_FETCH_FIXTURE'] = str(fetch)

    def plan(self):
        data = self.sources.data()
        return {'revision': data['revision'], 'items': [{k:i[k] for k in ('id','name','url','format','enabled')} for i in data['items']],
                'routing_before': self.f.status()['policy']['routing_enabled'], 'routing_enabled': self.f.status()['policy']['routing_enabled']}

    def add(self, p, name='One', url='https://rules.example/one'):
        p['items'].append({'id':None,'name':name,'url':url,'format':'domains','enabled':True})

    def apply(self, p, ok=True):
        path = self.f.write('batch.json', json.dumps(p))
        return self.f.ctl('settings-apply', str(path), ok=ok)

    def test_numeric_backend_size_delta_does_not_block_refresh(self):
        self.sources.add(); self.sources.run_source('finish'); self.f.ctl('enable')
        item = self.sources.data()['items'][0]
        uci = self.f.env['ADZERO_UCI']
        try:
            subprocess.run([uci,'set','adblock-fast.'+item['id']+'.size=206588'], check=True)
            self.f.ctl('source-refresh')
            self.assertEqual(self.f.status()['state'],'configured_unverified')
            self.assertEqual(self.sources.data()['items'][0]['domains'],2)
        finally:
            subprocess.run([uci,'revert','adblock-fast'],check=True)

    def test_external_user_delta_is_preserved_and_rejected(self):
        self.sources.add(); self.sources.run_source('finish')
        before = (self.root/'etc/config/adblock-fast').read_bytes()
        uci = self.f.env['ADZERO_UCI']
        try:
            subprocess.run([uci,'set','adblock-fast.config.enabled=1'],check=True)
            p=self.plan(); self.add(p); self.apply(p,ok=False)
            self.assertEqual((self.root/'etc/config/adblock-fast').read_bytes(),before)
            self.assertIn('enabled',subprocess.check_output([uci,'changes','adblock-fast'],text=True))
        finally: subprocess.run([uci,'revert','adblock-fast'],check=True)

    def test_multiple_sources_save_offline_and_validate_once_each(self):
        p=self.plan()
        for n in range(3): self.add(p,str(n),'https://rules.example/'+str(n))
        self.assertFalse(self.fetches.exists())
        self.apply(p)
        self.assertEqual(len(self.sources.data()['items']),3)
        self.assertEqual(len(self.fetches.read_text().splitlines()),3)
        self.assertEqual(self.f.status()['state'],'disabled')

    def test_stale_page_cannot_overwrite_other_edits(self):
        p=self.plan(); self.add(p)
        file=self.root/'etc/config/adblock-fast'; file.write_text(file.read_text()+"\nconfig file_url 'external'\n option url 'https://external.example/list'\n")
        before=file.read_bytes(); self.apply(p,ok=False)
        self.assertEqual(file.read_bytes(),before)
        self.assertFalse(self.fetches.exists())

    def test_semantic_revision_ignores_committed_statistics_and_formatting(self):
        self.sources.add();self.sources.run_source('finish');p=self.plan();item=p['items'][0]
        uci=self.f.env['ADZERO_UCI']
        for key,value in [('size','101'),('adzero_domains','123'),('adzero_skipped','7'),('adzero_checked','1'),('adzero_updated','2'),('adzero_validation','validated')]:
            subprocess.run([uci,'set','adblock-fast.'+item['id']+'.'+key+'='+value],check=True)
        subprocess.run([uci,'commit','adblock-fast'],check=True)
        config=self.root/'etc/config/adblock-fast';config.write_text('# harmless comment\n'+config.read_text())
        self.assertEqual(self.sources.data()['revision'],p['revision'])
        p['items'][0]['name']='Renamed';self.apply(p)
        self.assertEqual(self.sources.data()['items'][0]['name'],'Renamed')

    def test_pending_statistic_delta_does_not_conflict_or_discard_user_edits(self):
        self.sources.add();self.sources.run_source('finish');p=self.plan();uci=self.f.env['ADZERO_UCI'];id=p['items'][0]['id']
        try:
            subprocess.run([uci,'set','adblock-fast.'+id+'.adzero_checked=1'],check=True)
            self.assertEqual(self.sources.data()['revision'],p['revision'])
            p['items'][0]['name']='Changed';self.apply(p)
        finally:subprocess.run([uci,'revert','adblock-fast'],check=True)

    def test_semantic_revision_retains_all_protected_configuration_changes(self):
        self.sources.add();self.sources.run_source('finish');uci=self.f.env['ADZERO_UCI'];id=self.plan()['items'][0]['id']
        for key,value in [('adblock-fast.'+id+'.url','https://changed.example/list'),('adblock-fast.'+id+'.enabled','0'),('adblock-fast.'+id+'.adzero_format','hosts'),('adblock-fast.config.allowed_domain','new.example'),('adblock-fast.config.dns','dnsmasq.addnhosts'),('adzero.main.routing_enabled','1'),('adzero.main.dns_profile','{"domestic":{"servers":["119.29.29.29"]}}')]:
            with self.subTest(key=key):
                p=self.plan();context=self.root/'revision-context';context.mkdir(exist_ok=True)
                for f in context.iterdir():f.unlink()
                self.f.env['ADZERO_JOB_CONTEXT']=str(context)
                subprocess.run([uci,'set',key+'='+value],check=True);subprocess.run([uci,'commit',key.split('.')[0]],check=True)
                path=self.f.write('stale.json',json.dumps(p));self.sources.run_source('plan-check',str(path),ok=False)
                self.assertEqual((context/'reason').read_text(),'config_conflict')

    def test_empty_ruleset_is_structured_and_rejected_before_any_backend_call(self):
        self.sources.add();self.sources.run_source('finish');uci=self.f.env['ADZERO_UCI']
        subprocess.run([uci,'delete','adblock-fast.config.blocked_domain'],check=True);subprocess.run([uci,'commit','adblock-fast'],check=True)
        self.f.ctl('enable');context=self.job_context();p=self.plan();p['items'][0]['enabled']=False
        before=(self.root/'etc/config/adblock-fast').read_bytes();backend=self.f.write('bin/no-backend','#!/bin/sh\necho called > '+shlex.quote(str(self.root/'unexpected-backend'))+'\nexit 77\n',True)
        self.f.env['ADZERO_BACKEND_INIT']=str(backend);self.apply(p,ok=False)
        self.assertEqual((context/'reason').read_text(),'empty_ruleset');self.assertFalse((self.root/'unexpected-backend').exists())
        self.assertEqual((self.root/'etc/config/adblock-fast').read_bytes(),before);self.assertFalse(self.sources.data()['pending'])

    def test_empty_subscriptions_can_be_saved_offline_or_with_manual_blocks(self):
        self.sources.add();self.sources.run_source('finish');uci=self.f.env['ADZERO_UCI']
        subprocess.run([uci,'delete','adblock-fast.config.blocked_domain'],check=True);subprocess.run([uci,'commit','adblock-fast'],check=True)
        p=self.plan();p['items'][0]['enabled']=False;self.apply(p)
        subprocess.run([uci,'add_list','adblock-fast.config.blocked_domain=manual.example'],check=True);subprocess.run([uci,'commit','adblock-fast'],check=True)
        self.f.ctl('enable');p=self.plan();p['items']=[];self.apply(p)
        self.assertEqual(self.f.status()['state'],'configured_unverified')

    def test_unknown_capacity_blocks_live_batch_without_replacing_working_rules(self):
        config=self.root/'etc/config/adblock-fast';config.write_text(config.read_text()+"\nconfig file_url 'legacy'\n option enabled '1'\n option url 'https://legacy.example/list'\n")
        self.f.write('unsupported-body','||track.example^$third-party\n')
        fetch=self.f.write('bin/legacy-fetch','#!/bin/sh\ncase "$1" in *legacy*) cp "$ADZERO_SOURCES_ROOT/unsupported-body" "$2";; *) cp "$ADZERO_SOURCES_ROOT/source-body" "$2";; esac\n',True)
        self.f.env['ADZERO_SOURCE_FETCH_FIXTURE']=str(fetch);self.f.ctl('enable');context=self.job_context()
        original=config.read_bytes();p=self.plan();self.add(p)
        backend=self.f.write('bin/no-live-backend','#!/bin/sh\necho called > '+shlex.quote(str(self.root/'unexpected-stop'))+'\nexit 77\n',True);self.f.env['ADZERO_BACKEND_INIT']=str(backend)
        self.apply(p,ok=False)
        self.assertEqual((context/'reason').read_text(),'source_capacity_unknown');self.assertFalse((self.root/'unexpected-stop').exists());self.assertEqual(config.read_bytes(),original)
        receipt=json.loads((self.root/'etc/adzero/sources-capacity.json').read_text())
        self.assertEqual(receipt['state'],'unknown');self.assertEqual(receipt['unknown_sources'],[1]);self.assertGreater(receipt['known_domains'],0)
        self.assertNotIn('https://',json.dumps(receipt))

    def test_download_failure_does_not_commit_any_of_the_selection(self):
        p=self.plan(); self.add(p); self.add(p,'Bad','https://invalid.example/list')
        before=(self.root/'etc/config/adblock-fast').read_bytes()
        self.apply(p,ok=False)
        self.assertEqual((self.root/'etc/config/adblock-fast').read_bytes(),before)
        self.assertFalse(self.sources.data()['pending'])

    def test_real_external_edit_during_download_is_preserved_before_commit(self):
        p=self.plan();self.add(p)
        fetch=self.f.write('bin/racing-fetch','#!/bin/sh\n"$ADZERO_UCI" set adblock-fast.config.external_setting=keep\n"$ADZERO_UCI" commit adblock-fast\ncp "$ADZERO_SOURCES_ROOT/source-body" "$2"\n',True)
        self.f.env['ADZERO_SOURCE_FETCH_FIXTURE']=str(fetch);context=self.job_context();self.apply(p,ok=False)
        self.assertEqual((context/'reason').read_text(),'config_conflict')
        self.assertIn("option external_setting 'keep'",(self.root/'etc/config/adblock-fast').read_text());self.assertEqual(self.sources.data()['items'],[]);self.assertFalse(self.sources.data()['pending'])

    def test_capacity_receipt_counts_manual_blocks_and_hides_private_inputs(self):
        p=self.plan();self.add(p,url='https://rules.example/list?token=private-value');self.apply(p)
        capacity=self.sources.data()['capacity']
        self.assertEqual(capacity['state'],'complete');self.assertEqual(capacity['known_domains'],3);self.assertTrue(capacity['current'])
        self.assertNotIn('private-value',json.dumps(capacity));self.assertNotIn('selection',capacity)

    def test_semantic_revision_normalizes_json_key_order_but_not_dns_values(self):
        uci=self.f.env['ADZERO_UCI']
        for value in ['{"b":2,"a":{"x":1,"y":2}}','{ "a": {"y":2,"x":1}, "b":2 }']:
            subprocess.run([uci,'set','adzero.main.dns_enhance='+value],check=True);subprocess.run([uci,'commit','adzero'],check=True)
            current=self.sources.data()['revision']
            if 'revision' in locals():self.assertEqual(current,revision)
            revision=current

    def test_capacity_boundary_includes_manual_block_in_the_union(self):
        self.sources.body.write_text(''.join('a'+str(n)+'.example\n' for n in range(499999)))
        p=self.plan();self.add(p);self.apply(p)
        self.assertEqual(self.sources.data()['capacity']['known_domains'],500000)
        self.sources.body.write_text(self.sources.body.read_text()+'one-more.example\n')
        self.f.ctl('enable');context=self.job_context();before=(self.root/'etc/config/adblock-fast').read_bytes()
        self.f.ctl('source-refresh',ok=False)
        self.assertEqual((context/'reason').read_text(),'source_limit');self.assertEqual((self.root/'etc/config/adblock-fast').read_bytes(),before)

    def test_failed_backend_restores_all_changes(self):
        self.f.ctl('enable'); p=self.plan(); self.add(p)
        before=(self.root/'etc/config/adblock-fast').read_bytes()
        self.f.write('fail-backend-once','1'); self.apply(p,ok=False)
        self.assertEqual((self.root/'etc/config/adblock-fast').read_bytes(),before)
        self.assertFalse(self.sources.data()['pending'])
        self.assertEqual(self.f.status()['state'],'configured_unverified')

    def test_nailink_sources_and_routing_share_one_reload(self):
        controller=test_routing.RoutingControllerTest(); controller.fixture=self.f; controller.root=self.root
        profile=controller.nailink(); self.f.ctl('enable'); before=json.loads(profile.read_text())['runs']
        p=self.plan(); self.add(p); self.add(p,'Two','https://rules.example/two'); p['routing_enabled']=True
        self.apply(p)
        self.assertEqual(json.loads(profile.read_text())['runs'],before+1)
        self.assertEqual(self.f.status()['adapter']['routing']['mode'],'proxy')
        self.assertEqual(self.f.query('ads.example')['match'],'exact')
        p=self.plan(); p['items'][0]['enabled']=False; p['routing_enabled']=False; self.apply(p)
        self.assertEqual(json.loads(profile.read_text())['runs'],before+2)
        self.assertFalse(self.f.status()['policy']['routing_enabled'])

    def test_nailink_partial_failure_restores_routing_and_sources(self):
        controller=test_routing.RoutingControllerTest(); controller.fixture=self.f; controller.root=self.root
        profile=controller.nailink(); self.f.ctl('enable'); before=json.loads(profile.read_text())
        p=self.plan(); self.add(p); p['routing_enabled']=True
        self.f.write('fail-route-once','1'); self.apply(p,ok=False)
        self.assertFalse(self.f.status()['policy']['routing_enabled'])
        self.assertFalse(self.sources.data()['pending'])
        self.assertEqual(json.loads(profile.read_text())['dns'],before['dns'])
        self.assertEqual(self.f.status()['state'],'configured_unverified')

    def test_batch_rule_changes_rebuild_backend_once_on_each_adapter(self):
        for plugin in ('passwall','openclash','nikki','nailink'):
            with self.subTest(plugin=plugin):
                self.f.select(plugin)
                self.f.ctl('enable')
                original=self.f.env['ADZERO_BACKEND_INIT']; log=self.root/('calls-'+plugin)
                wrapper=self.f.write('bin/count-backend','#!/bin/sh\necho "$1" >> '+shlex.quote(str(log))+'\nexec '+shlex.quote(original)+' "$@"\n',True)
                self.f.env['ADZERO_BACKEND_INIT']=str(wrapper)
                p=self.plan()
                if not p['items']:self.add(p,'One','https://rules.example/one')
                self.add(p,plugin,'https://rules.example/'+plugin)
                self.apply(p)
                self.assertEqual(log.read_text().splitlines(),['stop','dl'])
                self.assertEqual(self.f.status()['state'],'configured_unverified')
                self.f.env['ADZERO_BACKEND_INIT']=original
                self.f.ctl('disable')

    def test_batch_edit_revalidates_and_delete_is_atomic(self):
        p=self.plan();self.add(p);self.add(p,'Two','https://rules.example/two');self.apply(p)
        p=self.plan();p['items']=p['items'][:1];p['items'][0].update(name='Edited',url='https://edited.example/list')
        self.apply(p)
        items=self.sources.data()['items'];self.assertEqual(len(items),1)
        self.assertEqual((items[0]['name'],items[0]['url']),('Edited','https://edited.example/list'))

    def test_noop_plan_does_not_download_or_reload(self):
        self.f.ctl('enable');p=self.plan()
        self.apply(p)
        self.assertFalse(self.fetches.exists())

    def test_other_proxy_adapters_apply_rules_and_routing_together(self):
        f=self.f
        data=f.write('routing-fixture.json',json.dumps({'domain_raw':'server=/cn.example/114.114.114.114\n','cidr_raw':'223.5.5.0/24\n'}))
        f.env.update(ADZERO_ROUTING_DATA_FIXTURE=str(data),ADZERO_ROUTING_DATA_PROGRAM=str(test_sources.ROOT/'luci-app-adzero/root/usr/libexec/adzero/routing-data'),ADZERO_UCODE=shlex.join(test_sources.UCODE))
        for plugin in ('passwall','openclash','nikki'):
            with self.subTest(plugin=plugin):
                f.select(plugin)
                f.write('etc/config/adzero',"config adzero 'main'\n option enabled '0'\n option routing_enabled '0'\n")
                if plugin=='passwall':
                    f.write('etc/config/passwall',"config global 'main'\n option enabled '1'\n option node 'chosen'\n option dns_mode 'xray'\n option chn_list '0'\nconfig nodes 'chosen'\n option type 'Xray'\n")
                    f.write('usr/share/passwall/app.sh','# direct_dns_mode USE_DEFAULT_DNS\n')
                    f.write('usr/share/passwall/rules/chnlist','cn.example\n');f.write('usr/share/passwall/rules/chnroute','223.5.5.0/24\n')
                else:
                    base=json.dumps({'mode':'rule','dns':{'enable':True,'enhanced-mode':'fake-ip','fake-ip-filter':['+.lan'],'nameserver':['8.8.8.8']},'proxy-groups':[{'name':'My Proxy','type':'select','proxies':['node']}],'rules':['MATCH,My Proxy']})
                    f.write('etc/openclash/source.yaml' if plugin=='openclash' else 'etc/nikki/base.yaml',base)
                    if plugin=='nikki':f.write('etc/nikki/run/config.yaml',base)
                f.ctl('enable');p=self.plan();self.add(p,plugin,'https://combined.example/'+plugin);p['routing_enabled']=True
                self.apply(p)
                self.assertEqual(f.status()['state'],'configured_unverified')
                self.assertEqual(f.status()['adapter']['routing']['mode'],'proxy')
                f.ctl('disable')

    def test_malformed_and_duplicate_batch_inputs_are_rejected(self):
        before=(self.root/'etc/config/adblock-fast').read_bytes()
        for update in [{'routing_enabled':'1'},{'revision':['a'*64]},{'items':[{'id':1,'enabled':True,'name':'x','url':'https://x.example/','format':'domains'}]}]:
            p=self.plan();p.update(update);self.apply(p,ok=False)
        p=self.plan();self.add(p);self.add(p);self.apply(p,ok=False)
        self.assertEqual((self.root/'etc/config/adblock-fast').read_bytes(),before)
        self.assertFalse(self.fetches.exists())

    def job_context(self):
        context=self.root/'job-context';context.mkdir()
        self.f.env['ADZERO_JOB_CONTEXT']=str(context)
        return context

    def test_overlapping_domains_across_many_lists_are_accepted(self):
        context=self.job_context();p=self.plan()
        for n in range(14):self.add(p,str(n),'https://rules.example/'+str(n))
        self.apply(p)
        self.assertEqual(len(self.sources.data()['items']),14)
        self.assertFalse((context/'reason').exists())
        self.assertFalse((context/'source').exists())

    def test_second_failed_subscription_has_numeric_context_and_preserves_choices(self):
        context=self.job_context();p=self.plan()
        self.add(p);self.add(p,'Private name','https://invalid.example/list?token=secret')
        before=(self.root/'etc/config/adblock-fast').read_bytes()
        self.apply(p,ok=False)
        self.assertEqual((context/'reason').read_text().strip(),'source_download')
        self.assertEqual(json.loads((context/'source').read_text()),dict(index=2,total=2))
        self.assertNotIn('secret',''.join(x.read_text() for x in context.iterdir()))
        self.assertEqual((self.root/'etc/config/adblock-fast').read_bytes(),before)

    def test_duplicate_address_reports_specific_cause_before_download(self):
        context=self.job_context();p=self.plan();self.add(p);self.add(p)
        self.apply(p,ok=False)
        self.assertEqual((context/'reason').read_text().strip(),'source_duplicate')
        self.assertFalse(self.fetches.exists())

    def test_bad_format_retains_source_position_without_committing(self):
        context=self.job_context();p=self.plan();self.add(p)
        self.sources.body.write_text('<html>provider error</html>')
        before=(self.root/'etc/config/adblock-fast').read_bytes()
        self.apply(p,ok=False)
        self.assertEqual((context/'reason').read_text().strip(),'source_format')
        self.assertEqual(json.loads((context/'source').read_text()),dict(index=1,total=1))
        self.assertEqual((self.root/'etc/config/adblock-fast').read_bytes(),before)

    def test_oversized_list_reports_limit_without_committing(self):
        context=self.job_context();p=self.plan();self.add(p)
        self.sources.body.write_text(''.join('a'+str(n)+'.example\n' for n in range(500001)))
        before=(self.root/'etc/config/adblock-fast').read_bytes()
        self.apply(p,ok=False)
        self.assertEqual((context/'reason').read_text().strip(),'source_limit')
        self.assertEqual((self.root/'etc/config/adblock-fast').read_bytes(),before)

    def test_stale_temporary_file_is_not_misreported_as_invalid_format(self):
        context=self.job_context();p=self.plan();self.add(p)
        self.f.write('tmp/adzero-source-check','existing')
        self.apply(p,ok=False)
        self.assertEqual((context/'reason').read_text().strip(),'source_check')
        self.assertEqual((self.root/'tmp/adzero-source-check').read_text(),'existing')

    def capacity_sources(self,overlap=False):
        self.sources.body.write_text(''.join('a'+str(n)+'.example\n' for n in range(300001)))
        self.sources.add(name='First',url='https://rules.example/first');self.sources.run_source('finish')
        first=self.sources.data()['items'][0]
        self.sources.run_source('begin','toggle',first['id'],first['url'],'0');self.sources.run_source('finish')
        self.sources.body.write_text(''.join(('a' if overlap else 'b')+str(n)+'.example\n' for n in range(200001)))
        self.sources.add(name='Second',url='https://rules.example/second');self.sources.run_source('finish')
        second=self.sources.data()['items'][1]
        self.sources.run_source('begin','toggle',second['id'],second['url'],'0');self.sources.run_source('finish')
        self.sources.run_source('begin','toggle',first['id'],first['url'],'1');self.sources.run_source('finish')
        self.f.ctl('enable')
        original=self.f.env['ADZERO_BACKEND_INIT'];calls=self.root/'backend-capacity-calls'
        wrapper=self.f.write('bin/capacity-backend','#!/bin/sh\necho "$1" >> '+shlex.quote(str(calls))+'\nexec '+shlex.quote(original)+' "$@"\n',True)
        self.f.env['ADZERO_BACKEND_INIT']=str(wrapper)
        return first,second,calls

    def test_cached_combined_capacity_rejected_before_backend_stop(self):
        first,second,calls=self.capacity_sources();context=self.job_context()
        p=self.plan();p['items'][1]['enabled']=True
        before=(self.root/'etc/config/adblock-fast').read_bytes()
        self.apply(p,ok=False)
        self.assertEqual((context/'reason').read_text().strip(),'source_limit')
        self.assertFalse(calls.exists(),'preflight must leave the working backend running')
        self.assertEqual((self.root/'etc/config/adblock-fast').read_bytes(),before)

    def test_cached_overlapping_capacity_does_not_sum_individual_counts(self):
        first,second,calls=self.capacity_sources(overlap=True)
        p=self.plan();p['items'][1]['enabled']=True
        self.apply(p)
        self.assertTrue(self.sources.data()['items'][1]['enabled'])

    def test_new_download_and_unchanged_cache_share_one_capacity_guard(self):
        first,second,calls=self.capacity_sources();context=self.job_context()
        p=self.plan();p['items'][1].update(enabled=True,url='https://rules.example/new-download')
        before=(self.root/'etc/config/adblock-fast').read_bytes()
        self.apply(p,ok=False)
        self.assertEqual((context/'reason').read_text().strip(),'source_limit')
        self.assertFalse(calls.exists())
        self.assertEqual((self.root/'etc/config/adblock-fast').read_bytes(),before)

    def test_capacity_uses_verified_raw_snapshot_if_parsed_cache_is_corrupt(self):
        first,second,calls=self.capacity_sources();context=self.job_context()
        for path in (self.root/'tmp/adzero-source-cache').glob('*.parsed'):path.write_text('{broken')
        prior=len(self.fetches.read_text().splitlines())
        p=self.plan();p['items'][1]['enabled']=True
        self.apply(p,ok=False)
        self.assertEqual((context/'reason').read_text().strip(),'source_limit')
        self.assertFalse(calls.exists())
        self.assertEqual(len(self.fetches.read_text().splitlines()),prior,'raw snapshot fallback is offline')

    def test_backend_failure_reason_survives_successful_restore(self):
        self.f.ctl('enable');context=self.job_context();p=self.plan();self.add(p)
        original=self.f.env['ADZERO_BACKEND_INIT'];flag=self.f.write('memory-failure-once','1')
        wrapper=self.f.write('bin/failing-backend','#!/usr/bin/env python3\n'+
            'import os,sys,json\nfrom pathlib import Path\n'+
            'root=Path(os.environ["ADZERO_POLICY_ROOT"])\n'+
            'flag=Path('+repr(str(flag))+')\n'+
            'if sys.argv[1]!="stop" and flag.exists():\n'+
            ' flag.unlink();state=json.loads((root/"service.json").read_text())\n'+
            ' state["adblock-fast"]={"data":{"status":"statusFail","errors":[{"code":"errorTooLittleRam","info":"private-token"}]}}\n'+
            ' (root/"service.json").write_text(json.dumps(state));sys.exit(2)\n'+
            'os.execv('+repr(original)+',['+repr(original)+',*sys.argv[1:]])\n',True)
        self.f.env['ADZERO_BACKEND_INIT']=str(wrapper)
        before=(self.root/'etc/config/adblock-fast').read_bytes()
        self.apply(p,ok=False)
        self.assertEqual((context/'reason').read_text().strip(),'backend_memory')
        self.assertEqual((self.root/'etc/config/adblock-fast').read_bytes(),before)
        self.assertEqual(self.f.status()['state'],'configured_unverified')
        self.assertNotIn('private-token',''.join(x.read_text() for x in context.iterdir()))
