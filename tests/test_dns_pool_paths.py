"""Native policy/preflight tests; transport integration uses a private netns."""
import json,os,shlex,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
LIB=ROOT/'luci-app-adzero/root/usr/libexec/adzero'
UCODE=shlex.split(os.environ.get('ADZERO_UCODE',''))

@unittest.skipUnless(UCODE,'requires OpenWrt ucode/socket')
class PoolPaths(unittest.TestCase):
    def run_ucode(self,body):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'case.uc';p.write_text("import * as state from '"+str(LIB/'dns-pool-state.uc')+"';import * as route from '"+str(LIB/'routing-lib.uc')+"';import * as wire from '"+str(LIB/'dns-enhance-lib.uc')+"';function prof(v){let p=route.profile(null);for(let k,vv in v)p[k]=index(['domestic','foreign'],k)>=0?{...p[k],...vv}:vv;return p;}function ok(q){return substr(q,0,2)+b64dec('gYAAAQABAAAAAA==')+substr(q,12)+b64dec('wAwAAQABAAAAPAAEwAACCQ==');}"+body)
            r=subprocess.run(UCODE+[str(p)],capture_output=True,text=True,timeout=10)
            self.assertEqual(r.returncode,0,r.stderr);return json.loads(r.stdout)
    def test_group_plugin_and_transport_matrix(self):
        for plugin,mode in [('nailink','tcp'),('passwall','tcp'),('passwall','xray'),('passwall','sing-box'),('openclash','tcp'),('nikki','tcp'),('none','tcp')]:
            for domestic,foreign,strict in [('single','single',False),('parallel','single',False),('single','parallel',False),('parallel','parallel',False),('single','single',True)]:
                p=dict(domestic=dict(mode=domestic),foreign=dict(mode=foreign),strict=strict)
                r=self.run_ucode('print(sprintf(\'%J\',state.paths(prof('+json.dumps(p)+'),'+json.dumps(plugin)+','+json.dumps(mode)+')));')
                self.assertEqual(r,dict(domestic=plugin=='nailink' and (strict or domestic=='parallel') or plugin=='passwall' and domestic=='parallel',foreign=plugin=='nailink' and (strict or foreign=='parallel') or plugin=='passwall' and (foreign=='parallel' or strict and mode=='tcp')))
    def test_missing_socks_never_attempts_a_foreign_direct_request(self):
        r=self.run_ucode("let calls=0,r=state.preflight(prof({foreign:{mode:'parallel'}}),'nailink','tcp',()=>{calls++;return null;});print(sprintf('%J',{r,calls}));")
        self.assertEqual(r,dict(r=dict(ready=False,reason='dns_socks_required'),calls=0))
    def test_candidate_socks_port_and_first_valid_same_group_are_used(self):
        r=self.run_ucode("let calls=[],p={domestic:{mode:'parallel',servers:['192.0.2.53','192.0.2.55'],active:'192.0.2.53'},foreign:{mode:'parallel',servers:['192.0.2.54'],active:'192.0.2.54'},proxy_port:23456};let r=state.preflight(p,'nailink','tcp',(a,port,q,tcp,socks)=>{push(calls,{a,port,tcp,socks,name:wire.message(q).name});return a=='192.0.2.53'?null:ok(q);});print(sprintf('%J',{r,calls}));")
        self.assertEqual(r['r'],dict(ready=True));self.assertEqual([c['a'] for c in r['calls']],['192.0.2.53','192.0.2.55','192.0.2.54'])
        self.assertTrue(all(c['tcp'] and c['port']==53 for c in r['calls']));self.assertEqual([c['socks'] for c in r['calls']],[0,0,23456])
        self.assertEqual([c['name'] for c in r['calls']],['www.baidu.com','www.baidu.com','www.google.com'])
    def test_failed_domestic_never_borrows_foreign_answer(self):
        r=self.run_ucode("let calls=[],r=state.preflight(prof({domestic:{mode:'parallel'},foreign:{mode:'parallel'},proxy_port:23456}),'nailink','tcp',(a,p,q,t,s)=>{push(calls,s);return wire.reply(q,2);});print(sprintf('%J',{r,calls}));")
        self.assertEqual(r['r'],dict(ready=False,reason='dns_pool_domestic_failed'));self.assertTrue(all(s==0 for s in r['calls']))
    def test_truncation_and_servfail_cannot_confirm_a_listener(self):
        for response in ["wire.reply(q,2)","wire.reply(q,3)","wire.reply(q,0)","substr(q,0,2)+wire.word(0x8380)+substr(q,4)","null"]:
            r=self.run_ucode("let r=state.probe(prof({domestic:{mode:'parallel'}}),'nailink','tcp',{domestic:15356},(a,p,q,t,s)=>"+response+");print(sprintf('%J',r));")
            self.assertEqual(r,dict(ready=False,reason='dns_pool_domestic_failed'))
    def test_native_plugins_do_not_probe_or_require_shared_pool(self):
        r=self.run_ucode("let calls=0,p=prof({domestic:{mode:'parallel'},foreign:{mode:'parallel'},strict:true});let rows=map(['openclash','nikki'],plugin=>state.preflight(p,plugin,'tcp',()=>{calls++;return null;}));print(sprintf('%J',{rows,calls}));")
        self.assertEqual(r,dict(rows=[dict(ready=True),dict(ready=True)],calls=0))
        self.assertEqual(self.run_ucode("print(sprintf('%J',state.paths(prof({domestic:{mode:'parallel'},foreign:{mode:'parallel'}}),'nailink','tcp',false)));"),dict(domestic=False,foreign=False))
