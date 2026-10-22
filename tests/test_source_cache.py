"""Actual ucode/UCI cache handoff, corruption fallback and reload behavior."""
import json
from pathlib import Path
import subprocess
import unittest
import test_sources

@unittest.skipUnless(test_sources.UCODE, 'requires actual OpenWrt runtime')
class SourceCacheTest(unittest.TestCase):
    def setUp(self):
        self.s=test_sources.SourcesTest();self.s.setUp();self.addCleanup(self.s.doCleanups)
        self.f=self.s.fixture;self.root=self.s.root;self.env=self.s.env
        fetch=self.f.write('bin/fetch', '#!/bin/sh\necho fetch >> "$ADZERO_SOURCES_ROOT/fetches"\ncp "$ADZERO_SOURCES_ROOT/source-body" "$2"\n',True)
        self.env['ADZERO_SOURCE_FETCH_FIXTURE']=str(fetch)
        self.env['ADZERO_SOURCE_REPLAY']='1'
        self.url='https://rules.example/list.txt?token=private-token'
        self.s.add(url=self.url);self.s.run_source('finish')
        self.output=self.f.write('tmp/adblock-fast_tmp.aB123456','')

    def helper(self, action='replay', extra=(), ok=True):
        argv=test_sources.UCODE+[str(test_sources.PROGRAM.with_name('cache-curl.uc')),'--',action,'-f','--silent','--retry','3',*extra,self.url,'-o','/tmp/'+self.output.name]
        p=subprocess.run(argv,env=self.env,text=True,capture_output=True,timeout=10)
        self.assertEqual(p.returncode==0,ok,p.stdout+p.stderr);return p

    def test_precheck_bytes_are_reused_by_the_backend_without_another_download(self):
        self.helper();self.assertEqual(self.output.read_bytes(),self.s.body.read_bytes())
        self.assertEqual((self.root/'fetches').read_text().splitlines(),['fetch'])
        paths=list((self.root/'tmp/adzero-source-cache').iterdir())
        self.assertEqual({p.suffix for p in paths},{'.proof','.body','.parsed'})
        self.assertFalse(any('private-token' in p.name or b'private-token' in p.read_bytes() for p in paths))

    def test_reenable_uses_cache_but_explicit_refresh_fetches_new_content(self):
        item=self.s.data()['items'][0]
        for value in ('0','1'):
            self.s.run_source('begin','toggle',item['id'],item['url'],value);self.s.run_source('finish')
        self.assertEqual(len((self.root/'fetches').read_text().splitlines()),1)
        self.s.body.write_text('changed.example\n')
        self.s.run_source('begin','refresh');self.s.run_source('finish');self.helper()
        self.assertEqual(self.output.read_text(),'changed.example\n')
        self.assertEqual(self.s.data()['items'][0]['domains'],1)
        self.assertEqual(len((self.root/'fetches').read_text().splitlines()),2)

    def test_corrupt_body_is_a_miss_and_precheck_fetches_again(self):
        next((self.root/'tmp/adzero-source-cache').glob('*.body')).write_text('corrupt.example\n')
        self.helper(ok=False);self.assertEqual(self.output.read_text(),'')
        item=self.s.data()['items'][0]
        for value in ('0','1'):
            self.s.run_source('begin','toggle',item['id'],item['url'],value);self.s.run_source('finish')
        self.helper();self.assertEqual(self.output.read_bytes(),self.s.body.read_bytes())
        self.assertEqual(len((self.root/'fetches').read_text().splitlines()),2)

    def test_invalid_fresh_download_cannot_fall_back_to_old_snapshot_as_success(self):
        before=(self.root/'etc/config/adblock-fast').read_bytes()
        self.s.body.write_text('<html>download error</html>')
        self.s.run_source('begin','refresh',ok=False)
        self.assertEqual((self.root/'etc/config/adblock-fast').read_bytes(),before)
        self.helper(ok=False)

    def test_native_update_invalidates_old_source_snapshots_before_reload(self):
        self.f.ctl('enable')
        self.helper()
        # Simulate output replaced by the backend's native scheduled updater.
        (self.root/'var/run/adblock-fast/dnsmasq.servers').write_text('server=/native-new.example/\n')
        self.s.run_source('cache-sync')
        self.helper(ok=False)
        self.s.run_source('cache-live',ok=False)

    def test_native_update_invalidates_snapshot_on_disable_too(self):
        self.f.ctl('enable')
        (self.root/'var/run/adblock-fast/dnsmasq.servers').write_text('server=/native-new.example/\n')
        self.f.ctl('disable')
        self.assertFalse(list((self.root/'tmp/adzero-source-cache').glob('*.proof')))

    def test_corrupt_parsed_result_falls_back_to_strict_body_parser(self):
        next((self.root/'tmp/adzero-source-cache').glob('*.parsed')).write_text('{"names":["injected.example"]}')
        item=self.s.data()['items'][0]
        for value in ('0','1'):
            self.s.run_source('begin','toggle',item['id'],item['url'],value);self.s.run_source('finish')
        self.assertEqual(self.s.data()['items'][0]['domains'],2)
        self.assertEqual(len((self.root/'fetches').read_text().splitlines()),1)

    def test_old_parser_proof_recounts_the_same_body_without_network_and_upgrades_proof(self):
        proof=next((self.root/'tmp/adzero-source-cache').glob('*.proof'))
        parsed=next((self.root/'tmp/adzero-source-cache').glob('*.parsed'))
        # A checksum-valid result from an older parser is no longer evidence.
        import hashlib
        parsed.write_text(json.dumps({'format':'domains','names':['wrong.example']}))
        old=json.loads(proof.read_text());old.pop('parser',None)
        old['parsed']=hashlib.sha256(parsed.read_bytes()).hexdigest();proof.write_text(json.dumps(old))
        item=self.s.data()['items'][0]
        for value in ('0','1'):
            self.s.run_source('begin','toggle',item['id'],item['url'],value);self.s.run_source('finish')
        self.assertEqual(self.s.data()['items'][0]['domains'],2)
        self.assertEqual(self.s.data()['items'][0]['skipped'],0)
        self.assertEqual(len((self.root/'fetches').read_text().splitlines()),1)
        self.assertEqual(json.loads(proof.read_text())['parser'],3)
        self.assertEqual(json.loads(parsed.read_text())['names'],['new-ads.example','new-track.example'])

    def test_cached_partial_domain_validation_retains_exclusion_count_without_refetch(self):
        self.s.body.write_text('valid.example\n-bad.example\nunder_score.example\n')
        self.s.run_source('begin','refresh');self.s.run_source('finish')
        item=self.s.data()['items'][0]
        for value in ('0','1'):
            self.s.run_source('begin','toggle',item['id'],item['url'],value);self.s.run_source('finish')
        self.assertEqual((self.s.data()['items'][0]['domains'],self.s.data()['items'][0]['skipped']),(1,2))
        self.assertEqual(len((self.root/'fetches').read_text().splitlines()),2)

    def test_unchanged_refresh_keeps_body_and_parsed_files_even_when_cache_is_full(self):
        directory=self.root/'tmp/adzero-source-cache'
        body=next(directory.glob('*.body'));parsed=next(directory.glob('*.parsed'))
        prior={p.name:(p.stat().st_ino,p.stat().st_mtime_ns,p.read_bytes()) for p in (body,parsed)}
        # A sparse filler exceeds the optional cache budget without using RAM.
        with (directory/'budget-fixture').open('wb') as f: f.truncate(96000000)
        self.s.run_source('begin','refresh');self.s.run_source('finish')
        self.assertEqual({p.name:(p.stat().st_ino,p.stat().st_mtime_ns,p.read_bytes()) for p in (body,parsed)},prior)
        self.helper();self.assertEqual(len((self.root/'fetches').read_text().splitlines()),2)

    def test_unchanged_refresh_cannot_renew_a_corrupt_parsed_array(self):
        parsed=next((self.root/'tmp/adzero-source-cache').glob('*.parsed'))
        parsed.write_text('{"format":"domains","names":["wrong.example"],"skipped":0}')
        self.s.run_source('begin','refresh');self.s.run_source('finish')
        self.assertEqual(json.loads(parsed.read_text())['names'],['new-ads.example','new-track.example'])
        self.assertEqual(self.s.data()['items'][0]['domains'],2)

    def test_disabled_source_changes_do_not_rebuild_or_reload_any_adapter(self):
        # Place a disabled anonymous source before the active source. Deletion
        # renumbers anonymous IDs, which must not look like a rule change.
        for plugin in ('nailink','passwall','openclash','nikki'):
            with self.subTest(plugin=plugin):
                cfg=self.root/'etc/config/adblock-fast'
                text=cfg.read_text().replace("config file_url 'adzero_src_1'","config file_url")
                pos=text.index('\nconfig file_url')
                cfg.write_text(text[:pos]+"\nconfig file_url\n option url 'https://disabled.example/one'\n option enabled '0'\n"+text[pos:])
                self.f.select(plugin);self.f.ctl('enable')
                for p in (self.root/'tmp/adzero-source-cache').glob('*.proof'):p.unlink()
                backend=Path(self.env['ADZERO_BACKEND_INIT']);before=backend.read_text()
                journal=self.root/'etc/adzero/adapter.json';adapter_before=journal.read_bytes()
                backend.write_text('#!/bin/sh\necho called >> "$ADZERO_SOURCES_ROOT/disabled-rebuild"\nexit 77\n')
                item=next(i for i in self.s.data()['items'] if not i['enabled'])
                self.f.ctl('source-remove',item['id'],item['url'])
                self.assertFalse((self.root/'disabled-rebuild').exists())
                self.assertEqual(journal.read_bytes(),adapter_before)
                backend.write_text(before);self.f.ctl('disable')

    def test_format_edit_with_newly_downloaded_bytes_cannot_use_selection_shortcut(self):
        self.f.ctl('enable')
        listing=self.s.data();items=[{k:i[k] for k in ('id','name','url','format','enabled')} for i in listing['items']]
        items[0]['format']='hosts';self.s.body.write_text('0.0.0.0 fresh-host.example\n')
        for p in (self.root/'tmp/adzero-source-cache').glob('*.proof'):p.unlink()
        backend=Path(self.env['ADZERO_BACKEND_INIT']);original=backend.read_text()
        backend.write_text(original.replace("r=Path(os.environ['ADZERO_POLICY_ROOT']); output=", "r=Path(os.environ['ADZERO_POLICY_ROOT']); (r/'rebuild-log').open('a').write(sys.argv[1]+'\\n'); output="))
        plan=self.f.write('format-plan.json',json.dumps({'revision':listing['revision'],'items':items,'routing_before':False,'routing_enabled':False}))
        self.f.ctl('settings-apply',str(plan))
        self.assertEqual((self.root/'rebuild-log').read_text().splitlines(),['stop','dl'])

    def test_unsupported_flags_disabled_source_and_foreign_output_are_not_intercepted(self):
        self.helper(extra=('--header','X-Test: private'),ok=False)
        item=self.s.data()['items'][0]
        self.s.run_source('begin','toggle',item['id'],item['url'],'0');self.s.run_source('finish')
        self.helper(ok=False)
        self.assertEqual(self.output.read_text(),'')

    def test_symlink_and_public_cache_are_rejected(self):
        self.output.unlink();self.output.symlink_to(self.s.body)
        self.helper(ok=False);self.assertEqual(self.s.body.read_text(),'new-ads.example\nnew-track.example\n')
        self.output.unlink();self.output.write_text('');self.output.chmod(0o600)
        (self.root/'tmp/adzero-source-cache').chmod(0o755)
        self.helper(ok=False)

    def test_backend_download_can_seed_a_missing_snapshot(self):
        for p in (self.root/'tmp/adzero-source-cache').iterdir(): p.unlink()
        self.output.write_text('from-backend.example\n');self.helper('store')
        self.output.write_text('');self.helper()
        self.assertEqual(self.output.read_text(),'from-backend.example\n')

    def test_reload_unchanged_configuration_skips_backend_and_proxy_restart(self):
        for plugin in ('nailink','passwall','openclash','nikki'):
            with self.subTest(plugin=plugin):
                self.f.select(plugin);self.f.ctl('enable')
                backend=Path(self.env['ADZERO_BACKEND_INIT'])
                original=backend.read_text()
                backend.write_text('#!/bin/sh\necho unexpected >> "$ADZERO_SOURCES_ROOT/unexpected-restart"\nexit 77\n')
                self.f.ctl('reload');self.assertFalse((self.root/'unexpected-restart').exists())
                self.assertEqual(self.f.status()['state'],'configured_unverified')
                backend.write_text(original);self.f.ctl('disable')

    def test_reload_still_rejects_broken_backend_and_external_owner(self):
        self.f.ctl('reload',ok=False)
        self.f.ctl('enable')
        (self.root/'var/run/adblock-fast/dnsmasq.servers').unlink()
        self.f.ctl('reload',ok=False)

    def test_reload_after_native_cache_restore_does_not_require_source_snapshots(self):
        self.f.ctl('enable');self.f.ctl('disable')
        for p in (self.root/'tmp/adzero-source-cache').iterdir(): p.unlink()
        self.f.ctl('enable')
        self.s.run_source('cache-current')
        self.s.run_source('cache-live',ok=False)
        backend=Path(self.env['ADZERO_BACKEND_INIT'])
        backend.write_text('#!/bin/sh\necho unexpected >> "$ADZERO_SOURCES_ROOT/unexpected-restart"\nexit 77\n')
        self.f.ctl('reload')
        self.assertFalse((self.root/'unexpected-restart').exists())

    def test_unchanged_refresh_preserves_fast_restore_on_the_next_enable(self):
        item=self.s.data()['items'][0]
        for args in (['set',f"adblock-fast.{item['id']}.adzero_updated=1"],['commit','adblock-fast']):
            subprocess.run([self.env['ADZERO_UCI'],*args],check=True)
        self.f.ctl('enable');self.f.ctl('source-refresh')
        self.f.ctl('disable');self.f.ctl('enable')
        self.assertEqual((self.root/'last-start-method').read_text(),'start')

    def test_unchanged_refresh_skips_rebuild_but_changed_body_does_not(self):
        self.f.ctl('enable')
        # Metadata timestamps may change; effective options and every source
        # snapshot must remain equal before the expensive rebuild is skipped.
        backend=Path(self.env['ADZERO_BACKEND_INIT']);original=backend.read_text()
        journal=self.root/'etc/adzero/adapter.json';prior=journal.read_bytes()
        item=self.s.data()['items'][0]
        subprocess.run([self.env['ADZERO_UCI'],'set',f"adblock-fast.{item['id']}.size=999"],check=True)
        backend.write_text('#!/bin/sh\necho restart >> "$ADZERO_SOURCES_ROOT/rebuilds"\nexit 77\n')
        self.f.ctl('source-refresh')
        self.assertFalse((self.root/'rebuilds').exists())
        self.assertEqual(journal.read_bytes(),prior,'unchanged refreshed metadata must not regenerate adapter data')
        self.s.body.write_text('fresh-new.example\n')
        self.f.ctl('source-refresh',ok=False)
        self.assertTrue((self.root/'rebuilds').exists())
        backend.write_text(original)

    def test_domains_and_adblock_comment_or_order_changes_do_not_rebuild(self):
        for kind in ('domains','adblock'):
            with self.subTest(kind=kind):
                item=self.s.data()['items'][0]
                # Use an explicit selected kind for this independent source.
                subprocess.run([self.env['ADZERO_UCI'],'set',f"adblock-fast.{item['id']}.adzero_format={kind}"],check=True)
                subprocess.run([self.env['ADZERO_UCI'],'commit','adblock-fast'],check=True)
                values=['new-ads.example','new-track.example']
                if kind=='adblock':values=['||'+v+'^' for v in values]
                self.s.body.write_text('\n'.join(values)+'\n')
                self.s.run_source('begin','refresh');self.s.run_source('finish');self.f.ctl('enable')
                backend=Path(self.env['ADZERO_BACKEND_INIT']);original=backend.read_text()
                backend.write_text('#!/bin/sh\necho restart >> "$ADZERO_SOURCES_ROOT/semantic-rebuild"\nexit 77\n')
                self.s.body.write_text('# Updated: later\n'+values[1]+'\n\n'+values[0]+'\n')
                self.f.ctl('source-refresh')
                self.assertFalse((self.root/'semantic-rebuild').exists())
                backend.write_text(original);self.f.ctl('disable')

    def test_changed_hosts_comment_semantics_still_rebuild(self):
        item=self.s.data()['items'][0]
        subprocess.run([self.env['ADZERO_UCI'],'set',f"adblock-fast.{item['id']}.adzero_format=hosts"],check=True)
        subprocess.run([self.env['ADZERO_UCI'],'commit','adblock-fast'],check=True)
        self.s.body.write_text('0.0.0.0 one.example\n0.0.0.0 two.example\n')
        self.s.run_source('begin','refresh');self.s.run_source('finish');self.f.ctl('enable')
        backend=Path(self.env['ADZERO_BACKEND_INIT']);original=backend.read_text()
        backend.write_text(original.replace("r=Path(os.environ['ADZERO_POLICY_ROOT']); output=", "r=Path(os.environ['ADZERO_POLICY_ROOT']); (r/'hosts-rebuild-log').open('a').write(sys.argv[1]+'\\n'); output="))
        self.s.body.write_text('0.0.0.0 one.example # localhost\n0.0.0.0 two.example\n')
        self.f.ctl('source-refresh')
        self.assertEqual((self.root/'hosts-rebuild-log').read_text().splitlines(),['stop','dl'])

    def test_semantic_proof_corruption_never_skips_backend_rebuild(self):
        self.f.ctl('enable')
        parsed=next((self.root/'tmp/adzero-source-cache').glob('*.parsed'))
        parsed.write_text('{"format":"domains","names":["different.example"],"skipped":0}')
        self.s.body.write_text('genuinely-new.example\n')
        backend=Path(self.env['ADZERO_BACKEND_INIT']);original=backend.read_text()
        backend.write_text(original.replace("r=Path(os.environ['ADZERO_POLICY_ROOT']); output=", "r=Path(os.environ['ADZERO_POLICY_ROOT']); (r/'new-rebuild-log').open('a').write(sys.argv[1]+'\\n'); output="))
        self.f.ctl('source-refresh')
        self.assertEqual((self.root/'new-rebuild-log').read_text().splitlines(),['stop','dl'])

    def test_metadata_apply_cannot_stamp_unapplied_snapshot_as_current(self):
        self.f.ctl('enable');cache=self.root/'etc/adzero/backend-cache.json'
        prior=json.loads(cache.read_text())['effective']
        # Simulate a later subscription failing after an earlier one was
        # downloaded: selection rolls back while disposable bytes are newer.
        self.s.body.write_text('unapplied-new.example\n')
        self.s.run_source('begin','refresh');self.s.run_source('rollback');self.s.run_source('discard')
        self.s.run_source('cache-live',ok=False)
        listing=self.s.data();items=[{k:i[k] for k in ('id','name','url','format','enabled')} for i in listing['items']]
        items[0]['name']='Only a name change'
        plan=self.f.write('rename-plan.json',json.dumps({'revision':listing['revision'],'items':items,'routing_before':False,'routing_enabled':False}))
        self.f.ctl('settings-apply',str(plan))
        self.assertEqual(json.loads(cache.read_text())['effective'],prior)
        self.s.run_source('cache-live',ok=False)

    def test_cached_start_preserves_the_inputs_of_restored_output(self):
        self.f.ctl('enable');cache=self.root/'etc/adzero/backend-cache.json'
        prior=json.loads(cache.read_text())['effective']
        self.s.body.write_text('not-yet-applied.example\n')
        self.s.run_source('begin','refresh');self.s.run_source('rollback');self.s.run_source('discard')
        self.s.run_source('cache-save','preserve')
        self.assertEqual(json.loads(cache.read_text())['effective'],prior)
        self.s.run_source('cache-live',ok=False)

    def test_legacy_cache_input_claim_is_not_promoted_to_current_proof(self):
        self.f.ctl('enable');cache=self.root/'etc/adzero/backend-cache.json'
        self.s.body.write_text('legacy-unapplied.example\n')
        self.s.run_source('begin','refresh');self.s.run_source('rollback');self.s.run_source('discard')
        # Reproduce an old proof claiming the latest downloaded bytes while
        # the output is still the previous cached result. It cannot be reused.
        old=json.loads(cache.read_text());old['schema']=1
        snapshot=json.loads(next((self.root/'tmp/adzero-source-cache').glob('*.proof')).read_text())
        for item in old['effective']:
            if item['type']=='file_url':item['snapshot']=snapshot['body'];item.pop('semantic',None)
        cache.write_text(json.dumps(old));self.s.run_source('cache-live',ok=False)
        self.s.run_source('cache-save','preserve')
        state=json.loads(cache.read_text())
        self.assertEqual(state['schema'],2);self.assertIsNone(state['effective'])
        self.s.run_source('cache-live',ok=False)

if __name__=='__main__': unittest.main()
