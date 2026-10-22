#!/usr/bin/env python3
"""Validate production ad plus DNS/traffic syntax with checksum-pinned dae."""
from pathlib import Path
import base64,hashlib,json,os,shlex,subprocess,tarfile,tempfile
from check_dae import URL,SHA256
from build_sdk import source_hash
root=Path(__file__).resolve().parents[1];r=root/'.sdk/runtime-24.10.8'
ucode=[str(r/'libc.so'),'--library-path',str(r),str(r/'ucode'),'-L',str(r)]
def transform(operation,*args,ad=False):
    p=subprocess.run(ucode+[str(root/('scripts/adapter_transform.uc' if ad else 'scripts/routing_transform.uc'))],input=json.dumps({'operation':operation,'arguments':args}),text=True,capture_output=True)
    assert p.returncode==0,p.stderr
    return json.loads(p.stdout)
archive=root/'artifacts/upstream/dae-v2.1.1.tar.xz'
if hashlib.sha256(archive.read_bytes()).hexdigest()!=SHA256:raise SystemExit('dae archive checksum mismatch')
binary=Path.home()/'.cache/adzero/dae-routing-check/dae';binary.parent.mkdir(parents=True,exist_ok=True)
with tarfile.open(archive) as tar:
    members=[m for m in tar.getmembers() if m.isfile() and m.name.endswith('/bin/dae')]
    if len(members)!=1:raise SystemExit('Unexpected dae archive')
    binary.write_bytes(tar.extractfile(members[0]).read());binary.chmod(0o755)
with tempfile.TemporaryDirectory(prefix='adzero-routing-dae-') as tmp:
    home=Path(tmp)
    (home/'adzero-geosite.dat').write_bytes(base64.b64decode(transform('geosite',['ads.example'],ad=True)))
    (home/'adzero-cn-geosite.dat').write_bytes(base64.b64decode(transform('geosite',['cn.example'],ad=True)))
    (home/'adzero-cn-geoip.dat').write_bytes(base64.b64decode(transform('geoip',['223.5.5.0/24','2400:3200::/32'])))
    profiles=[None,{'domestic':{'servers':['119.29.29.29'],'active':'119.29.29.29'},'foreign':{'servers':['8.8.8.8'],'active':'8.8.8.8'}},{'domestic':{'servers':['2400:3200::1'],'active':'2400:3200::1'},'foreign':{'servers':['2606:4700:4700::1111'],'active':'2606:4700:4700::1111'}}]
    for profile in profiles:
        for response in (True,False):
            dns='upstream { original: "udp://223.5.5.5:53" }\nrouting { request { fallback: original }'+(' response { fallback: accept }' if response else '')+' }'
            dns=transform('dae_dns',transform('dae_dns',dns,ad=True),profile)
            routing=transform('dae_routing','domain(full: keep.example) -> direct\nfallback: proxy\n','proxy',profile)
            config=home/'config.dae';config.write_text('global { log_level: info }\nnode { mynode: "socks5://127.0.0.1:9" }\ngroup { proxy { filter: name(mynode)\npolicy: fixed(0) } }\ndns { '+dns+' }\nrouting { '+routing+' }\n');config.chmod(0o600)
            p=subprocess.run([str(binary),'validate','-c',str(config)],text=True,capture_output=True)
            assert p.returncode==0,p.stdout+p.stderr
    report={'status':'passed','source_sha256':source_hash(root/'luci-app-adzero'),'asset_sha256':SHA256,'core':'dae v2.1.1','profiles':['default','custom_ipv4','custom_ipv6'],'response_shapes':['explicit_response','request_only'],'configurations':6,'scope':'real DNS/traffic config parser and v4/v6 GeoIP DAT; no eBPF, router or LAN execution'}
    (root/'artifacts/runtime/routing-dae-result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
