"""Production ucode planner/monitor. IO fixtures do not prove a live DNS path.

The separate network-namespace check covers kernel NAT and real conntrack.
"""
import copy
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UCODE = shlex.split(os.environ.get('ADZERO_UCODE', ''))
LIB = ROOT/'luci-app-adzero/root/usr/libexec/adzero/dns-handoff-lib.uc'
ENTRY = LIB.with_name('dns-handoff.uc')
LAN = dict(address='192.0.2.1', mask=24, device='br-lan')


def rules():
    result = {'nftables': [{'chain': dict(family='inet', table='passwall', name='PSW_DNS', handle=3)}]}
    for protocol in ('udp', 'tcp'):
        result['nftables'].append({'rule': dict(family='inet', table='passwall', chain='PSW_DNS',
            expr=[{'match': {'op': '==', 'left': {'payload': {'protocol': protocol, 'field': 'dport'}}, 'right': 53}},
                  {'counter': {'packets': 7, 'bytes': 500}}, {'redirect': {'port': 11400}}])})
    return result


def flow(client='192.0.2.107', source=51758, reply=53, target='192.0.2.1', ident=17, zone=0):
    return f'ipv4 2 udp 17 117 src={client} dst={target} sport={source} dport=53 src={target} dst={client} sport={reply} dport={source} [ASSURED] mark=0 zone={zone} use=1 id={ident}\n'

def dispatch():
    return {'nftables':[{'chain':dict(family='inet',table='passwall',name='dstnat',type='nat',hook='prerouting')},
        {'rule':dict(family='inet',table='passwall',chain='dstnat',expr=[
            {'match':{'op':'==','left':{'payload':{'protocol':'ip','field':'saddr'}},'right':'@psw_lan'}},
            {'jump':{'target':'PSW_DNS'}}])}]}


@unittest.skipUnless(UCODE, 'requires native OpenWrt ucode')
class HandoffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='adzero-handoff-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def evaluate(self, code, **data):
        script = self.root/'test.uc'
        script.write_text("import * as lib from '"+str(LIB)+"';\nlet data=json(require('fs').readfile(ARGV[0]));\n"+code)
        (self.root/'data.json').write_text(json.dumps(data))
        result = subprocess.run(UCODE+[str(script),str(self.root/'data.json')], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_only_stale_lan_router_udp_default_zone_is_planned(self):
        raw = flow()+flow(source=51759, reply=11400)+flow(client='198.51.100.8')+flow(target='8.8.8.8')+flow(zone=1)+flow(client='192.0.2.1')+flow(client='192.0.2.255')
        result = self.evaluate('print(sprintf("%J",lib.plan(data.raw,data.lan,11400)));', raw=raw, lan=LAN)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['sport'], '51758')

    def test_reject_malformed_duplicate_zone_id_and_ipv6(self):
        for raw in (flow()+'zone=0', flow().strip()+' id=18', flow(client='::1'), flow().replace('sport=53 dport=51758', 'sport=53'), flow().replace('udp 17','tcp 6'), flow(client='192.0.2.010')):
            with self.subTest(raw=raw):
                value = self.evaluate('print(sprintf("%J",lib.parse(data.raw)));', raw=raw)
                self.assertIsNone(value)

    def test_exact_deletion_matches_reply_and_zone_without_id_crash(self):
        value = self.evaluate('print(sprintf("%J",lib.deletion(lib.parse(data.raw))));', raw=flow())
        self.assertEqual(value, ['-D','-f','ipv4','-p','udp','--orig-src','192.0.2.107','--orig-dst','192.0.2.1','--sport','51758','--dport','53','--reply-src','192.0.2.1','--reply-dst','192.0.2.107','--reply-port-src','53','--reply-port-dst','51758','--zone','0'])

    def test_nft_default_chain_only_unknown_acl_and_missing_dport_rejected(self):
        self.assertTrue(self.evaluate('print(lib.target(data.rules,11400));', rules=rules()))
        variants = []
        x=rules(); x['nftables'].append(copy.deepcopy(x['nftables'][1])); variants.append(x)
        x=rules(); x['nftables'][1]['rule']['expr'][0]['match']['right']=54; variants.append(x)
        x=rules(); x['nftables'][1]['rule']['expr'].insert(0, {'return': None}); variants.append(x)
        x=rules(); x['nftables'][1]['rule']['expr'][0]['match']['left']={'meta': {'key': 'l4proto'}}; x['nftables'][1]['rule']['expr'][0]['match']['right']='udp'; variants.append(x)
        x=rules(); x['nftables'][1]['rule']['expr'][-1]['redirect']['port']=1053; variants.append(x)
        for x in variants:
            self.assertFalse(self.evaluate('print(lib.target(data.rules,11400));', rules=x))

    def test_limits_and_invalid_lan_never_create_a_partial_plan(self):
        for raw, lan in ((flow()*129, LAN), ('x'*1048577, LAN), (flow(), dict(LAN, mask=0)), (flow(), dict(LAN, device='br-lan;evil'))):
            self.assertIsNone(self.evaluate('print(sprintf("%J",lib.plan(data.raw,data.lan,11400)));', raw=raw, lan=lan))

    def test_orphaned_and_bypassed_native_chains_are_not_handoff_evidence(self):
        self.assertTrue(self.evaluate('print(lib.dispatch(data.rules));',rules=dispatch()))
        for change in ('orphan','not_nat','preceding_bypass'):
            x=dispatch()
            if change=='orphan':x['nftables'].pop()
            elif change=='not_nat':x['nftables'][0]['chain']['type']='filter'
            else:x['nftables'].insert(1,{'rule':dict(family='inet',table='passwall',chain='dstnat',expr=[{'return':None}])})
            self.assertFalse(self.evaluate('print(lib.dispatch(data.rules));',rules=x))

    def write(self, path, text, mode=None):
        path=self.root/path; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
        if mode is not None: path.chmod(mode)
        return path

    def monitor(self):
        self.write('etc/config/adzero', "config adzero 'main'\n option enabled '1'\n")
        self.write('etc/config/adblock-fast', "config adblock-fast 'config'\n option enabled '1'\n")
        self.write('etc/config/passwall', "config global\n option enabled '1'\n option dns_redirect '1'\n")
        self.write('etc/adzero/managed', '1')
        self.write('proc/uptime', '100.0 0\n')
        self.write('proc/123/stat', '123 (dnsmasq) S '+'0 '*18+'19 0\n')
        self.write('proc/123/cmdline', '/tmp/etc/passwall/bin/dnsmasq_default\0-C\0/tmp/etc/passwall/acl/default/dnsmasq.conf\0')
        self.write('tmp/etc/passwall/acl/default/dnsmasq.conf', 'port=11400\n')
        fd=self.root/'proc/123/fd'; fd.mkdir(); (fd/'3').symlink_to('socket:[900]'); (fd/'4').symlink_to('socket:[901]')
        self.write('proc/net/udp', ' 0: 00000000:2C88 00000000:0000 07 0 0 0 0 0 900\n')
        self.write('proc/net/tcp', ' 0: 00000000:2C88 00000000:0000 0A 0 0 0 0 0 901\n')
        self.write('nft.json', json.dumps(rules())); self.write('dispatch.json',json.dumps(dispatch())); self.write('flows', flow()+flow(source=51759,reply=11400))
        self.write('lan.json', json.dumps({'l3_device':'br-lan','ipv4-address':[{'address':LAN['address'],'mask':24}]}))
        self.write('probe.json', json.dumps({'dns': {'active_proxies':['passwall'], 'uncertain_proxies':[]}}))
        for binary, data in [('nft','nft.json'),('ubus','lan.json'),('probe','probe.json')]:
            self.write(('usr/libexec/adzero/' if binary=='probe' else 'usr/sbin/')+binary, '#!/bin/sh\ncat '+shlex.quote(str(self.root/data))+'\n',0o755)
        self.write('usr/sbin/nft','#!/bin/sh\ncase "$*" in *dstnat) cat '+shlex.quote(str(self.root/'dispatch.json'))+' ;; *) cat '+shlex.quote(str(self.root/'nft.json'))+' ;; esac\n',0o755)
        self.write('usr/sbin/conntrack', '#!/bin/sh\nif [ "$1" = -L ]; then cat '+shlex.quote(str(self.root/'flows'))+'; else printf "%s\\n" "$*" >> '+shlex.quote(str(self.root/'deleted'))+'; fi\n',0o755)

    def step(self):
        p=subprocess.run(UCODE+[str(ENTRY),'--','step'],env={**os.environ,'ADZERO_HANDOFF_ROOT':str(self.root)},text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr)
        return json.loads((self.root/'tmp/adzero-dns-handoff/status.json').read_text())

    def test_monitor_stabilizes_then_deletes_only_selected_tuple(self):
        self.monitor()
        self.assertEqual(self.step()['reason'],'stabilizing')
        self.assertFalse((self.root/'deleted').exists())
        self.assertEqual(self.step()['repaired'],1)
        deleted=(self.root/'deleted').read_text(); self.assertIn('--sport 51758',deleted); self.assertNotIn('51759',deleted)
        self.assertNotIn('192.0.2.',(self.root/'tmp/adzero-dns-handoff/status.json').read_text())

    def test_first_global_matches_native_passwall_with_extra_sections(self):
        self.monitor()
        self.write('etc/config/passwall', "config global\n option enabled '1'\n option dns_redirect '1'\nconfig global\n")
        self.assertEqual(self.step()['reason'],'stabilizing')
        self.assertEqual(self.step()['repaired'],1)
        (self.root/'deleted').unlink()
        # Never choose a later enabled section over the native first section.
        self.write('etc/config/passwall', "config global\n option enabled '0'\n option dns_redirect '1'\nconfig global\n option enabled '1'\n option dns_redirect '1'\n")
        self.assertEqual(self.step()['reason'],'passwall_disabled')
        self.assertFalse((self.root/'deleted').exists())

    def test_skip_reasons_identify_the_actual_gate(self):
        self.monitor()
        cases=[('etc/config/adzero',"config adzero 'main'\n option enabled '0'\n",'protection_disabled'),
               ('etc/config/adblock-fast',"config adblock-fast 'config'\n option enabled '0'\n",'backend_disabled'),
               ('etc/config/passwall',"config global\n option enabled '0'\n option dns_redirect '1'\n",'passwall_disabled'),
               ('etc/config/passwall',"config global\n option enabled '1'\n option dns_redirect '0'\n",'dns_redirect_disabled'),
               ('etc/config/passwall',"config other\n",'passwall_unconfigured'),
               ('etc/config/passwall',"config global\n option enabled '1'\n option dns_redirect '1'\nconfig acl_rules\n option enabled '1'\n",'acl_unsupported')]
        for path,text,reason in cases:
            with self.subTest(reason=reason):
                original=(self.root/path).read_text()
                self.write(path,text)
                self.assertEqual(self.step()['reason'],reason)
                self.assertFalse((self.root/'deleted').exists())
                self.write(path,original)
        self.write('etc/adzero/pause.json','{}')
        self.assertEqual(self.step()['reason'],'paused')
        (self.root/'etc/adzero/pause.json').unlink()
        (self.root/'etc/adzero/managed').unlink()
        self.assertEqual(self.step()['reason'],'not_managed')
        self.assertFalse((self.root/'deleted').exists())
        self.write('etc/adzero/managed','1')
        (self.root/'etc/config/passwall').unlink()
        self.assertEqual(self.step()['reason'],'config_unavailable')
        self.assertFalse((self.root/'deleted').exists())

    def test_monitor_rule_replacement_restarts_stabilization(self):
        self.monitor(); self.step()
        changed=rules(); changed['nftables'][0]['chain']['handle']=77
        self.write('nft.json',json.dumps(changed))
        self.assertEqual(self.step()['reason'],'stabilizing')
        self.assertFalse((self.root/'deleted').exists())
        self.assertEqual(self.step()['repaired'],1)

    def test_bind_dynamic_lan_listener_accepted_but_loopback_only_rejected(self):
        self.monitor()
        for protocol, state, inode in [('udp','07',900),('tcp','0A',901)]:
            self.write('proc/net/'+protocol,f'0: 010200C0:2C88 00000000:0000 {state} 0 0 0 0 0 {inode}\n')
        self.assertEqual(self.step()['reason'],'stabilizing')
        self.assertEqual(self.step()['repaired'],1)
        (self.root/'deleted').unlink()
        self.write('proc/net/udp','0: 0100007F:2C88 00000000:0000 07 0 0 0 0 0 900\n')
        self.assertEqual(self.step()['state'],'skipped')
        self.assertFalse((self.root/'deleted').exists())

    def test_tcp_worker_is_not_a_second_default_dns_instance(self):
        self.monitor()
        self.write('proc/124/cmdline',(self.root/'proc/123/cmdline').read_text())
        self.write('proc/124/stat','124 (dnsmasq) S 123 '+'0 '*17+'20 0\n')
        self.assertEqual(self.step()['reason'],'stabilizing')
        self.assertEqual(self.step()['repaired'],1)
        # A truly independent instance still blocks mutation.
        (self.root/'deleted').unlink()
        self.write('proc/124/stat','124 (dnsmasq) S 1 '+'0 '*17+'20 0\n')
        self.assertEqual(self.step()['state'],'skipped')
        self.assertFalse((self.root/'deleted').exists())

    def test_stale_status_and_untrusted_directory_are_not_reported_ready(self):
        self.monitor(); self.step(); self.step()
        self.write('proc/uptime','200 0\n')
        args=UCODE+[str(ENTRY),'--','status'];env={**os.environ,'ADZERO_HANDOFF_ROOT':str(self.root)}
        result=subprocess.run(args,env=env,text=True,capture_output=True)
        self.assertEqual(json.loads(result.stdout)['state'],'unavailable')
        (self.root/'tmp/adzero-dns-handoff').chmod(0o755)
        self.write('proc/uptime','100 0\n')
        result=subprocess.run(args,env=env,text=True,capture_output=True)
        self.assertEqual(json.loads(result.stdout)['state'],'unavailable')

    def test_monitor_fails_closed_for_acl_missing_tool_multiple_proxies_and_no_tcp(self):
        cases=('acl','no_tool','multi','no_tcp','pause')
        for case in cases:
            with self.subTest(case=case):
                # Each variant starts with a stable context, then changes it.
                self.monitor() if not (self.root/'proc/123/fd').exists() else None
                self.step()
                if case=='acl': self.write('etc/config/passwall',"config global\n option enabled '1'\n option dns_redirect '1'\nconfig acl_rule\n option enabled '1'\n")
                elif case=='no_tool': (self.root/'usr/sbin/conntrack').unlink()
                elif case=='multi': self.write('probe.json',json.dumps({'dns':{'active_proxies':['passwall','openclash'],'uncertain_proxies':[]}}))
                elif case=='no_tcp': self.write('proc/net/tcp','')
                else: self.write('etc/adzero/pause.json','{}')
                self.step();self.assertFalse((self.root/'deleted').exists())
                # Reset only our private fixture for the next case.
                self.tmp.cleanup(); self.tmp=tempfile.TemporaryDirectory(prefix='adzero-handoff-'); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name)


if __name__=='__main__': unittest.main()
