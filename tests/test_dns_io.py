"""TCP DNS probe uses SOCKS CONNECT with numeric endpoints and bounded IO."""
import base64,json,os,shlex,socket,struct,subprocess,threading,unittest
from pathlib import Path
from test_dns_enhance import query,answer
ROOT=Path(__file__).resolve().parents[1];UCODE=shlex.split(os.environ.get('ADZERO_UCODE',''))
@unittest.skipUnless(UCODE,'requires actual ucode/socket')
class IOTest(unittest.TestCase):
 def test_numeric_socks_connect_and_short_tcp_reads(self):
  listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();listener.settimeout(4);self.addCleanup(listener.close)
  received=[]
  def serve():
   with listener.accept()[0] as c:
    def read(n):
     b=b''
     while len(b)<n:b+=c.recv(n-len(b))
     return b
    received.append(read(3));c.sendall(b'\x05\x00');head=read(4);received.append(head+read(6));c.sendall(b'\x05\x00\x00\x01\x7f\0\0\x01\0\x35')
    size=struct.unpack('!H',read(2))[0];q=read(size);r=answer(q,[]);frame=struct.pack('!H',len(r))+r
    for part in (frame[:1],frame[1:3],frame[3:]):c.sendall(part)
  t=threading.Thread(target=serve,daemon=True);t.start()
  p=dict(address='1.1.1.1',port=53,query=base64.b64encode(query()).decode(),tcp=True,proxy_port=listener.getsockname()[1])
  r=subprocess.run(UCODE+[str(ROOT/'scripts/dns_io_fixture.uc')],input=json.dumps(p),text=True,capture_output=True,timeout=5)
  self.assertEqual(r.returncode,0,r.stderr);self.assertIsNotNone(json.loads(r.stdout),r.stderr)
  self.assertEqual(received,[b'\x05\x01\x00',b'\x05\x01\x00\x01\x01\x01\x01\x01\0\x35'])
  t.join(2);self.assertFalse(t.is_alive())
