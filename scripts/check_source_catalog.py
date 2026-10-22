#!/usr/bin/env python3
"""Download the curated catalog over HTTPS and run actual ucode validation.

Development/CI network only. Does not change UCI or start router services.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
import urllib.request
from build_sdk import ROOT, PACKAGE, source_hash


def transform(data):
    command=shlex.split(os.environ['ADZERO_UCODE'])+[str(ROOT/'scripts/source_transform.uc')]
    result=subprocess.run(command,input=json.dumps(data),text=True,capture_output=True,timeout=90)
    if result.returncode: raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory',type=Path,help='Previously downloaded public source inventory; inspect local bodies without network')
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/runtime/source-catalog-result.json')
    args=parser.parse_args();before=source_hash(PACKAGE)
    rows=[]
    items=json.loads(args.inventory.read_text()) if args.inventory else transform({'action':'catalog'})
    for item in items:
        print('Checking '+item.get('id',item.get('name','source')),flush=True)
        started=time.monotonic()
        if args.inventory:
            raw=(ROOT/item['path']).read_bytes()
            assert hashlib.sha256(raw).hexdigest()==item['body_sha256']
        else:
            with urllib.request.urlopen(item['url'],timeout=45) as response:
                assert response.geturl().startswith('https://')
                raw=response.read(25000001)
        parsed=transform({'action':'inspect','raw':raw.decode('utf-8-sig'),'format':item['format']})
        if not args.inventory:assert parsed['domains']>1000,item['id']
        rows.append({'id':item.get('id'),'name':item.get('name'),'url':item['url'],**parsed,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'seconds':round(time.monotonic()-started,3)})
    assert source_hash(PACKAGE)==before,'Source changed during catalog audit'
    result={'source_sha256':before,'checked_at':datetime.now(timezone.utc).isoformat(),'lists':rows,'validated':sum(r['validation']=='validated' for r in rows),'backend_only':sum(r['validation']=='backend_only' for r in rows),'scope':'saved HTTPS bodies and real ucode; no router or DNS lifecycle' if args.inventory else 'development HTTPS and real ucode only; no router or DNS lifecycle'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
