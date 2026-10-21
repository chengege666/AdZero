#!/usr/bin/env python3
"""Verify pinned domestic data with production HTTPS downloader and parser."""
from pathlib import Path
import json,os,shlex,subprocess,tempfile,time
from build_sdk import source_hash
root=Path(__file__).resolve().parents[1];r=root/'.sdk/runtime-24.10.8'
ucode=shlex.join([str(r/'libc.so'),'--library-path',str(r),str(r/'ucode'),'-L',str(r)])
with tempfile.TemporaryDirectory(prefix='adzero-routing-data-') as tmp:
    env={**os.environ,'ADZERO_UCODE':ucode,'ADZERO_ADAPTER_ROOT':tmp}
    start=time.monotonic()
    p=subprocess.run(['/bin/sh',str(root/'luci-app-adzero/root/usr/libexec/adzero/routing-data'),'prepare'],env=env,text=True,capture_output=True,timeout=190)
    assert p.returncode==0,p.stderr
    data=json.loads(p.stdout)
    report={'status':'passed','source_sha256':source_hash(root/'luci-app-adzero'),'sources':data['sources'],'domains':len(data['domains']),'cidrs':len(data['cidrs']),'ipv6_cidrs':sum(':' in x for x in data['cidrs']),'elapsed_seconds':round(time.monotonic()-start,3),'scope':'real HTTPS download and production ucode validation in temporary cache; no router configuration'}
    (root/'artifacts/runtime/routing-data-result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
