#!/usr/bin/env python3
"""Profile production ctl with large data and isolated service/API fixtures.

Uses real UCI, ucode and shell. No router, network service or external fetch.
--libexec allows an explicitly extracted old version to be compared locally.
"""
import argparse, json, os, shlex, subprocess, sys, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
native=ROOT/'.sdk/runtime-24.10.8'
os.environ.setdefault('ADZERO_UCODE',shlex.join([str(native/'libc.so'),'--library-path',str(native),str(native/'ucode'),'-L',str(native)]))
os.environ.setdefault('ADZERO_TEST_SHELL',shlex.join([str(native/'libc.so'),'--library-path',str(native),str(native/'busybox'),'ash']))
os.environ['PATH']=str(native/'wrappers')+os.pathsep+os.environ['PATH']
sys.path.insert(0,str(ROOT/'tests'))
import test_controls as controls
from test_routing import RoutingAdapterTest
from build_sdk import source_hash

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--libexec',type=Path,default=controls.LIBEXEC)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/runtime/large-rules-result.json')
    args=parser.parse_args();controls.LIBEXEC=args.libexec.resolve()
    f=controls.ControlsTest();f.setUp()
    try:
        p=RoutingAdapterTest.nailink_fixture(f)
        names=[f'ad{i:06d}.example' for i in range(206372)]
        bodies={'https://bench.example/large':names,'https://bench.example/extra':['extra-ad.example','extra-track.example']}
        f.write('source-downloads.json',json.dumps(bodies))
        cfg=f.root/'etc/config/adblock-fast'
        cfg.write_text(cfg.read_text()+"\nconfig file_url 'large'\n option enabled '1'\n option action 'block'\n option adzero_format 'domains'\n option url 'https://bench.example/large'\nconfig file_url 'extra'\n option enabled '0'\n option action 'block'\n option adzero_format 'domains'\n option url 'https://bench.example/extra'\n")
        for key,names in bodies.items():f.write('body-'+('large' if key.endswith('/large') else 'extra'),'\n'.join(names)+'\n')
        fetch=f.write('bin/fetch','#!/bin/sh\necho "$1" >> "$ADZERO_SOURCES_ROOT/fetches"\ncase "$1" in */large) cp "$ADZERO_SOURCES_ROOT/body-large" "$2";; *) cp "$ADZERO_SOURCES_ROOT/body-extra" "$2";; esac\n',True)
        data=f.write('country.json',json.dumps({'domain_raw':''.join(f'server=/cn{i:06d}.example.cn/114.114.114.114\n' for i in range(109795)),
                                             'cidr_raw':''.join(f'10.{i//256}.{i%256}.0/24\n' for i in range(10015))}))
        f.env.update(ADZERO_SOURCE_FETCH_FIXTURE=str(fetch),ADZERO_ROUTING_DATA_FIXTURE=str(data),ADZERO_ROUTING_DATA_PROGRAM=str(args.libexec/'routing-data'))
        results=[]
        actions=[('enable',['enable']),('unchanged_reconcile',['reconcile']),('routing_on_cold',['routing-on']),('routing_off',['routing-off']),('routing_on_warm',['routing-on']),('lookup',['lookup','ad000123.example']),('enable_extra_source',['source-toggle','extra','https://bench.example/extra','1'])]
        for label,argv in actions:
            context=f.root/'tmp'/('job-'+label);context.mkdir(parents=True)
            f.env['ADZERO_JOB_CONTEXT']=str(context)
            before=json.loads(p.read_text())['runs'];started=time.monotonic()
            proc=subprocess.run(controls.SHELL+[str(args.libexec/'ctl'),*argv],env=f.env,text=True,capture_output=True,timeout=180)
            assert proc.returncode==0,proc.stderr
            after=json.loads(p.read_text())['runs']
            row={'action':label,'seconds':round(time.monotonic()-started,4),'proxy_reload_calls':after-before}
            if (context/'timeline').exists():row['timeline']=(context/'timeline').read_text().splitlines()
            if label=='lookup':assert json.loads(proc.stdout)['match']=='exact'
            if label=='unchanged_reconcile':assert after==before
            if label.startswith('routing_'):assert after-before==1
            results.append(row);print(json.dumps(row),flush=True)
        final=json.loads(f.ctl('status').stdout)
        assert final['state']=='configured_unverified' and final['backend']['domains']==206377,final
        report={'source_sha256':source_hash(ROOT/'luci-app-adzero') if args.libexec.resolve()==(ROOT/'luci-app-adzero/root/usr/libexec/adzero').resolve() else 'explicit_old_libexec',
                'rules':206375,'domestic_domains':109795,'domestic_cidrs':10015,'measurements':results,
                'precheck_downloads':len((f.root/'fetches').read_text().splitlines()),
                'scope':'real ctl/UCI/ucode; synthetic large rules; backend/download/NaiLink API/reload fixtures; not router or network timings'}
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report),flush=True)
    finally:f.doCleanups()

if __name__=='__main__':main()
