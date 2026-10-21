/* Development fixture only: actual production view with native DOM and fake ctl. */
'use strict';
function E(tag, attrs = {}, children = []) {
  let el;
  if (tag.startsWith('<')) { const template = document.createElement('template'); template.innerHTML = tag; el = template.content.firstChild; }
  else el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null) continue;
    if (typeof value === 'function') el.addEventListener(key, value); else el.setAttribute(key, value);
  }
  for (const child of [children].flat(Infinity)) if (child != null) el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return el;
}
const baseline = {
  state: 'configured_unverified', managed: true, configured: true, backend_enabled: true,
  resolver: 'dnsmasq.servers', dns_mode_safe: true, force_dns: 'off', tls_download: 'strict', dnsmasq_port_hint: 'default', client_dns_verified: false,
  backend: { state: 'ready', domains: 66425, errors: 0, warnings: 1 }, adapter: { plugin: 'nailink', stage: 'configured_unverified', domains: 66425 },
  compatibility: { platform: { distribution: 'OpenWrt', version: '25.12.5', cpu: 'aarch64', target: 'rockchip/armv8', declared_arch: 'aarch64_generic', package_arch: 'aarch64', package_manager: 'apk' },
    plugins: ['nailink', 'passwall', 'passwall2', 'openclash'].map((id, i) => ({ id, installed: true, enabled: i === 0, runtime: i === 0 ? 'running' : 'unknown' })), dns: { active_proxy_count: 1 } }
};
let state = structuredClone(baseline), app, calls = 0;
const api = { exec: async (_program, args) => {
  if (args[0] === 'status') { if (state.state === 'error') throw new Error('模拟：连接暂时中断'); return { code: 0, stdout: JSON.stringify(state) }; }
  document.getElementById('calls').textContent = '操作次数：' + (++calls);
  await new Promise(resolve => setTimeout(resolve, 1600));
  if (document.getElementById('fail').checked) return { code: 1, stderr: '模拟错误：规则下载失败，原配置已恢复。' };
  state.state = args[0] === 'disable' ? 'disabled' : 'configured_unverified'; return { code: 0, stdout: 'ok' };
} };
function mount() { app.busy = app.notice = null; app.lastChecked = new Date(); document.getElementById('preview').replaceChildren(app.render(state)); }
document.getElementById('scenario').addEventListener('change', ev => {
  state = structuredClone(baseline);
  if (ev.target.value === 'off') state.state = 'disabled';
  if (ev.target.value === 'multi') { state.state = 'disabled'; state.compatibility.dns.active_proxy_count = 2; }
  if (ev.target.value === 'recovery') state.state = 'inconsistent';
  if (ev.target.value === 'error') { state.state = 'error'; state.error = '模拟：连接暂时中断'; }
  mount();
});
document.getElementById('appearance').addEventListener('change', ev => { document.documentElement.dataset.theme = ev.target.value; });
document.getElementById('sidebar').addEventListener('change', ev => { document.body.classList.toggle('with-sidebar', ev.target.checked); });
fetch('/luci-static/resources/view/adzero/overview.js').then(r => r.text()).then(source => {
  app = Function('view', 'fs', 'dom', '_', 'E', 'document', 'L', source)({ extend: x => x }, api,
    { content: (el, content) => el.replaceChildren(content) }, x => x, E, document, { resource: x => '/luci-static/resources/' + x }); mount();
});
