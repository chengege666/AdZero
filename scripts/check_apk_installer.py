#!/usr/bin/env python3
"""Run the installer with real apk-tools in disposable package databases.

Package contents and controller are fixtures, not router services. No system
database or repository file is modified. Supply the pinned SDK's host apk.
"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import shlex
import subprocess
import sys
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_installer import InstallerTest


def check(apk):
    apk=apk.resolve()
    def native(*args):
        result=subprocess.run([str(apk),*map(str,args)],text=True,capture_output=True,timeout=20)
        if result.returncode:raise AssertionError(result.stdout+result.stderr)
        return result
    version=native('--version').stdout.strip()
    requests=[]
    class BrokenRepository(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path);self.send_error(503)
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',0),BrokenRepository)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    cases=[]
    try:
        for mode in ('installed_dependencies','missing_dependency','version_mismatch'):
            fixture=InstallerTest();fixture.setUp()
            try:
                fixture.arm_apk(arch='x86_64')
                fixture.write('etc/openwrt_release',"DISTRIB_ID='OpenWrt'\nDISTRIB_RELEASE='25.12.5'\nDISTRIB_TARGET='x86/64'\nDISTRIB_ARCH='x86_64'\n")
                (fixture.root/'lib/apk/db/installed').unlink()
                def package(name,version,dependency=None):
                    path=fixture.base/(name+'-'+version+'.apk')
                    args=['mkpkg','--info','name:'+name,'--info','version:'+version,'--info','arch:noarch','--output',path]
                    if dependency:args+=['--info','depends:'+dependency]
                    native(*args);return path
                dep=package('adzero-test-dependency','1-r1')
                old=package('luci-app-adzero','0.14.3-r1')
                new=package('luci-app-adzero','0.15.1-r1','adzero-test-dependency>='+('2' if mode=='version_mismatch' else '1'))
                initial=['add','--root',fixture.root,'--initdb','--allow-untrusted','--no-network','--repositories-file','/dev/null',old]
                if mode!='missing_dependency':initial.append(dep)
                native(*initial)
                repos=fixture.root/'etc/apk/repositories.d';repos.mkdir(parents=True,exist_ok=True)
                (repos/'broken.list').write_text('http://127.0.0.1:'+str(server.server_port)+'/broken\n')
                sha=hashlib.sha256(new.read_bytes()).hexdigest()
                (fixture.release/'releases.tsv').write_text(sha+'\t'+new.name+'\topenwrt\t25.12.5\tx86/64\tx86_64\tapk\n')
                (fixture.release/new.name).write_bytes(new.read_bytes())
                journal=fixture.upgrade_fixture()
                fixture.executable(fixture.bin/'apk','''#!/bin/sh
if [ "$1" = --print-arch ]; then exec '''+shlex.quote(str(apk))+''' "$@"; fi
if [ "$1" = update ]; then echo 'apk update' >> "$MOCK_INSTALL_LOG"; exit 9; fi
simulate=0
for arg in "$@"; do [ "$arg" != --simulate ] || simulate=1; done
if [ "$simulate" = 1 ]; then echo 'apk check-local' >> "$MOCK_INSTALL_LOG"; else echo 'apk add-local' >> "$MOCK_INSTALL_LOG"; fi
exec '''+shlex.quote(str(apk))+''' --root "$ADZERO_INSTALL_ROOT" "$@"
''')
                installed=fixture.root/'lib/apk/db/installed';before=installed.read_bytes()
                result=fixture.run_installer('--upgrade',success=mode=='installed_dependencies')
                operations=fixture.log.read_text().splitlines()
                if mode=='installed_dependencies':
                    assert operations==['apk check-local','ctl disable','apk add-local','ctl enable'],operations
                    native('info','--root',fixture.root,'--exists','luci-app-adzero=0.15.1-r1')
                    assert not journal.exists()
                else:
                    assert operations==['apk check-local','apk update'],operations
                    assert installed.read_bytes()==before and journal.read_text()=='private-recovery-data'
                    assert '尚未关闭旧版保护' in result.stderr
                assert not (fixture.root/'tmp/adzero-install.lock').exists()
                cases.append({'case':mode,'operations':operations,'passed':True})
            finally:fixture.doCleanups()
    finally:server.shutdown();thread.join();server.server_close()
    assert requests==[],requests
    return {'apk':version,'apk_sha256':hashlib.sha256(apk.read_bytes()).hexdigest(),
            'installer_sha256':hashlib.sha256((ROOT/'scripts/install.sh').read_bytes()).hexdigest(),
            'checks':len(cases),'cases':cases,'repository_requests':len(requests),
            'scope':'real apk database/solver/package installation and delivered installer; synthetic packages and controller; no router service or host package changes'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    report=check(args.apk);raw=json.dumps(report,indent=2)+'\n'
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(raw,encoding='utf-8',newline='\n')
    print(raw,end='')
