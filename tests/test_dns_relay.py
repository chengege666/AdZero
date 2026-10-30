"""Native ucode sockets against isolated loopback UDP/TCP DNS fixtures."""
import errno,json,os,shlex,socket,struct,subprocess,tempfile,threading,time,unittest
from pathlib import Path
from test_dns_enhance import query,answer
ROOT=Path(__file__).resolve().parents[1]
UCODE=shlex.split(os.environ.get('ADZERO_UCODE',''))
def bind_dns_fixture():
    # TCP and UDP have separate ephemeral-port allocators. Reserve both before
    # starting either fixture; an unrelated host TCP connection must not make
    # this DNS regression fail before the relay has even been launched.
    for _ in range(32):
        tcp=socket.socket();udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        try:
            tcp.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            tcp.bind(('127.0.0.1',0));udp.bind(tcp.getsockname())
            tcp.listen();tcp.settimeout(.1);udp.settimeout(.1)
            return udp,tcp
        except OSError as error:
            tcp.close();udp.close()
            if error.errno!=errno.EADDRINUSE:raise
    raise RuntimeError('No shared TCP/UDP fixture port available')

@unittest.skipUnless(UCODE,'requires actual ucode/socket')
class RelayTest(unittest.TestCase):
    def test_udp_tcp_cname_device_exemption_and_pipeline(self):
        udp,tcp=bind_dns_fixture();port=udp.getsockname()[1]
        self.addCleanup(udp.close);self.addCleanup(tcp.close);stop=threading.Event();self.addCleanup(stop.set)
        def respond(q):return answer(q,[('shop.example','ads.example')])
        def udp_run():
            while not stop.is_set():
                try:q,a=udp.recvfrom(65535);udp.sendto(respond(q),a)
                except (socket.timeout,OSError):pass
        def tcp_run():
            while not stop.is_set():
                try:
                    c,_=tcp.accept();c.settimeout(1)
                    with c:
                        h=c.recv(2);size=struct.unpack('!H',h)[0];q=b''
                        while len(q)<size:q+=c.recv(size-len(q))
                        r=respond(q);c.sendall(struct.pack('!H',len(r))+r)
                except (socket.timeout,OSError,struct.error):pass
        threads=[threading.Thread(target=f,daemon=True) for f in (udp_run,tcp_run)]
        for t in threads:t.start()
        with tempfile.TemporaryDirectory() as d:
            cfg=Path(d)/'config.json';listen=socket.socket();listen.bind(('127.0.0.1',0));local=listen.getsockname()[1];listen.close()
            cfg.write_text(json.dumps(dict(context=dict(lan=dict(address='127.0.0.1'),listen_port=local,port=port),settings=dict(cname=True,devices=[]),rules={'ads.example':True},allowed=[])))
            p=subprocess.Popen(UCODE+[str(ROOT/'scripts/dns_relay_fixture.uc'),str(cfg)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            self.addCleanup(lambda:p.poll() is None and p.kill())
            time.sleep(.15)
            if p.poll() is not None:self.fail(p.communicate())
            u=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);u.settimeout(2)
            with u:
                u.sendto(query(),('127.0.0.1',local));r,_=u.recvfrom(65535);self.assertEqual(struct.unpack('!H',r[6:8])[0],0)
            with socket.create_connection(('127.0.0.1',local),2) as c:
                q=query();c.sendall((struct.pack('!H',len(q))+q)*2)
                for _ in range(2):
                    h=c.recv(2);self.assertEqual(len(h),2);size=struct.unpack('!H',h)[0];r=b''
                    while len(r)<size:r+=c.recv(size-len(r))
                    self.assertEqual(struct.unpack('!H',r[6:8])[0],0)
            p.terminate();out,err=p.communicate(timeout=5)
            self.assertNotIn('Reference error',err);self.assertNotIn('Type error',err)

    def tcp_case(self, requests=2, persistent=True, half_close=False, bad_id=False, hot_change=False):
        upstream=socket.socket();upstream.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        upstream.bind(('127.0.0.1',0));upstream.listen();upstream.settimeout(.1)
        self.addCleanup(upstream.close)
        stopped=threading.Event();self.addCleanup(stopped.set)
        accepted=[];seen=[]
        def read(c,size):
            raw=b''
            while len(raw)<size:
                chunk=c.recv(size-len(raw))
                if not chunk:return None
                raw+=chunk
            return raw
        def worker(c):
            with c:
                c.settimeout(2)
                try:
                    while not stopped.is_set():
                        h=read(c,2)
                        if h is None:return
                        q=read(c,struct.unpack('!H',h)[0])
                        if q is None:return
                        seen.append(q)
                        raw=answer(q,[('shop.example','normal.example')])
                        if bad_id:raw=bytes([raw[0]^1])+raw[1:]
                        frame=struct.pack('!H',len(raw))+raw
                        c.sendall(frame[:1]);c.sendall(frame[1:])
                        if not persistent:return
                except (OSError,struct.error):return
        def serve():
            while not stopped.is_set():
                try:
                    c,_=upstream.accept();accepted.append(c)
                    threading.Thread(target=worker,args=(c,),daemon=True).start()
                except (socket.timeout,OSError):pass
        thread=threading.Thread(target=serve,daemon=True);thread.start()
        with tempfile.TemporaryDirectory() as d:
            reserve=socket.socket();reserve.bind(('127.0.0.1',0));local=reserve.getsockname()[1];reserve.close()
            cfg=Path(d)/'config.json'
            cfg.write_text(json.dumps(dict(context=dict(lan=dict(address='127.0.0.1'),listen_port=local,port=upstream.getsockname()[1]),settings=dict(cname=True,devices=[]),rules={},allowed=[])))
            p=subprocess.Popen(UCODE+[str(ROOT/'scripts/dns_relay_fixture.uc'),str(cfg)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                for _ in range(40):
                    try:c=socket.create_connection(('127.0.0.1',local),.1);break
                    except OSError:
                        if p.poll() is not None:self.fail(p.communicate())
                        time.sleep(.025)
                else:self.fail('relay listener did not start')
                with c:
                    c.settimeout(2)
                    for n in range(requests):
                        q=query();q=struct.pack('!H',123+n)+q[2:]
                        c.sendall(struct.pack('!H',len(q))+q)
                        if half_close:c.shutdown(socket.SHUT_WR)
                        header=read(c,2);self.assertIsNotNone(header,'half-close must still deliver the pending DNS response')
                        raw=read(c,struct.unpack('!H',header)[0]);self.assertIsNotNone(raw)
                        self.assertEqual(raw[:2],q[:2])
                        self.assertEqual(raw[3]&15,2 if bad_id else 0)
                        self.assertEqual(struct.unpack('!H',raw[6:8])[0],0 if bad_id else 1)
                        if hot_change and n==0:
                            settings=json.loads(cfg.read_text());settings['rules']={'unused.example':True};cfg.write_text(json.dumps(settings))
                            until=time.monotonic()+2
                            while not cfg.with_name(cfg.name+'.applied').exists() and time.monotonic()<until:time.sleep(.01)
                            self.assertTrue(cfg.with_name(cfg.name+'.applied').exists(),'native rule update was not observed')
            finally:
                p.terminate();p.communicate(timeout=5)
        return len(accepted),len(seen)

    def test_persistent_tcp_client_reuses_one_native_connection(self):
        self.assertEqual(self.tcp_case(requests=12),(1,12))

    def test_client_half_close_keeps_pending_response(self):
        self.assertEqual(self.tcp_case(requests=1,half_close=True),(1,1))

    def test_short_lived_native_dns_reconnects_without_losing_answers(self):
        self.assertEqual(self.tcp_case(requests=5,persistent=False),(5,5))

    def test_wrong_transaction_id_is_servfail_without_replaying_query(self):
        self.assertEqual(self.tcp_case(requests=1,bad_id=True),(1,1))

    def test_native_rule_generation_retires_reused_tcp_stream(self):
        self.assertEqual(self.tcp_case(requests=3,hot_change=True),(2,3))

    def test_continuous_tcp_queries_periodically_retire_native_stream(self):
        self.assertEqual(self.tcp_case(requests=40),(2,40))
