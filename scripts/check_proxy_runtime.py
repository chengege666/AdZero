#!/usr/bin/env python3
"""Exercise core-only detection with real OpenWrt ubus sessions in a chroot.

The CGI is a controlled response fixture; no real router/proxy is contacted.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time

from check_openwrt_runtime import ROOT, SHA256


def main():
    archive=ROOT/'artifacts/runtime/openwrt-24.10.8-x86-64-rootfs.tar.gz'
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==SHA256
    with tempfile.TemporaryDirectory(prefix='adzero-proxy-') as tmp:
        base=Path(tmp)
        with tarfile.open(archive) as tar:tar.extractall(base,filter='fully_trusted')
        for name in ('tmp','dev','var/run/ubus','usr/libexec/adzero','usr/libexec/daed'):(base/name).mkdir(parents=True,exist_ok=True)
        os.mknod(base/'dev/null',0o666|0o20000,os.makedev(1,3))
        os.mknod(base/'dev/urandom',0o666|0o20000,os.makedev(1,9))
        (base/'var/run/ubus/ubus.sock').symlink_to('/tmp/ubus.sock')
        shutil.copyfile(ROOT/'luci-app-adzero/root/usr/libexec/adzero/proxy-state.uc',base/'usr/libexec/adzero/proxy-state.uc')
        (base/'usr/libexec/adzero/probe-test.uc').write_text("import * as p from './proxy-state.uc'; print(sprintf('%J\\n',{running:p.nailink('')}));\n")
        gateway=base/'usr/libexec/daed/luci-proxy'
        gateway.write_text('''#!/bin/sh
set -eu
[ "$REQUEST_METHOD" = POST ] && [ "$PATH_INFO" = /graphql ]
[ "$HTTP_ORIGIN" = http://localhost ]
session=${HTTP_COOKIE#daed_luci_session=}
umask 077
printf '%s' "$session" > /tmp/last-session
access=$(ubus call session access "{\\"ubus_rpc_session\\":\\"$session\\",\\"scope\\":\\"access-group\\",\\"object\\":\\"luci-app-daed-router\\",\\"function\\":\\"write\\"}" | jsonfilter -e '@.access')
[ "$access" = true ]
body=$(cat)
[ "$body" = '{"query":"{general{dae{running}}}"}' ]
case "$(cat /tmp/scenario)" in
 true|false) printf 'Status: 200 OK\\r\\nContent-Type: application/json\\r\\n\\r\\n{"data":{"general":{"dae":{"running":%s}}}}' "$(cat /tmp/scenario)";;
 denied) printf 'Status: 403 Forbidden\\r\\n\\r\\nPRIVATE-RESPONSE';;
 errors) printf 'Status: 200 OK\\r\\n\\r\\n{"errors":[{"message":"PRIVATE-RESPONSE"}],"data":null}';;
 invalid) printf 'Status: 200 OK\\r\\n\\r\\n{"data":{"general":{"dae":{"running":"false"}}}}';;
 slow) exec sleep 4;;
 *) printf 'invalid PRIVATE-RESPONSE';;
esac
''')
        gateway.chmod(0o755)
        child={k:v for k,v in os.environ.items() if not k.startswith('ADZERO_')}
        def run(*args):return subprocess.run(['chroot',tmp,*args],env=child,text=True,capture_output=True,timeout=8)
        procs=[]
        try:
            for command in (['/sbin/ubusd','-s','/tmp/ubus.sock'],['/sbin/rpcd','-s','/tmp/ubus.sock']):
                procs.append(subprocess.Popen(['chroot',tmp,*command],env=child,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
                time.sleep(.2)
            rows=[]
            for scenario,expected in [('true',True),('false',False),('denied',None),('errors',None),('invalid',None),('broken',None),('slow',None)]:
                (base/'tmp/scenario').write_text(scenario)
                started=time.monotonic();result=run('/usr/bin/ucode','/usr/libexec/adzero/probe-test.uc');elapsed=time.monotonic()-started
                assert result.returncode==0,result.stderr
                assert json.loads(result.stdout)=={'running':expected},(scenario,result.stdout,result.stderr)
                assert 'PRIVATE' not in result.stdout+result.stderr
                assert not list((base/'tmp').glob('adzero-proxy-*'))
                sid=(base/'tmp/last-session').read_text()
                access=run('/bin/ubus','call','session','access',json.dumps({'ubus_rpc_session':sid,'scope':'access-group','object':'luci-app-daed-router','function':'write'}))
                assert access.returncode!=0 or json.loads(access.stdout).get('access') is False
                assert elapsed<2.5,(scenario,elapsed)
                rows.append({'scenario':scenario,'running':expected,'seconds':round(elapsed,3),'session_destroyed':True,'temporary_files_removed':True})
            output={'runtime':'real OpenWrt ucode/ubus/rpcd; controlled CGI responses','checks':len(rows),'cases':rows,'device_acceptance':'not_run'}
            (ROOT/'artifacts/runtime/proxy-result.json').write_text(json.dumps(output,indent=2)+'\n')
            print(json.dumps(output,indent=2))
        finally:
            for proc in reversed(procs):proc.terminate();proc.wait(timeout=5)


if __name__=='__main__':main()
