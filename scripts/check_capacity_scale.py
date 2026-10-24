#!/usr/bin/env python3
"""Bounded native rule parsing and real Mihomo scale check; loopback only.

Defaults to 1M final / 500k source records in CI. Use --domains 4000000
--source-domains 2000000 to exercise the large-memory profile's upper bounds.
Measurements describe this Linux host, never router throughput or latency.
"""
import argparse,gzip,hashlib,json,os,shlex,socket,struct,subprocess,tempfile,threading,time,urllib.request
from pathlib import Path
from build_sdk import source_hash
from check_dns_core import VERSION,SHA256,URL,query,transform
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--domains',type=int,default=1000000);p.add_argument('--source-domains',type=int,default=500000)
    p.add_argument('--output',type=Path,default=ROOT/'artifacts/runtime/capacity-scale.json');a=p.parse_args()
    if not 1<=a.domains<=4000000 or not 1<=a.source_domains<=2000000:raise SystemExit('outside tested capacity profile')
    archive=ROOT/'artifacts/upstream'/f'mihomo-linux-amd64-compatible-{VERSION}.gz';archive.parent.mkdir(parents=True,exist_ok=True)
    if not archive.exists():
        with urllib.request.urlopen(URL,timeout=60) as r:archive.write_bytes(r.read(40*1024*1024))
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=SHA256:raise SystemExit('Mihomo checksum mismatch')
    binary=Path.home()/'.cache/adzero/mihomo'/VERSION/'mihomo';binary.parent.mkdir(parents=True,exist_ok=True);binary.write_bytes(gzip.decompress(archive.read_bytes()));binary.chmod(0o755)
    rows=[]
    with tempfile.TemporaryDirectory(prefix='adzero-capacity-') as tmp:
        home=Path(tmp);(home/'proc').mkdir();(home/'proc/meminfo').write_text('MemTotal: 3962420 kB\n')
        env={**os.environ,'ADZERO_ADAPTER_ROOT':tmp,'ADZERO_SOURCES_ROOT':tmp}
        lib=ROOT/'luci-app-adzero/root/usr/libexec/adzero'
        script=home/'parse.uc';script.write_text("import * as fs from 'fs';import * as lib from '"+str(lib/'adapter-lib.uc')+"';import * as source from '"+str(lib/'source-lib.uc')+"';let mode=ARGV[0],raw=fs.readfile(ARGV[1]);let values=mode=='source'?source.parse(raw,'domains'):lib.domains(raw,'dnsmasq.servers');print(sprintf('%J',{count:length(values)}));")
        for mode,count in [('source',a.source_domains),('output',a.domains)]:
            data=home/'rules.txt'
            with data.open('w') as f:
                for n in range(0,count,10000):f.write(''.join((f'a{i}.example\n' if mode=='source' else f'server=/a{i}.example/\n') for i in range(n,min(count,n+10000))))
            start=time.monotonic();result=subprocess.run(['/usr/bin/time','-f','%M','-o',str(home/'rss')]+shlex.split(os.environ['ADZERO_UCODE'])+[str(script),mode,str(data)],env=env,capture_output=True,text=True,timeout=300)
            assert result.returncode==0,result.stderr
            assert json.loads(result.stdout)['count']==count
            rows.append(dict(mode=mode,count=count,bytes=data.stat().st_size,seconds=round(time.monotonic()-start,3),max_rss_kib=int((home/'rss').read_text().strip())))
        provider=home/'adzero.txt'
        with provider.open('w') as f:
            for n in range(0,a.domains,10000):f.write(''.join(f'+.a{i}.example\n' for i in range(n,min(a.domains,n+10000))))
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as up:
            up.bind(('127.0.0.1',0));up.settimeout(.2);stop=threading.Event()
            def answer():
                while not stop.is_set():
                    try:raw,peer=up.recvfrom(4096)
                    except socket.timeout:continue
                    kind=struct.unpack('!H',raw[-4:-2])[0];ip=socket.inet_pton(socket.AF_INET6 if kind==28 else socket.AF_INET,'2001:db8::9' if kind==28 else '192.0.2.9')
                    up.sendto(raw[:2]+struct.pack('!HHHHH',0x8180,1,1,0,0)+raw[12:]+b'\xc0\x0c'+struct.pack('!HHIH',kind,1,60,len(ip))+ip,peer)
            thread=threading.Thread(target=answer,daemon=True);thread.start()
            with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
            cfg={'mode':'rule','log-level':'error','dns':{'enable':True,'listen':f'127.0.0.1:{port}','ipv6':True,'enhanced-mode':'redir-host','nameserver':[f'udp://127.0.0.1:{up.getsockname()[1]}'],'default-nameserver':['127.0.0.1']},'rules':['MATCH,DIRECT']}
            config=home/'config.json';config.write_text(json.dumps(transform('mihomo',cfg,str(provider),False)))
            with (home/'core.log').open('w+') as log:
                process=subprocess.Popen([str(binary),'-d',tmp,'-f',str(config)],stdout=log,stderr=log);start=time.monotonic()
                try:
                    for _ in range(600):
                        try:
                            # Listener readiness precedes asynchronous provider
                            # loading; require a rule hit before acceptance.
                            # A positive answer cached during startup cannot
                            # stand in for the now-loaded provider's behavior.
                            blocked=query(port,f'probe{_}.a0.example');normal=query(port,'normal.invalid')
                            if blocked==(3,0) and normal==(0,1):break
                        except OSError:pass
                        if process.poll() is not None:raise AssertionError((home/'core.log').read_text())
                        time.sleep(.1)
                    else:raise AssertionError('core provider readiness deadline: '+(home/'core.log').read_text())
                    checked=0
                    for tcp in (False,True):
                        for kind in (1,28):
                            for i in (0,a.domains//2,a.domains-1):
                                result=query(port,f'sub.a{i}.example',kind,tcp);assert result==(3,0),(i,kind,tcp,result,(home/'core.log').read_text());checked+=1
                            assert query(port,'normal.invalid',kind,tcp)==(0,1);checked+=1
                    rss=next(line.split()[1] for line in Path(f'/proc/{process.pid}/status').read_text().splitlines() if line.startswith('VmHWM:'))
                    rows.append(dict(mode='mihomo',count=a.domains,queries=checked,seconds=round(time.monotonic()-start,3),max_rss_kib=int(rss)))
                finally:process.terminate();process.wait(timeout=10);stop.set();thread.join(2)
    report=dict(source_sha256=source_hash(ROOT/'luci-app-adzero'),core=VERSION,measurements=rows,scope='native ucode and real Mihomo, synthetic domains, loopback only; not router performance')
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
if __name__=='__main__':main()
