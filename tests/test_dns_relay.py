"""Native ucode sockets against isolated loopback UDP/TCP DNS fixtures."""
import json,os,shlex,socket,struct,subprocess,tempfile,threading,time,unittest
from pathlib import Path
from test_dns_enhance import query,answer
ROOT=Path(__file__).resolve().parents[1]
UCODE=shlex.split(os.environ.get('ADZERO_UCODE',''))
@unittest.skipUnless(UCODE,'requires actual ucode/socket')
class RelayTest(unittest.TestCase):
    def test_udp_tcp_cname_device_exemption_and_pipeline(self):
        udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);udp.bind(('127.0.0.1',0));port=udp.getsockname()[1]
        tcp=socket.socket();tcp.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);tcp.bind(('127.0.0.1',port));tcp.listen();tcp.settimeout(.1);udp.settimeout(.1)
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
