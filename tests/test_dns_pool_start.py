"""Actual prepare_pool, native milliseconds, private health records; no router."""
import json,os,shlex,subprocess,tempfile,threading,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
LIB=ROOT/'luci-app-adzero/root/usr/libexec/adzero'
UCODE=shlex.split(os.environ.get('ADZERO_UCODE',''))
PROFILE={'domestic':{'servers':['223.5.5.5','119.29.29.29'],'active':'223.5.5.5','mode':'parallel'},'foreign':{'servers':['1.1.1.1'],'active':'1.1.1.1'}}

def prepare_source():
    text=(LIB/'adapter.uc').read_text()
    return text[text.index('prepare_pool=function(plugin){'):text.index('\nstrict_target=function(plugin){')]

def harness(root='ARGV[0]'):
    return f"""import * as fs from 'fs';
import * as route from '{LIB/'routing-lib.uc'}';
import * as progress from '{LIB/'progress-lib.uc'}';
import * as poolstate from '{LIB/'dns-pool-state.uc'}';
import {{now as monotime}} from '{LIB/'dns-io.uc'}';
const root={root},state_dir=root+'/etc/adzero';
let prepare_pool,dns_profile=route.profile(json(fs.readfile(root+'/profile')));
function atomic(path,raw,mode){{let f=fs.open(path,'wx',mode);if(!f)die('write');f.write(raw);f.close();}}
function pool_needed(plugin){{return true;}}
// These cases isolate readiness; native pool integration tests the real probe.
function verify_pool(plugin){{}}
function service_command(plugin,action){{return ['/bin/sh',root+'/service',action];}}
function timeout_helper(){{return '/usr/bin/timeout';}}
fs.writefile(root+'/expected',sprintf('%J',route.effective(dns_profile)));
"""+prepare_source()+"""
let start=monotime(),ok=false,error=null;
try{if(ARGV[1]=='inspect'){print(sprintf('%J',poolstate.inspect(root,fs.readfile(root+'/expected'))));exit(0);}prepare_pool('nailink');ok=true;}catch(e){error=e.message;}
print(sprintf('%J',{ok,error,elapsed:monotime()-start,reason:fs.readfile(root+'/job/reason')}));exit(ok?0:1);
"""

@unittest.skipUnless(UCODE,'requires actual OpenWrt ucode/socket')
class PoolStart(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        for name in ('etc/adzero','etc/init.d','bin','tmp','job'):(self.root/name).mkdir(parents=True)
        (self.root/'profile').write_text(json.dumps(PROFILE))
        service=self.root/'service';service.write_text('#!/bin/sh\ndir=${0%/*}\necho "$1" >> "$dir/calls"\n[ ! -f "$dir/fail-$1" ] || exit 1\n[ "$1" != start ] || touch "$dir/start"\n');service.chmod(0o755)
        init=self.root/'etc/init.d/adzero-dns';init.write_text('#!/bin/sh\n');init.chmod(0o755)
        # Simulate builds without CONFIG_FEATURE_FANCY_SLEEP. Even a future
        # accidental fallback must fail this test rather than silently spin.
        sleep=self.root/'bin/sleep';sleep.write_text('#!/bin/sh\necho called > "${0%/*}/../external-sleep"\nexit 1\n');sleep.chmod(0o755)
        self.script=self.root/'prepare.uc';self.script.write_text(harness())
        self.env={**os.environ,'PATH':str(self.root/'bin')+':'+os.environ['PATH'],'ADZERO_JOB_CONTEXT':str(self.root/'job')}
        self.call('inspect')
    def call(self,mode='prepare'):
        p=subprocess.run(UCODE+[str(self.script),str(self.root),mode],env=self.env,text=True,capture_output=True,timeout=6)
        self.assertNotIn('invalid number',p.stderr);self.assertFalse((self.root/'external-sleep').exists())
        self.assertTrue(p.stdout,p.stderr)
        return p,json.loads(p.stdout)
    def health(self,**changes):
        value={'profile':(self.root/'expected').read_text(),'updated':time.monotonic(),**changes}
        path=self.root/'tmp/adzero-dns-pool.json';temp=path.with_suffix('.new');temp.write_text(json.dumps(value));temp.chmod(0o600);temp.replace(path);return path
    def delayed(self,delay,**changes):
        stop=threading.Event()
        def produce():
            while not stop.wait(.005):
                if (self.root/'start').exists():break
            if not stop.wait(delay):self.health(**changes)
        worker=threading.Thread(target=produce);worker.start()
        def end():stop.set();worker.join(2)
        self.addCleanup(end)
    def test_delayed_650ms_succeeds_without_external_fractional_sleep(self):
        self.delayed(.65);p,r=self.call();self.assertEqual(p.returncode,0,r);self.assertGreaterEqual(r['elapsed'],.6)
    def test_delayed_one_second_succeeds(self):
        self.delayed(1);p,r=self.call();self.assertEqual(p.returncode,0,r);self.assertGreaterEqual(r['elapsed'],.95)
    def test_near_deadline_is_checked_again(self):
        self.delayed(2.85);p,r=self.call();self.assertEqual(p.returncode,0,r);self.assertGreaterEqual(r['elapsed'],2.8)
    def test_missing_health_rejects_after_real_bounded_wait(self):
        p,r=self.call();self.assertEqual(p.returncode,1);self.assertEqual(r['reason'],'dns_pool_not_ready');self.assertGreaterEqual(r['elapsed'],2.95);self.assertLess(r['elapsed'],4)
    def test_enable_and_start_request_failures_are_specific(self):
        for action in ('enable','start'):
            with self.subTest(action=action):
                flag=self.root/('fail-'+action);flag.touch();p,r=self.call();flag.unlink()
                self.assertEqual(p.returncode,1);self.assertEqual(r['reason'],'dns_pool_start_failed');self.assertLess(r['elapsed'],1)
    def test_fresh_matching_legacy_health_reuses_the_existing_instance(self):
        self.health();p,r=self.call();self.assertEqual(p.returncode,0,r);self.assertNotIn('start',(self.root/'calls').read_text())
    def test_stale_failure_receipt_cannot_abort_a_new_attempt(self):
        self.health(state='error',reason='dns_pool_bind_failed');time.sleep(.03);self.delayed(.65)
        p,r=self.call();self.assertEqual(p.returncode,0,r);self.assertGreaterEqual(r['elapsed'],.6)
    def test_new_runtime_failure_is_reported_without_waiting_three_seconds(self):
        self.delayed(.1,state='error',reason='dns_pool_bind_failed');p,r=self.call()
        self.assertEqual(p.returncode,1);self.assertEqual(r['reason'],'dns_pool_bind_failed');self.assertLess(r['elapsed'],1)
    def test_invalid_health_never_claims_readiness(self):
        cases=[({'profile':'other'},'dns_pool_profile_mismatch'),({'updated':time.monotonic()-4},'dns_pool_stale'),({'updated':time.monotonic()+10},'dns_pool_stale'),({'updated':'bad'},'dns_pool_state_invalid'),({'state':'unknown'},'dns_pool_state_invalid'),({'pid':'999999999'},'dns_pool_process_exited')]
        for fields,reason in cases:
            with self.subTest(fields=fields):
                self.health(**fields);_,r=self.call('inspect');self.assertFalse(r['ready']);self.assertEqual(r['reason'],reason)
    def test_bad_permissions_symlinks_and_large_records_are_rejected(self):
        path=self.health();path.chmod(0o644);_,r=self.call('inspect');self.assertEqual(r['reason'],'dns_pool_state_invalid')
        path.unlink();path.symlink_to(self.root/'profile');_,r=self.call('inspect');self.assertEqual(r['reason'],'dns_pool_state_invalid')
        path.unlink();path.write_text('x'*10001);path.chmod(0o600);_,r=self.call('inspect');self.assertEqual(r['reason'],'dns_pool_state_invalid')
    def test_current_plugin_pool_selection_covers_group_modes_and_strict(self):
        source=(LIB/'adapter.uc').read_text();functions=source[source.index('passwall_pool_foreign=function()'):source.index('\nprepare_pool=function')]
        for domestic,foreign,strict in [('single','single',False),('parallel','single',False),('single','parallel',False),('parallel','parallel',False),('single','single',True)]:
            p=json.loads(json.dumps(PROFILE));p['domestic']['mode']=domestic;p['foreign']['mode']=foreign;p['strict']=strict
            script=self.root/'selection.uc';script.write_text("import * as route from '"+str(LIB/'routing-lib.uc')+"';let dns_profile=route.profile("+json.dumps(p)+");let passwall_pool_foreign,pool_needed,uci={get:()=> 'tcp'};"+functions+"print(sprintf('%J',map(['nailink','passwall','openclash','nikki'],p=>!!pool_needed(p))));")
            run=subprocess.run(UCODE+[str(script)],text=True,capture_output=True);self.assertEqual(run.returncode,0,run.stderr)
            needed=strict or domestic=='parallel' or foreign=='parallel';self.assertEqual(json.loads(run.stdout),[needed,needed,False,False])
    def test_nailink_strict_prerequisite_still_requires_local_socks(self):
        source=(LIB/'adapter.uc').read_text();function=source[source.index('policy_prerequisites=function(plugin)'):source.index('\ntry {')]
        for port in [0,1070]:
            p=json.loads(json.dumps(PROFILE));p.update(strict=True,proxy_port=port)
            script=self.root/'strict.uc';script.write_text("import * as route from '"+str(LIB/'routing-lib.uc')+"';let dns_profile=route.profile("+json.dumps(p)+");let policy_prerequisites,split_enabled=true,calls=[],progress={failure:()=>true},guard=s=>push(calls,s),strict_target=()=>true,pool_preflight=()=>push(calls,'pool');"+function+"let ok=true;try{policy_prerequisites('nailink');}catch(e){ok=false;}print(sprintf('%J',{ok,calls}));")
            run=subprocess.run(UCODE+[str(script)],text=True,capture_output=True);self.assertEqual(run.returncode,0,run.stderr);r=json.loads(run.stdout)
            self.assertEqual(r['ok'],bool(port));self.assertEqual(r['calls'],['preflight','pool'] if port else [])
