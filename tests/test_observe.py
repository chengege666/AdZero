"""Real production DNS/pcap decoding and correlation, with synthetic wire packets.

These tests do not claim LAN capture: check_observe_runtime.py covers the real
tcpdump/ucode process lifecycle and isolated UDP traffic separately.
"""
import base64
import ipaddress
import json
import os
from pathlib import Path
import shlex
import struct
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
UCODE = shlex.split(os.environ.get('ADZERO_UCODE', ''))


def dns(name='ads.example', ident=42, response=False, rcode=0, address=None,
        qtype=1, tc=False):
    qname = b''.join(bytes([len(p)]) + p.encode() for p in name.split('.')) + b'\0'
    flags = 0x100 | (0x8000 if response else 0) | rcode | (0x200 if tc else 0)
    payload = struct.pack('!HHHHHH', ident, flags, 1, bool(address), 0, 0)
    payload += qname + struct.pack('!HH', qtype, 1)
    if address:
        raw = ipaddress.ip_address(address).packed
        payload += b'\xc0\x0c' + struct.pack('!HHIH', 1 if len(raw)==4 else 28, 1, 60, len(raw)) + raw
    return payload


def packet(payload, response=False, v6=False, tcp=False, seq=1, vlan=False, link=1):
    src = '2001:db8::2' if v6 else '192.168.2.10'
    dst = '2001:db8::1' if v6 else '192.168.2.1'
    sport, dport = 52000, 53
    if response:
        src, dst, sport, dport = dst, src, dport, sport
    if tcp:
        transport = struct.pack('!HHIIBBHHH', sport,dport,seq,0,0x50,0x18,4096,0,0) + payload
    else:
        transport = struct.pack('!HHHH',sport,dport,8+len(payload),0)+payload
    protocol = 6 if tcp else 17
    if v6:
        network=struct.pack('!IHBB',6<<28,len(transport),protocol,64)+ipaddress.ip_address(src).packed+ipaddress.ip_address(dst).packed
        ethertype=0x86dd
    else:
        network=struct.pack('!BBHHHBBH4s4s',0x45,0,20+len(transport),0,0,64,protocol,0,ipaddress.ip_address(src).packed,ipaddress.ip_address(dst).packed)
        ethertype=0x0800
    if link==1:
        header=b'\0'*12+struct.pack('!H',ethertype)
        if vlan:header=b'\0'*12+struct.pack('!HHH',0x8100,1,ethertype)
    elif link==113:header=b'\0'*14+struct.pack('!H',ethertype)
    elif link==276:header=struct.pack('!HHI',ethertype,0,4)+b'\0'*12
    else:header=b''
    return header+network+transport


def pcap(*packets, little=True, link=1):
    fmt='<' if little else '>'
    raw=struct.pack(fmt+'IHHIIII',0xa1b2c3d4,2,4,0,0,4096,link)
    for n,p in enumerate(packets):raw+=struct.pack(fmt+'IIII',n,0,len(p),len(p))+p
    return raw


@unittest.skipUnless(UCODE,'set ADZERO_UCODE to a real OpenWrt ucode runtime')
class ObserveTest(unittest.TestCase):
    def run_code(self,operation,success=True,**data):
        result=subprocess.run(UCODE+[str(ROOT/'scripts/observe_transform.uc')],input=json.dumps({'operation':operation,**data}),text=True,capture_output=True)
        self.assertEqual(result.returncode==0,success,result.stderr)
        return json.loads(result.stdout) if success else None

    def decode(self,payload):return self.run_code('dns',data=base64.b64encode(payload).decode())
    def packets(self,raw,**args):return self.run_code('pcap',data=base64.b64encode(raw).decode(),**args)

    def test_empty_noerror_nxdomain_refused_are_negative(self):
        for rcode in (0,3,5):
            self.assertTrue(self.decode(dns(response=True,rcode=rcode))['blocked'])

    def test_timeout_servfail_truncated_and_positive_are_not_blocks(self):
        for data in (dns(),dns(response=True,rcode=2),dns(response=True,tc=True),dns(response=True,address='1.2.3.4')):
            self.assertFalse(self.decode(data)['blocked'])

    def test_zero_addresses_v4_v6(self):
        for address in ('0.0.0.0','::','127.0.0.1'):
            self.assertTrue(self.decode(dns(response=True,address=address))['blocked'])

    def test_invalid_compression_lengths_and_questions(self):
        for raw in (b'',b'\0'*12,struct.pack('!HHHHHH',1,0x8000,1,0,0,0)+b'\xc0\x0c'+b'\0'*4,dns(response=True,address='1.2.3.4')[:-1]):
            self.assertIsNone(self.decode(raw))

    def test_udp_v4_v6_vlan_sll_and_chunking(self):
        for v6 in (False,True):
            for link in (1,113,276,101):
                raw=pcap(packet(dns(),v6=v6,link=link),packet(dns(response=True),response=True,v6=v6,link=link),link=link)
                messages=self.packets(raw,chunk=7)
                self.assertEqual(len(messages),2,(v6,link))
                self.assertEqual(messages[0]['name'],'ads.example')
                self.assertTrue(messages[1]['blocked'])
        self.assertEqual(len(self.packets(pcap(packet(dns(),vlan=True)))),1)

    def test_big_endian_and_bad_capture(self):
        self.assertEqual(len(self.packets(pcap(packet(dns()),little=False))),1)
        self.run_code('pcap',data=base64.b64encode(b'bad!'*10).decode(),success=False)

    def test_tcp_split_message_and_retransmit(self):
        data=dns(response=True,rcode=3);framed=struct.pack('!H',len(data))+data
        pieces=[packet(framed[:8],response=True,tcp=True,seq=100),packet(framed[:8],response=True,tcp=True,seq=100),packet(framed[8:],response=True,tcp=True,seq=108)]
        messages=self.packets(pcap(*pieces))
        self.assertEqual(len(messages),1)
        self.assertTrue(messages[0]['blocked'])

    def event(self,response=False,domain='ads.example',ident=42,**changes):
        data={'name':domain,'id':ident,'qtype':1,'response':response,'from':'192.168.2.1' if response else '192.168.2.10','to':'192.168.2.10' if response else '192.168.2.1','sport':53 if response else 52000,'dport':52000 if response else 53,'protocol':'udp','positive':False,'blocked':response}
        return {**data,**changes}

    def track(self,events,test=None):
        return self.run_code('tracker',rules=['ads.example'],test=test,events=[{'at':n+1,'dns':e} for n,e in enumerate(events)])

    def test_queries_alone_and_unrelated_nxdomain_never_count(self):
        result=self.track([self.event(),self.event(domain='other.example',ident=43),self.event(True,domain='other.example',ident=43)])
        self.assertEqual(result['counts'],{'queries':2,'blocked':0,'answered':1,'overflow':0})

    def test_duplicate_query_and_response_are_counted_once(self):
        result=self.track([self.event(),self.event(),self.event(True),self.event(True)])
        self.assertEqual(result['counts']['queries'],1)
        self.assertEqual(result['counts']['blocked'],1)

    def test_parent_rule_and_actual_positive_answer(self):
        result=self.track([self.event(domain='sub.ads.example'),self.event(True,domain='sub.ads.example'),self.event(ident=43),self.event(True,ident=43,blocked=False,positive=True)])
        self.assertEqual(result['counts']['blocked'],1)
        self.assertEqual(result['counts']['answered'],2)

    def test_missing_or_wrong_transaction_cannot_count(self):
        result=self.track([self.event(),self.event(True,ident=43),self.event(True,**{'from':'8.8.8.8'})])
        self.assertEqual(result['counts']['blocked'],0)

    def test_config_change_and_disabled_capture_invalidate_pending(self):
        for active in (False,True):
            result=self.run_code('tracker',rules=['ads.example'],events=[{'at':1,'dns':self.event()},{'configure':True,'generation':'changed','active':active},{'at':2,'dns':self.event(True)}])
            self.assertEqual(result['counts']['blocked'],0)

    def test_terminal_challenge_requires_marker_same_client_and_both_results(self):
        test={'nonce':'a'*32,'sample':'ads.example','control':'www.baidu.com','deadline':120}
        events=[self.event(domain='a'*32+'.adzero.invalid'),self.event(),self.event(True),self.event(domain='www.baidu.com',ident=45),self.event(True,domain='www.baidu.com',ident=45,positive=True,blocked=False)]
        result=self.track(events,test)
        self.assertTrue(result['test']['marker'] and result['test']['normal'] and result['test']['blocked'])
        self.assertEqual(result['counts']['queries'],0,'test traffic must not inflate counts')
        events[2]['to']='192.168.2.99'
        result=self.track(events,test)
        self.assertFalse(result['test'].get('blocked',False))
