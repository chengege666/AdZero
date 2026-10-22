"""Controller + real UCI/ucode + four adapters, with isolated service/API fixtures.

The backend fixture implements the pinned 1.2.4-r4 subtree allow semantics.
It is not a live proxy, DNS resolver, network restart or router acceptance test.
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UCODE = shlex.split(os.environ.get('ADZERO_UCODE', ''))
SHELL = shlex.split(os.environ.get('ADZERO_TEST_SHELL', '/bin/sh'))
LIBEXEC = ROOT / 'luci-app-adzero/root/usr/libexec/adzero'


@unittest.skipUnless(UCODE, 'requires actual OpenWrt runtime')
class ControlsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='adzero-controls-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write('etc/config/adzero', "config adzero 'main'\n option enabled '0'\n")
        self.write('etc/config/adblock-fast', "config adblock-fast 'config'\n option enabled '0'\n option dns 'dnsmasq.servers'\n option force_dns '1'\n option download_allow_insecure '1'\n list blocked_domain 'ads.example'\n list allowed_domain 'user.example'\n")
        self.write('proc/sys/kernel/random/boot_id', 'test-boot\n')
        self.write('proc/uptime', '1000.0 100\n')
        native = ROOT / '.sdk/runtime-24.10.8'
        uci = self.write('bin/uci', '#!/bin/sh\nexec ' + shlex.join([str(native/'libc.so'), '--library-path', str(native), str(native/'uci'), '-c', str(self.root/'etc/config')]) + ' "$@"\n', True)
        self.env = {**os.environ, 'ADZERO_UCI': str(uci), 'ADZERO_POLICY_ROOT': str(self.root), 'ADZERO_SOURCES_ROOT': str(self.root),
                    'ADZERO_ADAPTER_ROOT': str(self.root), 'ADZERO_BACKEND_ROOT': str(self.root),
                    'ADZERO_STATE_DIR': str(self.root/'etc/adzero'), 'ADZERO_LOCK_DIR': str(self.root/'lock'),
                    'ADZERO_ADAPTER_INVENTORY': str(self.root/'inventory.json'),
                    'ADZERO_BACKEND_SERVICE_FIXTURE': str(self.root/'service.json'),
                    'ADZERO_PIDOF': str(self.write('bin/pidof', '#!/bin/sh\nexit 1\n', True)),
                    'ADZERO_PROBE': str(self.write('bin/probe', '#!/bin/sh\ncat '+shlex.quote(str(self.root/'inventory.json'))+'\n', True))}
        backend = self.write('bin/service', '''#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
r=Path(os.environ['ADZERO_POLICY_ROOT']); output=r/'var/run/adblock-fast/dnsmasq.servers'
service={'dnsmasq':{'instances':{'test':{'running':True}}}}
if sys.argv[1] != 'stop':
 (r/'last-start-method').write_text(sys.argv[1])
 flag=r/'fail-backend-once'
 if flag.exists(): flag.unlink(); sys.exit(2)
 values=subprocess.check_output([os.environ['ADZERO_UCI'],'-q','get','adblock-fast.config.allowed_domain'],text=True).split()
 domains=['ads.example','tracker.example','sub.ads.example']
 # Optional DNS-domain subscription fixtures exercise the production source ->
 # backend output -> adapter pipeline without downloading or restarting a router.
 downloads=r/'source-downloads.json'
 if downloads.exists():
  import re
  bodies=json.loads(downloads.read_text())
  def option(key):
   p=subprocess.run([os.environ['ADZERO_UCI'],'-q','get',key],text=True,capture_output=True)
   return p.stdout.strip()
  config=subprocess.check_output([os.environ['ADZERO_UCI'],'show','adblock-fast'],text=True)
  for section in re.findall(r'^adblock-fast\.([^=]+)=file_url$',config,re.M):
   key='adblock-fast.'+section+'.'
   if option(key+'enabled')=='1': domains.extend(bodies.get(option(key+'url'),[]))
 rules=sorted({d for d in domains if not any(d==a or d.endswith('.'+a) for a in values)})
 output.parent.mkdir(parents=True,exist_ok=True)
 output.write_text(''.join('server=/'+d+'/\\n' for d in rules)+''.join('server=/'+d+'/#\\n' for d in values))
 service['adblock-fast']={'data':{'status':'statusSuccess','errors':[],'warnings':[],'entries':len(rules),'dns':'dnsmasq.servers','force_dns_active':False,'outputFile':'/var/run/adblock-fast/dnsmasq.servers'}}
else:
 if output.exists():
  cache=output.with_name(output.name+'.cache'); cache.write_bytes(output.read_bytes()); output.unlink()
(r/'service.json').write_text(json.dumps(service))
''', True)
        self.env['ADZERO_BACKEND_INIT'] = str(backend)
        for name in ('adapter','backend'):
            key = 'ADZERO_ADAPTER' if name == 'adapter' else 'ADZERO_BACKEND_CHECK'
            self.env[key] = str(self.write('bin/'+name, '#!/bin/sh\nexec '+shlex.join(UCODE+[str(LIBEXEC/(name+'.uc')),'--'])+' "$@"\n', True))
        self.select('passwall')
        subprocess.run([str(backend), 'stop'], env=self.env, check=True)

    def write(self, path, content, executable=False):
        p = self.root / path; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content); p.chmod(0o755 if executable else 0o600); return p

    def select(self, plugin):
        self.write('inventory.json', json.dumps({'dns': {'active_proxy_count': 1}, 'plugins': [{'id': plugin, 'installed': True, 'enabled': True, 'runtime': 'running'}]}))
        self.write('etc/init.d/' + plugin, '#!/bin/sh\nexit 0\n')
        self.write('etc/config/passwall', "config global\n option enabled '1'\n option use_block_list '0'\n")
        self.write('etc/passwall/rules/block_host', 'user-block.example\n')
        if plugin == 'passwall':
            # This fixture now models the native generated DNS handoff. Inert
            # restart scripts exercise the missing-runtime retry path elsewhere.
            self.write('proc/900/comm','dnsmasq_default\n')
            self.write('proc/900/cmdline','/tmp/etc/passwall/bin/dnsmasq_default\0-C\0/tmp/etc/passwall/acl/default/dnsmasq.conf\0')
            self.write('proc/900/stat','900 dnsmasq fixture\n')
            generator=self.write('dns-fixture.py', '''from pathlib import Path
import os
r=Path(os.environ['ADZERO_ADAPTER_ROOT'])
d=r/'tmp/etc/passwall/acl/default';(d/'dnsmasq.d').mkdir(parents=True,exist_ok=True)
(d/'dnsmasq.conf').write_text('port=11400\\nconf-dir=/tmp/etc/passwall/acl/default/dnsmasq.d\\n')
names=[s.strip() for s in (r/'etc/passwall/rules/block_host').read_text().splitlines() if s.strip() and not s.startswith('#')]
(d/'dnsmasq.d/000-address.conf').write_text(''.join('address=/.'+s+'/\\n' for s in names))
''')
            self.write('etc/init.d/passwall','#!/bin/sh\nexec python3 '+shlex.quote(str(generator))+'\n')
        if plugin == 'nikki':
            self.write('etc/config/nikki', "config nikki 'config'\n option enabled '1'\nconfig mixin 'mixin'\n option mixin_file_content '0'\n")
            mixin = self.write('etc/nikki/mixin.yaml', '# original\n')
            base = self.write('etc/nikki/base.yaml', 'dns:\n  enable: true\n  enhanced-mode: fake-ip\n  fake-ip-filter: ["+.lan"]\nrules: ["MATCH,DIRECT"]\n')
            run = self.write('etc/nikki/run/config.yaml', base.read_text())
            self.write('etc/init.d/nikki', '#!/bin/sh\nyq -o=json eval-all \'. as $item ireduce ({}; . * $item ) | .rules = .nikki-rules + .rules | del(.nikki-rules)\' '+shlex.join([str(base),str(mixin)])+' > '+shlex.quote(str(run))+'\n')
        if plugin == 'openclash':
            self.write('etc/config/openclash', "config openclash 'config'\n option config_path '/etc/openclash/config/config.yaml'\n")
            custom = self.write('etc/openclash/custom/openclash_custom_overwrite.sh', '#!/bin/sh\n# original\nexit 0\n')
            base = self.write('etc/openclash/source.yaml', 'dns:\n  enable: true\n  enhanced-mode: fake-ip\n  fake-ip-filter: ["+.lan"]\nrules: ["MATCH,DIRECT"]\n')
            run = self.root/'etc/openclash/config.yaml'
            self.write('etc/openclash/core/clash_meta', '#!/bin/sh\nexit 0\n', True)
            self.write('etc/init.d/openclash', '#!/bin/sh\ncp '+shlex.join([str(base),str(run)])+'\nif grep -q "ADZERO MANAGED BEGIN" '+shlex.quote(str(custom))+'; then\n'+shlex.join(UCODE+[str(LIBEXEC/'adapter.uc'),'--','hook-openclash','/etc/openclash/config.yaml'])+'\nfi\n')
        if plugin == 'nailink':
            self.write('profile.json', json.dumps({'id':'profile-1','dns':{'string':'upstream { local: "udp://127.0.0.1:5353" }\nrouting { request { fallback: local } response { fallback: accept } }'}}))
            api = self.write('bin/nailink-api', '''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
r=Path(os.environ['ADZERO_POLICY_ROOT']); p=r/'profile.json'; profile=json.loads(p.read_text()); req=json.loads(Path(sys.argv[1]).read_text()); q=req['query']; v=req['variables']
if 'general{' in q: result={'general':{'dae':{'running':True}}}
elif 'dnss(' in q: result={'dnss':[profile]}
elif 'parsedDns' in q: result={'parsedDns':{'string':v['raw']}}
elif 'updateDns' in q:
 assert v['id']==profile['id']; profile['dns']['string']=v['dns']; p.write_text(json.dumps(profile)); result={'updateDns':{'id':profile['id']}}
else: result={'run':True}
print(json.dumps(result))
''', True)
            self.env['ADZERO_NAILINK_API_FIXTURE'] = str(api)

    def ctl(self, *args, ok=True):
        p = subprocess.run(SHELL+[str(LIBEXEC/'ctl'),*args],env=self.env,text=True,capture_output=True,timeout=45)
        self.assertEqual(p.returncode == 0,ok,p.stdout+p.stderr)
        return p

    def status(self): return json.loads(self.ctl('status').stdout)
    def query(self, domain): return json.loads(self.ctl('lookup', domain).stdout)

    def cycle(self, plugin):
        self.select(plugin)
        self.ctl('enable')
        original = self.status()
        self.assertEqual(original['adapter']['plugin'], plugin)
        self.assertEqual(self.query('login.ads.example')['scope'], 'ads.example')
        self.ctl('allow','login.ads.example','ads.example')
        self.assertEqual(self.query('login.ads.example')['match'], 'allowed')
        self.assertEqual(self.status()['adapter']['domains'], 1)
        self.assertNotIn('server=/ads.example/\n',(self.root/'var/run/adblock-fast/dnsmasq.servers').read_text())
        self.ctl('revoke','ads.example','ads.example')
        self.assertEqual(self.query('login.ads.example')['match'], 'parent')
        self.ctl('pause','300')
        s = self.status(); self.assertEqual(s['state'], 'paused'); self.assertEqual(s['adapter']['stage'], 'inactive')
        self.assertEqual(s['backend']['state'], 'stopped')
        self.write('proc/uptime','1301.0 100\n'); self.ctl('reconcile')
        self.assertEqual(self.status()['state'], 'configured_unverified')
        self.assertEqual(self.status()['adapter']['plugin'], plugin)
        self.ctl('disable')
        self.assertEqual(self.status()['state'], 'disabled')
        self.assertFalse((self.root/'etc/adzero/pause.json').exists())
        self.assertNotIn('ADZERO MANAGED', (self.root/'etc/passwall/rules/block_host').read_text())

    def test_passwall_complete_cycle(self): self.cycle('passwall')
    def test_nailink_complete_cycle(self):
        self.cycle('nailink')
        self.assertNotIn('ADZERO MANAGED', (self.root/'profile.json').read_text())
    @unittest.skipUnless(shutil.which('yq'), 'actual yq required')
    def test_nikki_complete_cycle(self): self.cycle('nikki')
    @unittest.skipUnless(shutil.which('ruby'), 'actual Ruby required')
    def test_openclash_complete_cycle(self): self.cycle('openclash')

    def test_allow_failed_download_restores_old_policy_and_rules(self):
        self.ctl('enable'); self.write('fail-backend-once','1')
        self.ctl('allow','ads.example','ads.example',ok=False)
        self.assertEqual(self.status()['policy']['allowed'],[])
        self.assertEqual(self.status()['state'],'configured_unverified')
        self.assertEqual(self.query('ads.example')['match'],'exact')
        self.assertFalse((self.root/'etc/adzero/allow-pending.json').exists())

    def test_allow_adapter_restart_failure_rolls_back_every_layer(self):
        self.ctl('enable')
        flag = self.write('fail-proxy-once','1')
        self.write('etc/init.d/passwall', '#!/bin/sh\nif [ -f '+shlex.quote(str(flag))+' ]; then rm '+shlex.quote(str(flag))+'; exit 1; fi\nexit 0\n')
        self.ctl('allow','ads.example','ads.example',ok=False)
        self.assertEqual(self.status()['policy']['allowed'],[])
        self.assertEqual(self.status()['adapter']['domains'],3)
        self.assertEqual(self.query('ads.example')['match'],'exact')

    def test_failed_resume_stays_paused_and_retries_after_cooldown(self):
        self.ctl('enable'); self.ctl('pause','300'); self.write('fail-backend-once','1')
        self.ctl('resume',ok=False)
        s=self.status(); self.assertEqual(s['state'],'paused'); self.assertEqual(s['policy']['pause']['error'],'resume_failed')
        self.ctl('reconcile'); self.assertEqual(self.status()['state'],'paused')
        self.write('proc/uptime','1400 100\n'); self.ctl('reconcile')
        self.assertEqual(self.status()['state'],'configured_unverified')

    def test_disable_cancels_pause_and_personal_choice_survives_reenable(self):
        self.ctl('enable'); self.ctl('allow','ads.example','ads.example'); self.ctl('pause','900'); self.ctl('disable')
        self.write('proc/uptime','5000 100\n'); self.ctl('reconcile')
        self.assertEqual(self.status()['state'],'disabled')
        self.ctl('enable'); self.assertEqual(self.query('ads.example')['match'],'allowed')
        self.assertIn('user.example',(self.root/'etc/config/adblock-fast').read_text())

    def test_reboot_expires_pause_without_wall_clock_and_resumes(self):
        self.ctl('enable'); self.ctl('pause','1800'); self.write('proc/sys/kernel/random/boot_id','new-boot\n'); self.write('proc/uptime','20 1\n')
        self.ctl('reconcile'); self.assertEqual(self.status()['state'],'configured_unverified')

    def test_invalid_scope_cannot_change_rules(self):
        self.ctl('enable'); before=(self.root/'etc/config/adblock-fast').read_bytes()
        self.ctl('allow','login.ads.example','example',ok=False)
        self.assertEqual(before,(self.root/'etc/config/adblock-fast').read_bytes())
        self.assertEqual(self.status()['state'],'configured_unverified')
