#!/usr/bin/env python3
"""Download the curated catalog over HTTPS and run actual ucode validation.

Development/CI network only. Does not change UCI or start router services.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import urllib.request
from build_sdk import ROOT, PACKAGE, source_hash


def transform(data):
    command=shlex.split(os.environ['ADZERO_UCODE'])+[str(ROOT/'scripts/source_transform.uc')]
    result=subprocess.run(command,input=json.dumps(data),text=True,capture_output=True,timeout=90)
    if result.returncode: raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def main():
    rows=[]
    for item in transform({'action':'catalog'}):
        print('Checking '+item['id'],flush=True)
        with urllib.request.urlopen(item['url'],timeout=45) as response:
            assert response.geturl().startswith('https://')
            raw=response.read(25000001)
        parsed=transform({'action':'parse','raw':raw.decode('utf-8-sig'),'format':item['format']})
        assert len(parsed)>1000,item['id']
        rows.append({'id':item['id'],'url':item['url'],'format':item['format'],'bytes':len(raw),'domains':len(parsed),'sha256':hashlib.sha256(raw).hexdigest()})
    result={'source_sha256':source_hash(PACKAGE),'checked_at':datetime.now(timezone.utc).isoformat(),'lists':rows,'validation':'all catalog downloads accepted by the production parser','scope':'development HTTPS and real ucode only; no router or DNS lifecycle'}
    (ROOT/'artifacts/runtime/source-catalog-result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
