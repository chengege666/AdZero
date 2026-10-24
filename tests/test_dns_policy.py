"""Production policy compiler and concurrent sockets, no router services."""
import copy,json,os,shlex,socket,struct,subprocess,tempfile,threading,time,unittest
from pathlib import Path
from test_dns_enhance import query,answer
import test_routing as routing
ROOT=Path(__file__).resolve().parents[1]
UCODE=shlex.split(os.environ.get('ADZERO_UCODE',''))
PROFILE={'domestic':{'servers':['223.5.5.5','119.29.29.29'],'active':'223.5.5.5','mode':'parallel'},'foreign':{'servers':['1.1.1.1','8.8.8.8'],'active':'1.1.1.1','mode':'parallel'}}

@unittest.skipUnless(UCODE,'requires actual OpenWrt ucode/socket')
class PolicyTest(unittest.TestCase):
    compile=routing.RoutingCompilerTest.compile
    def test_profile_modes_limits_and_overlap(self):
        self.assertEqual(self.compile('profile',PROFILE),PROFILE)
        for change in [dict(strict='yes'),dict(proxy_port=53),dict(failover='yes')]:
            p={**copy.deepcopy(PROFILE),**change};self.compile('profile',p,ok=False)
        for addresses in [['1.1.1.1','8.8.8.8','9.9.9.9','8.8.4.4'],['1.1.1.1','223.5.5.5']]:
            p=copy.deepcopy(PROFILE);p['foreign']['servers']=addresses;self.compile('profile',p,ok=False)
        p=copy.deepcopy(PROFILE);p['foreign']['mode']='roundrobin';self.compile('profile',p,ok=False)
    def test_all_foreign_addresses_pin_to_current_group(self):
        p={**copy.deepcopy(PROFILE),'strict':True,'proxy_port':1070}
        raw='upstream { user: "udp://9.9.9.9:53" }\nrouting { request { qname(user.example) -> user\n fallback: user } }'
        result=self.compile('dae_dns',raw,p)
        self.assertIn('tcp://127.0.0.1:5356',result);self.assertIn('tcp://127.0.0.1:5357',result)
        self.assertLess(result.index('qname(regex: ".*")'),result.index('qname(user.example)'))
        transport=self.compile('dae_routing','fallback: proxy\n','proxy',p)
        self.assertIn('dip(1.1.1.1, 8.8.8.8) && dport(53) -> proxy',transport)
        cfg={'dns':{'enable':True,'nameserver-policy':{'user.example':['9.9.9.9'],'rule-set:adzero-dns':'rcode://success'}},'rules':['MATCH,Proxy'],'proxy-groups':[{'name':'Proxy'}]}
        result=self.compile('mihomo',cfg,'/domains','/ips',p)['config']['dns']
        self.assertEqual(result['nameserver'],['tcp://1.1.1.1:53#Proxy','tcp://8.8.8.8:53#Proxy'])
        self.assertNotIn('user.example',result['nameserver-policy']);self.assertIn('rule-set:adzero-dns',result['nameserver-policy'])
        self.assertNotIn('direct-nameserver',result);self.assertTrue(result['direct-nameserver-follow-policy'])
    def test_effective_change_ignores_unused_backups_but_tracks_mode(self):
        a=copy.deepcopy(PROFILE);a['domestic'].pop('mode');b=copy.deepcopy(a);b['domestic']['servers'].append('180.76.76.76')
        self.assertEqual(self.compile('effective',a),self.compile('effective',b))
        b['domestic']['mode']='parallel';self.assertNotEqual(self.compile('effective',a),self.compile('effective',b))
    def test_guard_scope_and_fail_closed_rules(self):
        body=dict(lan=dict(device='br-lan',address='192.168.2.1',mask=24),profile=PROFILE,ready=False,bootstrap=False)
        def render():
            r=subprocess.run(UCODE+[str(ROOT/'scripts/dns_guard_transform.uc')],input=json.dumps(body),text=True,capture_output=True,check=True);return r.stdout
        held=render();self.assertIn('priority -110',held);self.assertIn('ct original proto-dst 53 drop',held)
        self.assertNotIn('443',held);self.assertNotIn('1.1.1.1',held);self.assertNotIn('223.5.5.5',held)
        body.update(ready=True,bootstrap=True);active=render()
        self.assertIn('ip daddr { 223.5.5.5, 119.29.29.29 }',active);self.assertNotIn('8.8.8.8',active)
        self.assertIn('meta nfproto ipv6',active);self.assertIn('th dport { 53, 853 } drop',active)

def freeport():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
def read(c,n):
    b=b''
    while len(b)<n:
        p=c.recv(n-len(b))
        if not p:raise OSError('short read')
        b+=p
    return b

@unittest.skipUnless(UCODE,'requires actual OpenWrt ucode/socket')
class PoolTest(unittest.TestCase):
    def peer(self,delay=0,code=0,bad=False,socks=False,persistent=False,drop_reuse=False,bad_reuse=False):
        s=socket.socket();s.bind(('127.0.0.1',0));s.listen();s.settimeout(.1);self.addCleanup(s.close)
        stop=threading.Event();self.addCleanup(stop.set);seen=[]
        if not hasattr(self,'connections'):self.connections={}
        connections=self.connections[s.getsockname()[1]]=[]
        def handle(c):
            connections.append(True)
            with c:
                c.settimeout(4)
                try:
                    if socks:
                        self.assertEqual(read(c,3),b'\x05\x01\0');c.sendall(b'\x05\0');h=read(c,4);host=read(c,4 if h[3]==1 else 16);port=read(c,2);seen.append((host,struct.unpack('!H',port)[0]));c.sendall(b'\x05\0\0\x01\x7f\0\0\x01\0\x35')
                    uses=0
                    while True:
                        q=read(c,struct.unpack('!H',read(c,2))[0]);uses+=1
                        if drop_reuse and uses>1:return
                        seen.append(q);time.sleep(delay)
                        r=bytearray(answer(q,[]));r[3]=(r[3]&240)|code
                        if bad or bad_reuse and uses>1:r[1]^=1
                        frame=struct.pack('!H',len(r))+r;c.sendall(frame[:1]);c.sendall(frame[1:])
                        if not persistent:return
                except (OSError,AssertionError):pass
        def run():
            while not stop.is_set():
                try:c,_=s.accept();threading.Thread(target=handle,args=(c,),daemon=True).start()
                except (OSError,socket.timeout):pass
        threading.Thread(target=run,daemon=True).start()
        return {'address':'127.0.0.1','port':s.getsockname()[1]},seen
    def start(self,domestic,foreign=None,options=None):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);d=Path(temp.name)
        ports={g:freeport() for g in ['domestic','foreign','split']}
        (d/'config').write_text(json.dumps(dict(groups=dict(domestic=domestic,foreign=foreign or domestic),ports=ports,options=options or {})))
        p=subprocess.Popen(UCODE+[str(ROOT/'scripts/dns_pool_fixture.uc'),str(d/'config'),str(d/'ready')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        def end():
            if p.poll() is None:p.terminate()
            _,err=p.communicate(timeout=4)
            self.assertNotIn('error:',err.lower())
        self.addCleanup(end)
        for _ in range(60):
            if (d/'ready').exists():return ports
            if p.poll() is not None:self.fail(p.communicate())
            time.sleep(.02)
        self.fail('pool not ready')
    def ask(self,port,tcp=False,name='shop.example'):
        q=query(name);start=time.monotonic()
        if tcp:
            with socket.create_connection(('127.0.0.1',port),3) as c:
                c.settimeout(3);c.sendall(struct.pack('!H',len(q))+q);r=read(c,struct.unpack('!H',read(c,2))[0])
        else:
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as c:c.settimeout(3);c.sendto(q,('127.0.0.1',port));r,_=c.recvfrom(65535)
        self.assertEqual(r[:2],q[:2]);return r,time.monotonic()-start
    def test_parallel_first_valid_udp_and_tcp_and_group_isolation(self):
        slow,a=self.peer(.5);fast,b=self.peer(.03);foreign,f=self.peer(.02,code=3);ports=self.start([slow,fast],[foreign])
        for tcp in [False,True]:
            _,elapsed=self.ask(ports['domestic'],tcp);self.assertLess(elapsed,.4)
        self.assertEqual(len(a),2);self.assertEqual(len(b),2);self.assertFalse(f)
        r,_=self.ask(ports['foreign']);self.assertEqual(r[3]&15,3);self.assertEqual(len(f),1)
    def test_broken_fast_answer_and_servfail_never_win(self):
        wrong,_=self.peer(.001,bad=True);failure,_=self.peer(.001,code=2);valid,_=self.peer(.05,code=3);ports=self.start([wrong,failure,valid])
        r,elapsed=self.ask(ports['domestic']);self.assertEqual(r[3]&15,3);self.assertGreater(elapsed,.03)
    def test_all_failed_returns_servfail_without_group_fallback(self):
        bad,_=self.peer(.001,code=2);other,seen=self.peer(.001);ports=self.start([bad],[other])
        r,elapsed=self.ask(ports['domestic']);self.assertEqual(r[3]&15,2);self.assertFalse(seen);self.assertLess(elapsed,2.5)
    def test_strict_split_and_foreign_socks_only(self):
        cn,seen_cn=self.peer(.01);proxy,seen=self.peer(.01,socks=True)
        ports=self.start([cn],[dict(address='1.1.1.1',port=53),dict(address='8.8.8.8',port=53)],dict(proxy_port=proxy['port'],domains={'example.cn':True}))
        r,_=self.ask(ports['split'],name='www.example.cn');self.assertEqual(r[3]&15,0);self.assertFalse(seen)
        for tcp in [False,True]:self.ask(ports['split'],tcp,name='chatgpt.com')
        destinations=[v for v in seen if isinstance(v,tuple)]
        self.assertIn((socket.inet_aton('1.1.1.1'),53),destinations);self.assertIn((socket.inet_aton('8.8.8.8'),53),destinations)
        self.assertEqual(len(seen_cn),1)
    def test_dead_socks_never_falls_back_to_direct(self):
        direct,seen=self.peer(.01);ports=self.start([direct],[direct],dict(proxy_port=freeport()))
        r,_=self.ask(ports['foreign']);self.assertEqual(r[3]&15,2);self.assertFalse(seen)

    def test_warm_tcp_upstream_is_reused_across_client_transports_but_not_groups(self):
        endpoint,seen=self.peer(.001,persistent=True);ports=self.start([endpoint],[endpoint])
        for tcp in (False,True,False):self.assertEqual(self.ask(ports['domestic'],tcp)[0][3]&15,0)
        self.assertEqual(len(self.connections[endpoint['port']]),1)
        self.ask(ports['foreign']);self.assertEqual(len(self.connections[endpoint['port']]),2)
        self.ask(ports['domestic']);self.assertEqual(len(self.connections[endpoint['port']]),2)
        self.assertEqual(len(seen),5)

    def test_socks_handshake_is_reused_without_direct_foreign_fallback(self):
        direct,unused=self.peer(.001);proxy,seen=self.peer(.001,socks=True,persistent=True)
        ports=self.start([direct],[dict(address='1.1.1.1',port=53)],dict(proxy_port=proxy['port']))
        for tcp in (False,True,False):self.assertEqual(self.ask(ports['foreign'],tcp)[0][3]&15,0)
        self.assertEqual(len(self.connections[proxy['port']]),1)
        self.assertEqual(len([v for v in seen if isinstance(v,tuple)]),1);self.assertFalse(unused)

    def test_closed_reused_transport_reconnects_once_within_original_deadline(self):
        endpoint,seen=self.peer(.001,persistent=True,drop_reuse=True);ports=self.start([endpoint])
        self.ask(ports['domestic']);reply,elapsed=self.ask(ports['domestic'])
        self.assertEqual(reply[3]&15,0);self.assertLess(elapsed,1)
        self.assertEqual(len(self.connections[endpoint['port']]),2);self.assertEqual(len(seen),2)

    def test_mismatched_reused_answer_is_not_retried_or_accepted(self):
        endpoint,_=self.peer(.001,persistent=True,bad_reuse=True);ports=self.start([endpoint])
        self.ask(ports['domestic']);reply,_=self.ask(ports['domestic'])
        self.assertEqual(reply[3]&15,2);self.assertEqual(len(self.connections[endpoint['port']]),1)

    def test_reused_upstream_has_a_bounded_query_lifetime(self):
        endpoint,seen=self.peer(.001,persistent=True);ports=self.start([endpoint])
        for _ in range(33):self.assertEqual(self.ask(ports['domestic'])[0][3]&15,0)
        self.assertEqual(len(self.connections[endpoint['port']]),2);self.assertEqual(len(seen),33)
