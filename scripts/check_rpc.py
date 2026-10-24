#!/usr/bin/env python3
"""Actual rpcd/ubusd/ucode smoke in a disposable chroot; no router or TCP port.

Run with root inside WSL. Uses the checksum-pinned runtime archive and a ctl
fixture that itself calls rpcd, exercising asynchronous nested ubus handling.
"""
import hashlib
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid as uuidlib

from check_openwrt_runtime import ROOT, SHA256
from build_sdk import source_hash
from prepare_dns_socket import install as install_socket


def large_status_check(base, run, ctl):
    """Real ctl/ucode/UCI over rpcd, with 206375 rules and a large journal.

    Only procd's service inventory is a fixture. No adapter apply, filtering
    service, network restart, LAN traffic or router is involved.
    """
    libexec=ROOT/'luci-app-adzero/root/usr/libexec/adzero'
    for source in libexec.iterdir():
        if source.is_file():
            target=base/'usr/libexec/adzero'/source.name
            shutil.copyfile(source,target);target.chmod(0o755)
    # Environment injection is confined to this disposable chroot. The public
    # file.exec call still invokes the exact executable and args used by LuCI.
    ctl.rename(ctl.with_name('ctl.real'))
    ctl.write_text('''#!/bin/sh
export ADZERO_BACKEND_ROOT=/ ADZERO_BACKEND_SERVICE_FIXTURE=/tmp/services.json
export ADZERO_PROBE_ROOT=/ ADZERO_PROBE_SERVICE_FIXTURE=/tmp/services.json
exec /bin/sh /usr/libexec/adzero/ctl.real "$@"
''');ctl.chmod(0o755)
    (base/'etc/config/adzero').write_text("config adzero 'main'\n option enabled '1'\n")
    init=base/'etc/init.d/adblock-fast'
    init.write_text('#!/bin/sh\necho unexpected-service-operation >/tmp/service-was-called\nexit 77\n');init.chmod(0o755)
    (base/'etc/config/adblock-fast').write_text("config adblock-fast 'config'\n option enabled '1'\n option dns 'dnsmasq.servers'\n option force_dns '0'\n option download_allow_insecure '0'\n list blocked_domain 'ads.example'\n")
    output=base/'var/run/adblock-fast/dnsmasq.servers';output.parent.mkdir(parents=True,exist_ok=True)
    raw=''.join(f'server=/ad{i:06d}.example/\n' for i in range(206375))
    output.write_text(raw)
    state=base/'etc/adzero'
    for name,content in [('managed','1'),('force_dns.previous','1'),('download_allow_insecure.previous','1')]:
        (state/name).write_text(content+'\n')
    (state/'adapter.json').write_text(json.dumps({'schema':1,'plugin':'nailink','stage':'configured_unverified','count':206375,'flags':[],
        'files':[{'path':'/etc/daed/adzero-geosite.dat','kind':'owned','before':None,'after':base64.b64encode(raw.encode()).decode()}]}))
    services={'adblock-fast':{'data':{'status':'statusSuccess','errors':[],'warnings':[],'entries':206375,'dns':'dnsmasq.servers','force_dns_active':False,'outputFile':'/var/run/adblock-fast/dnsmasq.servers'}},'dnsmasq':{'instances':{'test':{'running':True}}}}
    fixture=base/'tmp/services.json';fixture.write_text(json.dumps(services))
    def read():
        start=time.monotonic()
        result=run('/bin/ubus','-s','/tmp/ubus.sock','call','file','exec',json.dumps({'command':'/usr/libexec/adzero/ctl','params':['status']}))
        elapsed=time.monotonic()-start
        assert result.returncode==0,result.stdout+result.stderr
        reply=json.loads(result.stdout);assert reply['code']==0,reply
        return json.loads(reply['stdout']),round(elapsed,4)
    before={str(p):p.read_bytes() for p in [output,state/'adapter.json',base/'etc/config/adzero',base/'etc/config/adblock-fast']}
    samples=[]
    for _ in range(3):
        value,elapsed=read();samples.append(elapsed)
        assert value['state']=='configured_unverified',value
        assert value['backend']['domains']==206375 and not value['backend']['rules_checked'],value
        assert value['adapter']['domains']==206375,value
    assert before=={p:Path(p).read_bytes() for p in before},'status changed configuration or rules'
    assert not (base/'tmp/adzero.lock').exists(),'read acquired a mutation lock'
    assert not (base/'tmp/service-was-called').exists(),'read invoked a network service'
    # Stale backend success cannot enable controls after output disappearance.
    output.unlink();value,_=read();assert value['state']=='inconsistent',value
    output.write_text(raw);services['dnsmasq']['instances']['test']['running']=False;fixture.write_text(json.dumps(services))
    value,_=read();assert value['state']=='inconsistent' and not value['backend']['resolver_running'],value
    return {'rules':206375,'rule_bytes':len(raw),'journal_bytes':(state/'adapter.json').stat().st_size,
            'rpcd_seconds':samples,'unchanged_files':True,'missing_output_and_stopped_resolver':'rejected',
            'scope':'actual ctl/UCI/ucode/file.exec; procd service data fixture; no network services'}


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run as root inside Linux/WSL (disposable chroot only)')
    archive = ROOT/'artifacts/runtime/openwrt-24.10.8-x86-64-rootfs.tar.gz'
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == SHA256
    with tempfile.TemporaryDirectory(prefix='adzero-rpc-') as tmp:
        # Development wrappers contain host paths and cannot be inherited by
        # rpcd inside the disposable router filesystem.
        child_env={key:value for key,value in os.environ.items() if key!='ADZERO_UCODE'}
        base = Path(tmp)
        with tarfile.open(archive) as tar:
            tar.extractall(base, filter='fully_trusted')  # verified official archive
        install_socket(ROOT,base)
        for path in ('var/run/ubus','tmp','dev','etc/adzero'):
            (base/path).mkdir(parents=True,exist_ok=True)
        os.mknod(base/'dev/null',0o666 | 0o20000,os.makedev(1,3))
        os.mknod(base/'dev/urandom',0o666 | 0o20000,os.makedev(1,9))
        (base/'var/run/ubus/ubus.sock').symlink_to('/tmp/ubus.sock')
        for relative in ('usr/share/rpcd/ucode/adzero','usr/libexec/adzero/observe-state.uc','usr/libexec/adzero/policy-lib.uc','usr/libexec/adzero/source-lib.uc','usr/libexec/adzero/routing-lib.uc','usr/libexec/adzero/progress-lib.uc','usr/libexec/adzero/job','usr/share/rpcd/acl.d/luci-app-adzero.json'):
            target=base/relative; target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/'luci-app-adzero/root'/relative,target)
            if relative.endswith('/job'): target.chmod(0o755)
        for name in ('observe','observe.uc','observe-lib.uc','rules-cache.uc','adapter-lib.uc','dns-enhance-lib.uc'):
            target=base/'usr/libexec/adzero'/name
            shutil.copyfile(ROOT/'luci-app-adzero/root/usr/libexec/adzero'/name,target);target.chmod(0o755)
        uuid=base/'proc/sys/kernel/random/uuid';uuid.parent.mkdir(parents=True,exist_ok=True)
        uuid.write_text('12345678-1234-1234-1234-123456789012\n')
        ctl=base/'usr/libexec/adzero/ctl'
        ctl.write_text('''#!/bin/sh
# A nested rpcd operation would deadlock with synchronous popen in the plugin.
ubus -s /tmp/ubus.sock call session create '{"timeout":2}' >/tmp/nested.json || exit 1
case "$1" in
 lookup) printf '{"available":true,"domain":"%s","match":"none"}\\n' "$2";;
pause) echo source_download > "$ADZERO_JOB_CONTEXT/reason"; exit 1;;
 enable|disable|refresh|reload|routing-on|routing-off)
   mkdir /tmp/long-operation.lock || exit 1
   trap 'rmdir /tmp/long-operation.lock' EXIT
   echo $$ > /tmp/long-operation.pid
   sleep 2
   echo 'private-backend-token-not-for-browser';;
 source-add) sleep 2;;
 settings-apply|controls-apply|enhance-save)
   [ -f "$2" ] || exit 1
   cat "$2" > /tmp/received-batch.json
   sleep 2;;
 sources-list) echo '{"catalog":[],"items":[],"pending":false}';;
 *) echo 'private-backend-token-not-for-browser';;
esac
'''); ctl.chmod(0o755)
        def run(*args): return subprocess.run(['chroot',tmp,*args],env=child_env,text=True,capture_output=True,timeout=12)
        procs=[]
        try:
            log=(ROOT/'artifacts/runtime/rpc-smoke.log').open('w+')
            procs.append(subprocess.Popen(['chroot',tmp,'/sbin/ubusd','-s','/tmp/ubus.sock'],env=child_env,stdout=log,stderr=log))
            time.sleep(.2)
            # Lower the real rpcd execution timer only in this disposable chroot.
            procs.append(subprocess.Popen(['chroot',tmp,'/sbin/rpcd','-s','/tmp/ubus.sock','-t','1'],env=child_env,stdout=log,stderr=log))
            for _ in range(30):
                r=run('/bin/ubus','-s','/tmp/ubus.sock','-v','list','adzero')
                if 'lookup' in r.stdout: break
                time.sleep(.1)
            log.flush()
            assert 'lookup' in r.stdout,r.stdout+r.stderr+(ROOT/'artifacts/runtime/rpc-smoke.log').read_text()
            def call(method,data):
                uuid.write_text(str(uuidlib.uuid4())+'\n')
                r=run('/bin/ubus','-s','/tmp/ubus.sock','-t','8','call','adzero',method,json.dumps(data))
                if r.returncode:
                    debug={str(p.relative_to(base)):p.read_text() for p in (base/'tmp/adzero-jobs').glob('*/result*')}
                    raise AssertionError(r.stdout+r.stderr+json.dumps(debug))
                return json.loads(r.stdout)
            def finished(receipt):
                assert receipt['ok'] and uuidlib.UUID(receipt['job'])
                for _ in range(60):
                    reply=call('job_status',{'job':receipt['job']})
                    if not reply.get('pending'): return reply
                    time.sleep(.1)
                raise AssertionError('worker did not finish')
            reply=call('lookup',{'domain':'HTTPS://Example.COM/path'})
            assert reply.get('data',{}).get('domain')=='example.com',reply
            assert (base/'tmp/nested.json').exists()
            assert not call('lookup',{'domain':'x.example;id'})['ok']
            assert not call('pause',{'seconds':1})['ok']
            failed=finished(call('pause',{'seconds':300}))
            assert not failed['ok'] and failed['reason']=='source_download' and 'HTTPS' in failed['message'],failed
            result=call('allow',{'domain':'ads.example','scope':'ads.example'})
            assert result['ok'] and 'private-backend' not in json.dumps(result),result
            assert finished(result)['ok']
            assert finished(call('resume',{}))['ok']
            assert call('source_list',{})['data']['items']==[]
            assert not call('settings_apply',{'payload':'invalid'})['ok']
            assert not call('temporary',{'domain':'ads.example','scope':'ads.example','seconds':60})['ok']
            enhanced={'before':{},'after':{'devices':[{'ip':'192.168.2.10','name':'TV','blocked':['ads.example']}]}}
            receipt=call('enhance_save',{'payload':json.dumps(enhanced)})
            assert finished(receipt)['ok'],receipt
            received=json.loads((base/'tmp/received-batch.json').read_text())
            assert received['after']['devices'][0]['blocked']==['ads.example']
            assert not list((base/'tmp/adzero-requests').iterdir())
            assert not call('enhance_save',{'payload':json.dumps({'before':{},'after':{'devices':[{'ip':'8.8.8.8'}]}})})['ok']
            payload={'revision':'a'*64,'routing_before':False,'routing_enabled':True,'items':[{'id':None,'name':'Private source','url':'https://example.com/list?token=private-batch-marker','format':'domains','enabled':True}]}
            receipt=call('settings_apply',{'payload':json.dumps(payload)})
            assert finished(receipt)['ok'],receipt
            context=base/'tmp/adzero-jobs'/receipt['job']
            assert json.loads((base/'tmp/received-batch.json').read_text())==payload
            assert not (context/'input').exists() and not list((base/'tmp/adzero-requests').iterdir())
            assert 'private-batch-marker' not in json.dumps(receipt)+(context/'log').read_text()
            assert finished(call('source_verify',{}))['ok']
            dns={'domestic':{'servers':['119.29.29.29'],'active':'119.29.29.29'},'foreign':{'servers':['8.8.8.8'],'active':'8.8.8.8'}}
            payload.update(dns_before=dns,dns=dns)
            assert finished(call('settings_apply',{'payload':json.dumps(payload)}))['ok']
            assert json.loads((base/'tmp/received-batch.json').read_text())['dns']==dns
            invalid={**payload,'dns':{**dns,'foreign':{'servers':['127.0.0.1'],'active':'127.0.0.1'}}}
            assert not call('settings_apply',{'payload':json.dumps(invalid)})['ok']
            assert not call('source_add',{'catalog':'','name':'test','url':'http://example.com/list','format':'domains'})['ok']
            assert not call('source_toggle',{'id':'../../etc','expected_url':'x','enabled':True})['ok']
            start=time.monotonic()
            started=call('source_add',{'catalog':'adaway','name':'','url':'','format':'hosts'})
            assert time.monotonic()-start < 1.5,'launcher waited for worker'
            done=finished(started)
            assert done.get('ok') and not done.get('pending'),done
            assert done['progress']['elapsed']>=0 and done['progress']['stage'] in ('queued','checking'),done
            context=base/'tmp/adzero-jobs'/started['job']
            assert (context/'action').read_text().strip()=='source-add'
            assert done['progress']['phase_elapsed']>=0,done
            assert (context/'finished').exists() and (context/'timeline').read_text().endswith(' finished\n')
            (context/'finished').write_text(str(int((context/'created').read_text())+1))
            assert call('job_status',{'job':started['job']})['progress']['elapsed']==1
            (context/'stage').write_text('private-backend-token-not-for-browser')
            (context/'reason').write_text('private-backend-token-not-for-browser')
            (context/'result').write_text('1')
            safe=call('job_status',{'job':started['job']})
            assert 'private-backend' not in json.dumps(safe) and safe['reason']=='unknown',safe
            (context/'reason').write_text('source_limit')
            (context/'source').write_text(json.dumps({'index':2,'total':14,'url':'private-marker'}))
            safe=call('job_status',{'job':started['job']})
            assert safe['reason']=='source_limit' and safe['progress']['source']==dict(index=2,total=14),safe
            assert 'private-marker' not in json.dumps(safe),safe
            for raw in ('{"index":0,"total":14}','{"index":1,"total":31}','{"index":"1","total":14}','{"index":2,', 'null'):
                (context/'source').write_text(raw)
                assert 'source' not in call('job_status',{'job':started['job']})['progress']
            assert 'private-backend' not in json.dumps(done)
            assert run('/bin/ubus','-s','/tmp/ubus.sock','call','adzero','exec','{}').returncode != 0
            # Old direct file.exec kills ctl with SIGKILL before the EXIT trap.
            direct=run('/bin/ubus','-s','/tmp/ubus.sock','call','file','exec',json.dumps({'command':'/usr/libexec/adzero/ctl','params':['enable']}))
            assert direct.returncode != 0 and 'timed out' in direct.stderr.lower(),direct
            assert (base/'tmp/long-operation.lock').is_dir(),'expected orphan after SIGKILL'
            time.sleep(1.2)  # let the fixture child sleep end before cleanup
            (base/'tmp/long-operation.lock').rmdir()
            for action in ('enable','disable','refresh','reload','routing_on','routing_off'):
                start=time.monotonic()
                receipt=call(action,{})
                assert time.monotonic()-start < .9,'launcher crossed one-second rpcd limit'
                assert finished(receipt)['ok'],action
                assert not (base/'tmp/long-operation.lock').exists(),'detached worker did not release lock'
                private=(base/'tmp/adzero-jobs'/receipt['job']/'log').read_text()
                assert 'private-backend-token' in private and 'private-backend' not in json.dumps(receipt)
            controls={'before':{'allowed':[],'blocked':[]},'after':{'allowed':['allow.example'],'blocked':['block.example','second.example']}}
            receipt=call('controls_apply',{'payload':json.dumps(controls)})
            assert finished(receipt)['ok']
            assert json.loads((base/'tmp/received-batch.json').read_text())==controls
            assert not (base/'tmp/adzero-jobs'/receipt['job']/'input').exists()
            assert not call('controls_apply',{'payload':json.dumps({**controls,'after':{'allowed':['example.org'],'blocked':['sub.example.org']}})})['ok']
            # Interrupted record detection uses a process with the exact job id.
            lost=base/'tmp/adzero-jobs'/str(uuidlib.uuid4());lost.mkdir()
            (lost/'worker').write_text('999999')
            (base/'proc/self').mkdir()
            interrupted=call('job_status',{'job':lost.name})
            assert not interrupted['ok'] and interrupted['reason']=='interrupted',interrupted
            large_status=large_status_check(base,run,ctl)
            observed=[]
            for _ in range(3):
                started=time.monotonic()
                observation=call('observation',{})
                observed.append(round(time.monotonic()-started,4))
                assert observation['ok'] and observation['data']['available'] is False,observation
                assert not any(k in observation['data'] for k in ('pid','boot','generation','sample')),observation
            assert max(observed)<.9,'snapshot crossed one-second rpcd limit'
            assert not call('verification_start',{})['ok'],'missing observer cannot claim a test started'
            assert not call('recent_set',{'enabled':True})['ok'],'missing observer cannot record'
            assert call('recent_set',{'enabled':False})['ok'],'stop and clear works with observer unavailable'
            assert not call('stats_reset',{})['ok'],'unavailable collector cannot claim a reset'
            acl=json.loads((base/'usr/share/rpcd/acl.d/luci-app-adzero.json').read_text())['luci-app-adzero']
            assert 'recent_set' in acl['write']['ubus']['adzero'] and 'recent_set' not in acl['read']['ubus']['adzero']
            assert all(method in acl['write']['ubus']['adzero'] and method not in acl['read']['ubus']['adzero'] for method in ['stats_reset','controls_apply'])
            assert not (base/'tmp/service-was-called').exists(),'observation invoked network lifecycle'
            report={'runtime':'pinned OpenWrt 24.10.8 rpcd/ubusd/ucode in isolated chroot',
                    'source_sha256':source_hash(ROOT/'luci-app-adzero'),
                    'checks':66,'controls_private_batch_and_write_acl':'passed','stats_reset_unavailable_rejected':'passed','observation_snapshot_seconds':observed,'observation_no_network_lifecycle':'passed','unavailable_verification_rejected':'passed','recent_typed_write_and_stop':'passed','rpcd_exec_timeout_seconds':1,'old_direct_exec_orphan_lock':'reproduced','private_batch_payload_and_detached_apply':'passed','finished_elapsed_is_fixed':'passed',
                    'nested_rpcd_call':'passed','typed_input_and_no_log_leak':'passed','detached_source_job':'passed',
                    'enable_disable_refresh_survive_timeout':'passed','routing_on_off_survive_timeout':'passed','public_stage_and_reason':'passed','interrupted_worker_record':'passed','large_status':large_status,'router':'not_touched'}
            (ROOT/'artifacts/runtime/rpc-result.json').write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps(report,indent=2))
        finally:
            for process in reversed(procs):
                process.terminate()
                process.wait(timeout=5)


if __name__ == '__main__': main()
