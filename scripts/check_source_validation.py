#!/usr/bin/env python3
"""Compare a saved domain list with production and pinned native parsers.

No UCI, services or network. Uses OpenWrt BusyBox when configured via PATH.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
from build_sdk import source_hash

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_SHA256 = '19727b189472f380b9791b1fc37c4acdec60eea06650f7d845fea8fafbd49315'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--format', choices=('domains','hosts','adblock'), default='domains')
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/runtime/source-validation-result.json')
    args = parser.parse_args()
    before = source_hash(ROOT/'luci-app-adzero')
    ucode = shlex.split(os.environ.get('ADZERO_UCODE', ''))
    if not ucode: raise SystemExit('Set ADZERO_UCODE to actual OpenWrt ucode/fs modules')
    raw = args.input.read_bytes()
    assert 0 < len(raw) <= 25000000
    native = ROOT/'artifacts/upstream/adblock-fast-1.2.4-r4.uc'
    assert hashlib.sha256(native.read_bytes()).hexdigest() == UPSTREAM_SHA256
    table = native.read_text()
    table = table[table.index('const list_formats = {'):table.index('const sym = {')]
    def run(code):
        return subprocess.run(ucode+['-e', code], check=True, text=True,
                              capture_output=True, timeout=90).stdout
    with tempfile.TemporaryDirectory(prefix='adzero-source-validation-') as tmp:
        output = Path(tmp)/'native.txt'
        kind='adblockplus' if args.format=='adblock' else args.format
        expression = run(table+'print(list_formats['+json.dumps(kind)+'].filter);')
        source=args.input.resolve()
        if args.format=='hosts':
            source=Path(tmp)/'hosts.txt'
            source.write_bytes(subprocess.run(['sed','/# Title: StevenBlack/,/# Custom host records are listed here/d',str(args.input.resolve())],check=True,capture_output=True).stdout)
        filtered = subprocess.run(['sed', expression, str(source)],
                                  check=True, capture_output=True, timeout=30).stdout
        sorted_result = subprocess.run(['sort', '-u'], input=filtered,
                                       check=True, capture_output=True, timeout=30).stdout
        # Same ASCII restriction as the native process_downloads sort stage.
        ascii_result = subprocess.run(['grep','-E','-v','[^a-zA-Z0-9=/.-]'],
                                      input=sorted_result, check=True,
                                      capture_output=True, timeout=30).stdout
        output.write_bytes(ascii_result)
        library = str(ROOT/'luci-app-adzero/root/usr/libexec/adzero/source-lib.uc')
        actual = str(ROOT/'luci-app-adzero/root/usr/libexec/adzero/adapter-lib.uc')
        code = ("import * as lib from "+json.dumps(library)+";"
                "import {readfile} from 'fs';let result=lib.detect(readfile("
                +json.dumps(str(args.input.resolve()))+"));print(sprintf('%J',result));")
        started = time.monotonic();detected = json.loads(run(code));seconds = time.monotonic()-started
        backend = json.loads(run("import {domains} from "+json.dumps(actual)
            +";import {readfile} from 'fs';print(sprintf('%J',domains(readfile("
            +json.dumps(str(output))+"),'smartdns.domainset')));"))
        assert detected and detected['format'] == args.format
        # Native hosts sed can concatenate the broadcast system mapping into
        # a fake domain. Do not add that artifact to the source's valid count.
        # This sole exception is tied to the exact header in the input; all
        # other missing/additional domains still fail the comparison.
        artifacts=[]
        header='255.255.255.255broadcasthost'
        if args.format=='hosts' and header in backend and header not in detected['names'] and re.search(rb'^\s*255\.255\.255\.255\s+broadcasthost\s*(?:#.*)?$',raw,re.M):artifacts=[header]
        usable=[name for name in backend if name not in artifacts]
        assert detected['names'] == usable, ('Independent/native domain sets differ',
            sorted(set(detected['names'])-set(usable))[:5],sorted(set(usable)-set(detected['names']))[:5])
        assert source_hash(ROOT/'luci-app-adzero') == before, 'Source changed during validation'
        report = {'source_sha256':before,
                  'body_sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),
                  'format':detected['format'],'valid_unique_domains':len(usable),'native_domain_count':len(backend),
                  'excluded_records':detected['skipped'],'native_upstream_sha256':UPSTREAM_SHA256,
                  'same_sorted_domain_set':detected['names']==backend,'native_header_artifacts':artifacts,
                  'valid_source_domain_sets_match':True,'parse_seconds_x86_userspace':round(seconds,3),
                  'network_services_proxy_router':'not_run'}
        path=args.output;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__': main()
