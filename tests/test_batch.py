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

    def test_download_failure_does_not_commit_any_of_the_selection(self):
        p=self.plan(); self.add(p); self.add(p,'Bad','https://invalid.example/list')
        before=(self.root/'etc/config/adblock-fast').read_bytes()
        self.apply(p,ok=False)
        self.assertEqual((self.root/'etc/config/adblock-fast').read_bytes(),before)
        self.assertFalse(self.sources.data()['pending'])

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
