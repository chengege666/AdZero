#!/usr/bin/env node
/* Native LuCI attribute semantics, command/result and accessibility regressions. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(process.argv[2] || path.join(__dirname, '../luci-app-adzero/htdocs/luci-static/resources/view/adzero/overview.js'), 'utf8');
let root, active, assertions = 0;
function nodes(n, pred) {
  if (n == null || typeof n !== 'object') return [];
  if (Array.isArray(n)) return n.flatMap(x => nodes(x, pred));
  return (pred(n) ? [n] : []).concat(nodes(n.children, pred));
}
function text(n) { return n == null ? '' : Array.isArray(n) ? n.map(text).join(' ') : typeof n === 'object' ? text(n.children) : String(n); }
function E(tag, attrs = {}, children = []) {
  // LuCI's array append stringifies null; scalar strings are HTML. The view
  // must normalize all dynamic children into text arrays before reaching E.
  const original = children;
  children = Array.isArray(children) ? children.map(x => typeof x === 'object' && x !== null ? x : String(x)) : children == null ? [] : [children];
  const el = { tag, attrs: {}, events: {}, children, scalarHtml: typeof original === 'string', focus() { active = this; }, contains(x) { return nodes(this, n => n === x).length > 0; } };
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (typeof v === 'function') el.events[k] = v;
    else el.attrs[k] = String(v); // LuCI setAttribute: even false is PRESENT.
  }
  el.disabled = Object.hasOwn(el.attrs, 'disabled'); el.open = Object.hasOwn(el.attrs, 'open'); return el;
}
const body = E('body'); active = body;
const doc = { body, contains: n => !!nodes(root, x => x === n).length, get activeElement() { return active; }, getElementById(id) { return nodes(root, n => n.attrs.id === id)[0] || null; } };
const commands = [];
let state, failAction, failStatus, pending, resolveAction, staleResult, statusPending, resolveStatus;
const api = { exec: async (program, args) => {
  assert.equal(program, '/usr/libexec/adzero/ctl'); commands.push(args[0]);
  assert.equal(args[0], 'status', 'only short reads may use file.exec');
  if (args[0] === 'status') { if (statusPending) await new Promise(r => { resolveStatus = r; }); if (failStatus) throw new Error('status unreachable'); return { code: 0, stdout: JSON.stringify(state) }; }
} };
let rpcFailure = false, rpcStale = false, rpcListFailure = false, storageBlocked = false, sessionID = 'b'.repeat(32), jobSteps=[], ruleData, lookup = {available:true,domain:'login.ads.example',match:'parent',rule:'ads.example',scope:'ads.example'};
const storage = new Map();
const session = {getItem:k=>{if(storageBlocked)throw Error('storage unavailable');return storage.get(k)||null;},setItem:(k,v)=>{if(storageBlocked)throw Error('storage unavailable');storage.set(k,v);},removeItem:k=>storage.delete(k)};
const rpc = { getSessionID:()=> sessionID, declare: spec => async (...args) => {
  assert.equal(spec.object,'adzero'); commands.push(spec.method);
  if (rpcFailure) return {ok:false,message:'typed failure'};
  if (['enable','disable','refresh','reload'].includes(spec.method)) {
    if (pending) await new Promise(r => { resolveAction = r; });
    if (failAction) return {ok:false,message:'<script>untrusted error</script>'};
    if (!staleResult) state.state = spec.method === 'disable' ? 'disabled' : 'configured_unverified';
    return {ok:true,job:'11111111-1111-1111-1111-111111111111'};
  }
  if (spec.method === 'source_list') return rpcListFailure ? {ok:false,message:'list unavailable'} : {ok:true,data:structuredClone(ruleData)};
  if (spec.method === 'settings_apply') {
    const p=JSON.parse(args[0]);
    if(!rpcStale){ruleData.items=p.items.map((i,n)=>({...i,id:i.id||'batch_'+n,https:true}));state.policy.routing_enabled=p.routing_enabled;ruleData.revision='d'.repeat(64);if(p.dns)ruleData.dns=structuredClone(p.dns);}
    return {ok:true,job:'11111111-1111-1111-1111-111111111111'};
  }
  if (spec.method === 'job_status') {let next=jobSteps.shift();if(next instanceof Error)throw next;return typeof next==='function'?next():next || {ok:true,pending:false};}
  if (spec.method.startsWith('source_')) {
    if (!rpcStale && spec.method==='source_add') ruleData.items.push({id:'new1',catalog_id:args[0]||null,name:args[1]||'Library rule',url:args[2]||'https://library.example/list',https:true,enabled:true,domains:42});
    if (!rpcStale && spec.method==='source_toggle') ruleData.items.find(i=>i.id===args[0]).enabled=args[2];
    if (!rpcStale && spec.method==='source_remove') ruleData.items=ruleData.items.filter(i=>i.id!==args[0]);
    if (!rpcStale && spec.method==='source_refresh') ruleData.items.filter(i=>i.format==='unknown').forEach(i=>Object.assign(i,{domains:27,format:'domains',validation:'validated',updated:1700000000}));
    return {ok:true,job:'11111111-1111-1111-1111-111111111111'};
  }
  if (spec.method === 'lookup') return {ok:true,data:lookup};
  if (!rpcStale) {
    if (['routing_on','routing_off'].includes(spec.method)) { state.policy.routing_enabled=spec.method==='routing_on';state.adapter.routing={mode:spec.method==='routing_on'?'proxy':'inactive'}; }
    if (spec.method === 'allow') state.policy.allowed.push(args[1]);
    if (spec.method === 'revoke') state.policy.allowed = state.policy.allowed.filter(x => x !== args[1]);
    state.state = spec.method === 'pause' ? 'paused' : 'configured_unverified';
    state.policy.pause = spec.method === 'pause' ? {stage:'paused',remaining:args[0]} : null;
  }
  return {ok:true,job:'11111111-1111-1111-1111-111111111111'};
} };
const app = Function('view', 'fs', 'dom', '_', 'E', 'document', 'L', 'rpc', 'poll', 'sessionStorage', 'setTimeout', source)(
  { extend: x => x }, api, { content: (target, children) => { target.children = children; } }, x => x, E, doc, { resource: x => '/luci-static/resources/' + x }, rpc, {add:()=>{},remove:()=>{}},session,fn=>queueMicrotask(fn));
function reset(overrides = {}) {
  state = { state: 'disabled', managed: false, dns_mode_safe: true, resolver: 'dnsmasq.servers', client_dns_verified: false,
    policy:{allowed:[],pause:null,routing_enabled:false}, force_dns: 'off', tls_download: 'strict', backend: { state: 'ready', domains: 66425, warnings: 1 }, adapter: { plugin: 'nailink', stage: 'configured_unverified' },
    compatibility: { platform: { distribution: 'OpenWrt', version: '25.12.5', cpu: 'aarch64', target: 'rockchip/armv8', package_manager: 'apk', declared_arch: 'aarch64_generic' },
      dns: { active_proxy_count: 1 }, plugins: ['nailink', 'passwall', 'passwall2', 'openclash', 'nikki'].map((id, i) => ({ id, installed: true, enabled: i === 0, runtime: i === 0 ? 'running' : 'unknown' })) }, ...overrides };
  failAction = failStatus = pending = staleResult = statusPending = rpcFailure = rpcStale = rpcListFailure = storageBlocked = false; sessionID='b'.repeat(32); commands.length = 0;
  app.dnsOpen=false;app.dnsForm=null;app.dnsFormBase=null;
  storage.clear();ruleData={dns:{domestic:{servers:['223.5.5.5','119.29.29.29'],active:'223.5.5.5'},foreign:{servers:['1.1.1.1','8.8.8.8'],active:'1.1.1.1'}},revision:'a'.repeat(64),items:[],catalog:[{id:'test',name:'Library example',url:'https://library.example/list',home:'https://library.example/',description:'test list',group:'Light'}]};
  app.draft=app.applyingDraft=app.editSource=null;app.draftSequence=0;
  app.rulesOpen=false;app.sourcesData=null;app.sourcesLoading=false;app.sourcesError=null;
  jobSteps=[];app.currentJob=null;app.jobUncertain=false;app.jobProgress=null;
  app.busy = app.notice = app.domainResult = null; app.domainInput = ''; root = app.render(state); active = body;
}
const find = id => doc.getElementById(id);
function check(value, label) { assert.ok(value, label); assertions++; }
(async () => {
  reset();
  check(!find('az-toggle').disabled, 'enable omits disabled attribute');
  check(!text(root).includes('null') && !text(root).includes('undefined'), 'absent content is not rendered by native array append');
  check(!nodes(root, n => n.scalarHtml).length, 'all dynamic content reaches native DOM as text arrays');
  check(find('az-update').disabled, 'cannot update while off');
  check(find('az-toggle').attrs['aria-checked'] === 'false', 'off announced');
  check(nodes(root, n => n.tag === 'link')[0].attrs.href.includes('overview.css?v='), 'local versioned CSS');
  await app.runAction('enable'); assert.deepEqual(commands, ['enable', 'job_status', 'status']);
  check(find('az-toggle').attrs['aria-checked'] === 'true', 'on only after backend status');
  check(!find('az-update').disabled && !find('az-toggle').disabled, 'actions genuinely enabled');
  check(text(root).includes('66,425'), 'real domain count');
  check(text(root).includes('终端待验证') && !text(root).includes('今日拦截'), 'no invented effectiveness/stats');
  check(active === find('az-toggle'), 'focus restored to initiating control');
  check(!find('az-plugins') && !find('az-diagnostics'), 'technical inventory panels are not rendered');
  check(!text(root).includes('aarch64_generic') && !text(root).includes('PassWall 2'), 'unused platform and plugin inventory is absent');
  await app.refreshStatus(); check(text(root).includes('NaiLink / daed'), 'current integration remains visible after refresh');
  await app.runAction('refresh'); check(app.notice.kind === 'success', 'update success inline');
  await app.runAction('disable'); check(state.state === 'disabled', 'disable works');
  for (const overrides of [{ dns_mode_safe: false }, { adguardhome_running: true }, { state: 'external_owner' }, { state: 'unavailable' }, { state: 'error' }]) {
    reset(overrides); check(find('az-toggle').disabled, 'blocked switch'); await app.runAction('enable'); check(commands.length === 0, 'blocked action');
  }
  reset(); state.compatibility.dns.active_proxy_count = 2; root = app.render(state);
  check(find('az-toggle').disabled && text(root).includes('多个代理'), 'multi proxy guard');
  reset({ state: 'inconsistent', managed: true });
  check(!find('az-toggle').disabled && text(find('az-toggle')).includes('关闭并恢复'), 'recovery available');
  await app.runAction('disable'); check(state.state === 'disabled', 'recover via disable');
  reset(); pending = true; const first = app.runAction('enable');
  check(find('az-toggle').disabled && find('az-status').disabled && find('az-update').disabled, 'controls lock during operation');
  check(find('az-toggle').attrs['aria-checked'] === 'false', 'no optimistic switch');
  await app.runAction('enable'); await app.refreshStatus(); await app.runAction('reboot');
  check(commands.length === 1, 'duplicates and arbitrary commands ignored');
  resolveAction(); await first; check(app.busy === null && !find('az-toggle').disabled, 'unlocks');
  reset(); failAction = true; await app.runAction('enable');
  check(commands.join(',') === 'enable,status' && state.state === 'disabled', 'failure reads truth');
  check(app.notice.kind === 'error' && text(root).includes('<script>untrusted error</script>'), 'error as text');
  check(!nodes(root, n => n.tag === 'script').length, 'no HTML injection');
  reset(); staleResult = true; await app.runAction('enable'); check(app.notice.kind === 'error', 'wrong status is not success');
  reset(); failStatus = true; await app.runAction('enable');
  check(app.currentStatus.state === 'error' && app.notice.kind === 'error', 'unknown result');
  check(active === find('az-status') && !find('az-status').disabled, 'retry focused');
  failStatus = false; await app.refreshStatus(); check(app.currentStatus.state === 'configured_unverified', 'retry recovers');
  reset(); active = E('input'); await app.runAction('enable'); check(active.tag === 'input', 'no focus steal outside panel');
  reset({ backend: { state: 'failed', domains: 99999 }, state: 'configured_unverified' }); check(!text(root).includes('99,999'), 'unhealthy count hidden');
  reset();
  const initial = await app.load();
  check(initial.state === 'loading' && commands.length === 0, 'load does not wait for or start status RPC');
  statusPending = true; root = app.render(initial);
  check(typeof root.then !== 'function' && text(root).includes('正在读取运行状态'), 'view renders immediately while status is pending');
  check(find('az-toggle').disabled && find('az-update').disabled, 'initial actions locked until fresh status');
  check(commands.join(',') === 'status', 'exactly one initial request');
  resolveStatus(); await app.initialRequest;
  check(app.currentStatus.state === 'disabled' && !find('az-toggle').disabled, 'initial response hydrates view');
  check(active === body, 'initial response does not steal focus');
  reset(); failStatus = true; root = app.render(await app.load()); await app.initialRequest;
  check(app.currentStatus.state === 'error' && !find('az-status').disabled, 'initial RPC failure keeps a working retry');
  check(text(root).includes('查看状态读取错误') && text(root).includes('status unreachable'), 'initial read exposes actual error instead of assuming network disconnected');
  for (const [id, label] of [['passwall', 'PassWall'], ['openclash', 'OpenClash'], ['nikki', 'Nikki']]) {
    reset({ state: 'configured_unverified', adapter: { plugin: id, stage: 'configured_unverified' } });
    check(text(root).includes(label), 'active adapter name ' + id);
  }
  reset({ state: 'inconsistent', managed: true, backend: { state: 'failed', errors: 1 } });
  check(text(root).includes('过滤后端报告错误') && !find('az-toggle').disabled, 'essential backend warning and recovery survive simplification');
  reset({ state: 'error', error: '<img src=x onerror=alert(1)>' });
  check(!nodes(root, n => n.scalarHtml).length, 'untrusted data cannot reach innerHTML');
  reset(); check(find('az-domain').disabled && find('az-lookup').disabled,'query unavailable when off');
  await app.lookupDomain(); check(!commands.length,'no query while off');
  reset({state:'configured_unverified'}); app.domainInput='login.ads.example';
  await app.lookupDomain();
  check(text(root).includes('ads.example') && text(root).includes('及其所有子域'),'actual subtree scope visible before mutation');
  check(!commands.includes('allow'),'query does not write');
  await app.runPolicy('allow',['login.ads.example','ads.example']);
  check(state.policy.allowed.includes('ads.example') && app.notice.kind === 'success','typed allow then canonical status');
  check(text(root).includes('撤销放行'),'personal list has undo');
  await app.runPolicy('revoke',['ads.example','ads.example']);
  check(!state.policy.allowed.length && app.notice.kind === 'success','revoke status verified');
  await app.runPolicy('pause',[900]);
  check(state.state === 'paused' && text(root).includes('15 分钟后'),'pause deadline visible');
  check(find('az-domain').disabled && find('az-update').disabled && !find('az-resume').disabled,'paused controls guarded');
  check(find('az-toggle').attrs['data-action'] === 'resume','paused switch resumes');
  state.state='configured_unverified'; await app.pausePoll();
  check(app.currentStatus.state==='configured_unverified' && app.notice===null,'automatic resume clears obsolete paused notice');
  state.state='paused'; app.currentStatus=state;
  await app.runPolicy('resume',[]); check(state.state === 'configured_unverified','resume supported');
  await app.runPolicy('routing_on',[]);check(state.policy.routing_enabled && app.notice.kind==='success' && find('az-routing').attrs['aria-checked']==='true','routing preference confirmed through typed background job');
  check(text(root).includes('国内直连 / 国外代理'),'actual applied proxy mode displayed');
  rpcStale=true;await app.runPolicy('routing_off',[]);check(app.notice.kind==='error' && state.policy.routing_enabled,'routing switch does not claim success without canonical preference');
  rpcStale=false;await app.runPolicy('routing_off',[]);check(!state.policy.routing_enabled && state.state==='configured_unverified','disabling routing retains ad protection');
  reset({state:'configured_unverified',policy:{allowed:[],routing_enabled:true},adapter:{plugin:'none',routing:{mode:'direct'}}});check(text(root).includes('国内 DNS / 全部直连'),'no-proxy mode explains domestic resolution and direct traffic');
  reset();check(!find('az-routing').disabled,'routing preference may be staged while protection is off');
  reset({state:'configured_unverified'});
  rpcStale=true; await app.runPolicy('allow',['ads.example','ads.example']); check(app.notice.kind==='error','stale RPC success rejected');
  rpcStale=false; rpcFailure=true; await app.runPolicy('pause',[300]); check(app.notice.kind==='error' && state.state!=='paused','RPC failure is not optimistic pause');
  reset({state:'configured_unverified'}); app.domainInput=''; await app.lookupDomain(); check(!commands.length && text(root).includes('请输入'),'empty query validation');
  app.domainInput='ads.example'; rpcFailure=true; await app.lookupDomain(); check(text(root).includes('typed failure') && !find('az-allow'),'query failure cannot enable allow');
  reset({state:'paused',policy:{allowed:['ads.example'],pause:{remaining:0,error:'resume_failed'}}});
  check(text(root).includes('自动恢复未完成') && !find('az-resume').disabled,'failed automatic resume remains actionable');
  await app.runAction('disable'); check(state.state==='disabled','manual close cancels pause via canonical controller');
  reset({state:'configured_unverified'});await app.refreshStatus();
  statusPending=true;const cached=await app.load();root=app.render(cached);
  check(cached.stale && text(root).includes('66,425') && !text(root).includes('正在读取运行状态'),'return navigation paints last snapshot immediately');
  check(find('az-toggle').disabled && find('az-update').disabled && find('az-domain').disabled,'cached snapshot cannot authorize mutations');
  resolveStatus();await app.initialRequest;check(!app.currentStatus.stale && !find('az-toggle').disabled,'background recheck restores live controls');
  statusPending=false;failStatus=true;await app.refreshStatus();
  check(app.currentStatus.stale && text(root).includes('66,425') && find('az-toggle').disabled && !find('az-status').disabled,'recheck failure preserves snapshot with retry and locked operations');
  check(!JSON.stringify([...storage.values()]).includes('aarch64_generic'),'snapshot excludes technical inventory');
  reset();await app.refreshStatus();const cacheKey='adzero.v0.8.'+sessionID+'.snapshot',snapshot=storage.get(cacheKey);
  const expired=JSON.parse(snapshot);expired.at-=300001;storage.set(cacheKey,JSON.stringify(expired));
  check((await app.load()).state==='loading','expired snapshot falls back to live loading');
  storage.set(cacheKey,snapshot);sessionID='c'.repeat(32);check((await app.load()).state==='loading','new login cannot reuse old session snapshot');
  sessionID='b'.repeat(32);storage.set(cacheKey,'invalid JSON');check((await app.load()).state==='loading','corrupt storage falls back safely');
  storageBlocked=true;await app.refreshStatus();check(!find('az-toggle').disabled && (await app.load()).state==='loading','storage-disabled browser retains live controls');
  reset();await app.openRules();check(text(root).includes('我的过滤规则') && text(root).includes('Library example'),'rule library renders separately');
  await app.runSource('source_add',['','Personal list','https://rules.example/list','domains']);
  check(ruleData.items.length===1 && text(root).includes('Personal list') && state.state==='disabled','add source while off preserves master switch');
  await app.runSource('source_toggle',['new1','https://rules.example/list',false]);
  check(!ruleData.items[0].enabled && text(root).includes('选择已保存'),'rule switch persisted after job and canonical reread');
  await app.runSource('source_remove',['new1','https://rules.example/list']);check(!ruleData.items.length,'source removal');
  check(!storage.has('adzero.v0.8.'+'b'.repeat(32)+'.job'),'completed job receipt cleared');
  const before=commands.length;await app.runSource('source_add',['','','http://unsafe.example/list','domains']);check(commands.length===before && app.notice.kind==='error','invalid custom form stays local');
  rpcStale=true;await app.runSource('source_add',['','Not persisted','https://missing.example/list','domains']);check(app.notice.kind==='error','finished job without persisted subscription is not success');
  rpcStale=false;rpcListFailure=true;await app.runSource('source_refresh',[]);check(app.notice.kind==='error' && find('az-source-add').disabled,'unreadable source list prevents success and editing');
  reset();storage.set('adzero.v0.8.'+sessionID+'.job',JSON.stringify('11111111-1111-1111-1111-111111111111'));
  root=app.render({state:'loading'});await app.initialRequest;
  check(app.rulesOpen && commands.includes('job_status') && !storage.has('adzero.v0.8.'+sessionID+'.job'),'navigation resumes stored job receipt and reconciles result');
  for (const [kind,action] of [['action','enable'],['policy','allow'],['policy','resume'],['policy','routing_off']]) {
    reset({state:'configured_unverified'});
    storage.set('adzero.v0.8.'+sessionID+'.job',JSON.stringify({job:'11111111-1111-1111-1111-111111111111',kind,action}));
    root=app.render({state:'loading'});await app.initialRequest;
    check(commands.join(',')==='status,job_status,status' && app.notice.kind==='success','navigation reconciles '+action+' without submitting it twice');
    check(!storage.has('adzero.v0.8.'+sessionID+'.job'),'receipt cleared after '+action+' confirmation');
  }
  reset({state:'paused'});await app.openRules();check(find('az-source-add').disabled,'paused sources cannot be edited');
  reset({state:'configured_unverified'});
  ruleData.items=[{id:'legacy',name:'Existing list',url:'https://legacy.example/list',https:true,enabled:true,format:'unknown',validation:'unchecked',domains:null,updated:null}];
  await app.openRules();check(text(root).includes('待校验')&&text(root).includes('更新时自动校验'),'legacy rules explain missing validation');
  await app.runSource('source_refresh',[]);
  check(app.notice.kind==='success'&&text(root).includes('27')&&!text(root).includes('待校验'),'refresh renders validated count for legacy rules');
  ruleData.items=[{id:'cname',name:'CNAME',url:'https://rules.example/cname',https:true,enabled:true,format:'domains',validation:'validated',domains:245052,skipped:26,updated:1700000000}];
  await app.loadSources();
  check(text(root).includes('245,052')&&text(root).includes('已排除不支持的记录：26'),'source count and excluded malformed records stay distinct');
  ruleData.items[0]={...ruleData.items[0],format:'unknown',validation:'backend_only',domains:null,skipped:0};await app.loadSources();
  check(text(root).includes('格式未识别')&&text(root).includes('仅由后端处理；更新订阅可重新校验。')&&!text(root).includes('245,052'),'unsupported native format explains missing count without a fake total');
  reset({state:'configured_unverified'});await app.openRules();commands.length=0;
  await app.stageSource('source_add',['','One','https://one.example/list','domains']);
  await app.stageSource('source_add',['','Two','https://two.example/list','domains']);
  check(commands.length===0&&ruleData.items.length===0&&app.draft.items.length===2,'multiple selections stay local with no download RPC');
  check(find('az-draft-apply')&&!find('az-draft-apply').disabled&&find('az-source-refresh').disabled,'pending bar exposes one apply and prevents conflicting refresh');
  const key=app.draft.items[0]._key;
  await app.stageSource('source_toggle',[key,'https://one.example/list',false]);
  app.rulesOpen=false;app.paint();await app.stageRouting(true);
  check(commands.length===0&&find('az-routing').attrs['aria-checked']==='true'&&!state.policy.routing_enabled,'routing is staged without changing live state');
  check(!find('az-update').disabled,'overview reload can apply all pending choices together');
  await app.openRules();
  check(app.draft.items.length===2,'switching internal tabs preserves all pending choices');
  commands.length=0;await app.reloadCurrent();
  check(commands.filter(x=>x==='settings_apply').length===1&&!commands.includes('source_toggle')&&!commands.includes('routing_on'),'one typed batch applies all selections');
  check(app.draft===null&&app.notice.kind==='success'&&ruleData.items.length===2&&state.policy.routing_enabled,'only canonical completion clears pending changes');
  check(!JSON.stringify([...storage.values()]).includes('one.example'),'draft URLs are never persisted in browser storage');
  commands.length=0;await app.reloadCurrent();
  check(commands.filter(x=>x==='reload').length===1&&!commands.includes('source_refresh')&&!commands.includes('settings_apply'),'unchanged reload is a distinct typed operation without subscription refresh');
  check(app.notice.kind==='success'&&text(root).includes('未强制更新订阅'),'reload confirms its cache-only intent');
  commands.length=0;await app.stageSource('source_toggle',[ruleData.items[0].id,ruleData.items[0].url,true]);
  find('az-draft-discard').events.click();
  check(app.draft===null&&commands.length===0&&!ruleData.items[0].enabled,'discard makes no server calls and leaves active choices alone');
  await app.stageSource('source_toggle',[ruleData.items[0].id,ruleData.items[0].url,true]);
  rpcFailure=true;await app.applyDraft();
  check(app.draftCount()>0&&app.notice.kind==='error','rejected batch keeps every pending choice');
  rpcFailure=false;rpcStale=true;await app.applyDraft();
  check(app.draftCount()>0&&app.notice.kind==='error','successful receipt without desired config is not accepted');
  reset();await app.openRules();await app.stageSource('source_add',['','Temporary','https://temp.example/list','domains']);
  await app.stageSource('source_remove',[app.draft.items[0]._key,'https://temp.example/list']);
  check(app.draft===null&&!find('az-draft-apply'),'adding then removing an unapplied source cancels without a task');
  reset();jobSteps=[new Error('connection reset'),new Error('network reloading'),{ok:true,pending:false}];
  await app.runAction('enable');
  check(app.notice.kind==='success' && commands.filter(x=>x==='enable').length===1,'network reload retries receipt without resubmitting mutation');
  reset({state:'configured_unverified'});jobSteps=Array.from({length:16},()=>new Error('network unreachable'));
  await app.runPolicy('routing_on',[]);
  check(app.jobUncertain && storage.has('adzero.v0.8.'+sessionID+'.job'),'prolonged transport failure retains original task receipt');
  check(app.currentStatus.stale && find('az-toggle').disabled && find('az-routing').disabled && !find('az-status').disabled,'uncertain task blocks new writes but permits reconnect');
  await app.refreshStatus();
  check(app.notice.kind==='success' && commands.filter(x=>x==='routing_on').length===1 && !app.jobUncertain,'retry checks original routing task and canonical state only');
  reset({state:'configured_unverified'});
  jobSteps=[{ok:true,pending:true,progress:{stage:'downloading',elapsed:20,phase_elapsed:3}},()=>{
    check(text(root).includes('正在下载规则') && text(root).includes('20'),'server stage and elapsed time are visible during operation');
    check(text(root).includes('本阶段 3 秒'),'total task time is distinct from current stage time');
    return {ok:false,pending:false,message:'国内分类库校验失败'};
  }];
  await app.runPolicy('routing_on',[]);
  check(app.notice.kind==='error' && text(root).includes('国内分类库校验失败') && !storage.has('adzero.v0.8.'+sessionID+'.job'),'confirmed failure is distinct from temporary disconnection');
  reset({state:'inconsistent',managed:true,adapter:{plugin:'nailink',stage:'restarting',reload_pending:true}});
  check(text(root).includes('正在确认代理重载') && !text(root).includes('部分配置尚未确认，请关闭并恢复后再开启'),'pending reload has its own accurate overview state');
  app.sourcesData={...ruleData,pending:true};app.rulesOpen=true;app.paint();
  check(text(root).includes('请稍候重新检测，勿重复应用') && find('az-source-reload').disabled,'pending reload blocks duplicate apply without mislabeling rule format');
  app.draft={base:[],items:[{id:null,_key:'pending_1',_new:true,name:'Late',url:'https://late.example/rules',format:'domains',enabled:true}],routing_before:false,routing_enabled:false};
  ruleData.items=[{id:'new',name:'Late',url:'https://late.example/rules',format:'domains',enabled:true}];
  state={...state,state:'configured_unverified',adapter:{plugin:'nailink',stage:'configured_unverified',reload_pending:false}};
  await app.refreshStatus();
  check(!app.draft && app.notice.kind==='success' && !commands.includes('settings_apply') && !commands.includes('reload'),'late background completion clears matching pending draft without another mutation');
  reset({state:'configured_unverified'});
  jobSteps=[{ok:true,pending:true,progress:{stage:'confirming_proxy',elapsed:33}},()=>{
    check(text(root).includes('不会重复重载'),'late acknowledgement explains confirmation rather than resubmission');
    return {ok:true,pending:false};
  }];await app.runAction('reload');
  reset();await find('az-dns-open').events.click();
  check(find('az-dns-domestic')&&find('az-dns-foreign'),'resolver editor loads both editable groups');
  find('az-dns-domestic').events.input({target:{value:'119.29.29.29\n223.5.5.5'}});
  find('az-dns-foreign').events.input({target:{value:'8.8.8.8\n1.1.1.1'}});
  commands.length=0;await app.stageDNS();
  check(commands.length===0&&app.draft.dns.domestic.active==='119.29.29.29'&&app.draft.dns.foreign.active==='8.8.8.8','DNS edits stay local and first address is selected');
  await app.stageRouting(true);await app.stageSource('source_add',['','DNS batch','https://dnsbatch.example/list','domains']);
  check(commands.length===0&&app.draftCount()===3,'DNS routing and rules share the same pending batch');
  await app.applyDraft();
  check(commands.filter(x=>x==='settings_apply').length===1&&!app.draft&&ruleData.dns.foreign.active==='8.8.8.8','one batch persists DNS and canonical confirmation clears draft');
  reset();await find('az-dns-open').events.click();find('az-dns-foreign').events.input({target:{value:'https://dns.example/query'}});await app.stageDNS();
  check(!app.draft&&app.notice.kind==='error','invalid resolver text stays out of pending settings');
  reset();await app.openRules();ruleData.items=[{id:'local',url:'https://local.example/list',name:'Local',enabled:true,format:'domains'}];await app.loadSources();commands.length=0;
  await app.runSource('source_verify',[]);
  check(commands.filter(x=>x==='source_verify').length===1&&!commands.includes('source_refresh')&&!commands.includes('reload'),'manual validation is a distinct operation without refresh or reload');
  check(app.notice.kind==='success'&&text(root).includes('未下载订阅或重载网络'),'manual validation reports its actual local-only scope');
  reset();ruleData.dns.foreign.active='8.8.8.8';await find('az-dns-open').events.click();commands.length=0;await find('az-dns-default').events.click();
  check(commands.length===0&&app.draft.dns.foreign.active==='1.1.1.1'&&!state.policy.routing_enabled,'restore default DNS is staged without enabling routing or sending a mutation');
  console.log(`AdZero LuCI: ${assertions} UI regression assertions passed.`);
})().catch(err => { console.error(err); process.exitCode = 1; });
