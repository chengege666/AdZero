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
  if (args[0] === 'status') { if (statusPending) await new Promise(r => { resolveStatus = r; }); if (failStatus) throw new Error('status unreachable'); return { code: 0, stdout: JSON.stringify(state) }; }
  if (pending) await new Promise(r => { resolveAction = r; });
  if (failAction) return { code: 1, stderr: '<script>untrusted error</script>' };
  if (!staleResult) state.state = args[0] === 'disable' ? 'disabled' : 'configured_unverified';
  return { code: 0, stdout: 'ok' };
} };
let rpcFailure = false, rpcStale = false, lookup = {available:true,domain:'login.ads.example',match:'parent',rule:'ads.example',scope:'ads.example'};
const rpc = { declare: spec => async (...args) => {
  assert.equal(spec.object,'adzero'); commands.push(spec.method);
  if (rpcFailure) return {ok:false,message:'typed failure'};
  if (spec.method === 'lookup') return {ok:true,data:lookup};
  if (!rpcStale) {
    if (spec.method === 'allow') state.policy.allowed.push(args[1]);
    if (spec.method === 'revoke') state.policy.allowed = state.policy.allowed.filter(x => x !== args[1]);
    state.state = spec.method === 'pause' ? 'paused' : 'configured_unverified';
    state.policy.pause = spec.method === 'pause' ? {stage:'paused',remaining:args[0]} : null;
  }
  return {ok:true};
} };
const app = Function('view', 'fs', 'dom', '_', 'E', 'document', 'L', 'rpc', 'poll', source)(
  { extend: x => x }, api, { content: (target, children) => { target.children = children; } }, x => x, E, doc, { resource: x => '/luci-static/resources/' + x }, rpc, {add:()=>{},remove:()=>{}});
function reset(overrides = {}) {
  state = { state: 'disabled', managed: false, dns_mode_safe: true, resolver: 'dnsmasq.servers', client_dns_verified: false,
    policy:{allowed:[],pause:null}, force_dns: 'off', tls_download: 'strict', backend: { state: 'ready', domains: 66425, warnings: 1 }, adapter: { plugin: 'nailink', stage: 'configured_unverified' },
    compatibility: { platform: { distribution: 'OpenWrt', version: '25.12.5', cpu: 'aarch64', target: 'rockchip/armv8', package_manager: 'apk', declared_arch: 'aarch64_generic' },
      dns: { active_proxy_count: 1 }, plugins: ['nailink', 'passwall', 'passwall2', 'openclash', 'nikki'].map((id, i) => ({ id, installed: true, enabled: i === 0, runtime: i === 0 ? 'running' : 'unknown' })) }, ...overrides };
  failAction = failStatus = pending = staleResult = statusPending = rpcFailure = rpcStale = false; commands.length = 0;
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
  await app.runAction('enable'); assert.deepEqual(commands, ['enable', 'status']);
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
  rpcStale=true; await app.runPolicy('allow',['ads.example','ads.example']); check(app.notice.kind==='error','stale RPC success rejected');
  rpcStale=false; rpcFailure=true; await app.runPolicy('pause',[300]); check(app.notice.kind==='error' && state.state!=='paused','RPC failure is not optimistic pause');
  reset({state:'configured_unverified'}); app.domainInput=''; await app.lookupDomain(); check(!commands.length && text(root).includes('请输入'),'empty query validation');
  app.domainInput='ads.example'; rpcFailure=true; await app.lookupDomain(); check(text(root).includes('typed failure') && !find('az-allow'),'query failure cannot enable allow');
  reset({state:'paused',policy:{allowed:['ads.example'],pause:{remaining:0,error:'resume_failed'}}});
  check(text(root).includes('自动恢复未完成') && !find('az-resume').disabled,'failed automatic resume remains actionable');
  await app.runAction('disable'); check(state.state==='disabled','manual close cancels pause via canonical controller');
  console.log(`AdZero LuCI: ${assertions} UI regression assertions passed.`);
})().catch(err => { console.error(err); process.exitCode = 1; });
