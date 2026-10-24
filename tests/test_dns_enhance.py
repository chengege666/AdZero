"""Real ucode DNS parsing/policy, including hostile wire messages."""
import base64
import json
import os
from pathlib import Path
import shlex
import struct
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
UCODE=shlex.split(os.environ.get('ADZERO_UCODE',''))
def name(n): return (b''.join(bytes([len(x)])+x.encode() for x in n.split('.')) if n else b'')+b'\0'
def query(n='shop.example',kind=1): return struct.pack('!6H',123,0x100,1,0,0,0)+name(n)+struct.pack('!HH',kind,1)
def answer(q,aliases):
    raw=q[:2]+struct.pack('!5H',0x81a0,1,len(aliases),0,0)+q[12:]
    for owner,target in aliases:
        value=name(target);raw+=name(owner)+struct.pack('!HHIH',5,1,300,len(value))+value
    return raw

def service_answer(q,target='ads.example',kind=65,priority=0,owner='shop.example',extra=b'',additional=False):
    value=struct.pack('!H',priority)+name(target)+extra
    record=name(owner)+struct.pack('!HHIH',kind,1,300,len(value))+value
    return q[:2]+struct.pack('!5H',0x81a0,1,0 if additional else 1,0,1 if additional else 0)+q[12:]+record

@unittest.skipUnless(UCODE,'requires actual ucode')
class EnhanceTest(unittest.TestCase):
    def call(self,op,args,wire=(),output_wire=False,ok=True):
        args=list(args)
        for i in wire: args[i]=base64.b64encode(args[i]).decode()
        r=subprocess.run(UCODE+[str(ROOT/'scripts/dns_enhance_transform.uc')],input=json.dumps(dict(operation=op,args=args,wire=list(wire),output_wire=output_wire)),text=True,capture_output=True,timeout=10)
        self.assertEqual(r.returncode==0,ok,r.stderr)
        if ok:return json.loads(r.stdout)
    def test_reachable_cname_only_and_chains(self):
        q=query();r=answer(q,[('shop.example','first.example'),('first.example','sub.ads.example')])
        v=self.call('decision',[q,r,{'ads.example':True},[],None,True],[0,1])
        self.assertEqual((v['kind'],v['rule']),('cname','ads.example'))
        self.assertFalse(self.call('decision',[q,answer(q,[('unrelated.example','ads.example')]),{'ads.example':True},[],None,True],[0,1])['blocked'])
        self.assertFalse(self.call('decision',[q,r,{'ads.example':True},['shop.example'],None,True],[0,1])['blocked'])
    def test_wrong_response_and_cyclic_pointer_rejected(self):
        q=query();r=bytearray(answer(q,[]));r[1]^=1
        self.call('decision',[q,bytes(r),{},[],None,True],[0,1],ok=False)
        self.call('message',[query()[:12]+b'\xc0\x0c'+b'\0\1\0\1'],[0],ok=False)
        self.call('message',[query()+b'garbage'],[0],ok=False)
    def test_alias_domain_boundaries_and_explicit_exemptions(self):
        q=query();rules={'ads.example':True}
        for target in ('notads.example','ads.example.safe.example'):
            r=answer(q,[('shop.example',target)])
            self.assertFalse(self.call('decision',[q,r,rules,[],None,True],[0,1])['blocked'])
        r=answer(q,[('shop.example','sub.ads.example')])
        self.assertFalse(self.call('decision',[q,r,rules,['ads.example'],None,True],[0,1])['blocked'])
        d=dict(enabled=True,allowed=['shop.example'],blocked=[])
        self.assertFalse(self.call('decision',[q,r,rules,[],d,True],[0,1])['blocked'])
    def test_truncated_and_failed_answers_are_not_cname_blocks(self):
        q=query();raw=bytearray(answer(q,[('shop.example','ads.example')]))
        for flags in (0x8380,0x8182,0x8183):
            raw[2:4]=struct.pack('!H',flags)
            self.assertFalse(self.call('decision',[q,bytes(raw),{'ads.example':True},[],None,True],[0,1])['blocked'])
    def test_device_exception_and_synthetic_ad_clear(self):
        q=query();d={'enabled':True,'allowed':[],'blocked':['example']}
        self.assertTrue(self.call('decision',[q,None,{},[],d,True],[0])['blocked'])
        d['allowed']=['shop.example']
        self.assertFalse(self.call('decision',[q,None,{},[],d,True],[0])['blocked'])
        r=base64.b64decode(self.call('reply',[q,0],[0],True))
        self.assertFalse(struct.unpack('!H',r[2:4])[0]&0x20)
        self.assertEqual(struct.unpack('!3H',r[6:12]),(0,0,0))
    def test_config_limits_and_ip_validation(self):
        v=self.call('config',[{'devices':[dict(ip='192.168.2.107',name='PC',blocked=['ads.example'])]}])
        self.assertEqual(v['devices'][0]['blocked'],['ads.example'])
        for d in [dict(ip='8.8.8.8'),dict(ip='192.168.2.999'),dict(ip='192.168.02.1')]:
            self.call('config',[{'devices':[d]}],ok=False)
    def test_device_block_follows_reachable_alias_and_keeps_exceptions(self):
        q=query();r=answer(q,[('shop.example','sub.device.example')])
        device=dict(enabled=True,allowed=[],blocked=['device.example'])
        result=self.call('decision',[q,r,{},[],device,True],[0,1])
        self.assertEqual((result['blocked'],result['kind'],result['rule']),(True,'device','device.example'))
        for allowed in (['shop.example'],['device.example']):
            self.assertFalse(self.call('decision',[q,r,{},allowed,device,True],[0,1])['blocked'])
        device['allowed']=['device.example']
        self.assertFalse(self.call('decision',[q,r,{},[],device,True],[0,1])['blocked'])
        device['allowed']=[];device['enabled']=False
        self.assertFalse(self.call('decision',[q,r,{},[],device,True],[0,1])['blocked'])
    def test_https_and_svcb_alias_modes_block_only_reachable_matching_types(self):
        for kind in (64,65):
            q=query(kind=kind);r=service_answer(q,kind=kind)
            self.assertTrue(self.call('decision',[q,r,{'ads.example':True},[],None,True],[0,1])['blocked'])
            for options in (dict(priority=1),dict(owner='unrelated.example'),dict(kind=129-kind),dict(additional=True)):
                self.assertFalse(self.call('decision',[q,service_answer(q,**(dict(kind=kind)|options)),{'ads.example':True},[],None,True],[0,1])['blocked'])
            self.assertFalse(self.call('decision',[q,r,{'ads.example':True},['ads.example'],None,True],[0,1])['blocked'])
            self.assertFalse(self.call('decision',[q,r,{'ads.example':True},[],None,False],[0,1])['blocked'])
    def test_alias_mode_handles_root_parameters_and_cname_chain(self):
        q=query(kind=65)
        self.assertFalse(self.call('decision',[q,service_answer(q,target=''),{'ads.example':True},[],None,True],[0,1])['blocked'])
        # AliasMode parameters are ignored by RFC 9460, not interpreted as names.
        self.assertTrue(self.call('decision',[q,service_answer(q,extra=b'\x00\x01\x00\x00'),{'ads.example':True},[],None,True],[0,1])['blocked'])
        first=answer(q,[('shop.example','edge.example')]);last=service_answer(q,owner='edge.example')
        r=first[:6]+struct.pack('!H',2)+first[8:]+last[len(q):]
        self.assertTrue(self.call('decision',[q,r,{'ads.example':True},[],None,True],[0,1])['blocked'])
    def test_service_alias_does_not_change_address_queries_or_accept_short_rdata(self):
        q=query()
        self.assertFalse(self.call('decision',[q,service_answer(q),{'ads.example':True},[],None,True],[0,1])['blocked'])
        q=query(kind=65);head=q[:2]+struct.pack('!5H',0x8180,1,1,0,0)+q[12:]
        for data in (b'',b'\x00\x00',b'\x00\x00\x03ab'):
            raw=head+name('shop.example')+struct.pack('!HHIH',65,1,60,len(data))+data
            self.call('message',[raw],[0],ok=False)
    def test_failover_three_failures_cooldown_and_no_cross_group(self):
        group={'active':'a','servers':['a','b']};r=[dict(address='a',ok=False),dict(address='b',ok=True)]
        s=None
        for _ in range(2):s=self.call('fallback',[s,group,r,1000]);self.assertIsNone(s['next'])
        s=self.call('fallback',[s,group,r,1000]);self.assertEqual(s['next'],'b')
        s=self.call('fallback',[s,group,r,1001]);self.assertIsNone(s['next'])
        s=self.call('fallback',[{'failures':2,'last_switch':0},group,r,120]);self.assertEqual(s['next'],'b')
        s=self.call('fallback',[{'failures':2,'last_switch':0},group,[dict(address='a',ok=False),dict(address='outside',ok=True)],1000]);self.assertIsNone(s['next'])
