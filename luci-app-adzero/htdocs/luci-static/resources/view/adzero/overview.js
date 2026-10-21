'use strict';
'require view';
'require fs';
'require dom';
'require rpc';
'require poll';

var policyCalls = {};
[ ['enable', []], ['disable', []], ['refresh', []], ['lookup', ['domain']], ['allow', ['domain', 'scope']], ['revoke', ['domain', 'scope']], ['pause', ['seconds']], ['resume', []] ].forEach(function(method) {
	policyCalls[method[0]] = rpc.declare({ object: 'adzero', method: method[0], params: method[1] });
});
var sourceCalls = {};
[ ['source_list', []], ['source_add', ['catalog','name','url','format']], ['source_toggle', ['id','expected_url','enabled']], ['source_remove', ['id','expected_url']], ['source_refresh', []], ['job_status', ['job']] ].forEach(function(method) {
	sourceCalls[method[0]] = rpc.declare({object:'adzero',method:method[0],params:method[1]});
});
function sessionValue(kind, value) {
	try {
		var sid = typeof rpc.getSessionID === 'function' ? rpc.getSessionID() : '';
		if (!/^[a-f0-9]{32}$/.test(sid) || /^0+$/.test(sid) || typeof sessionStorage === 'undefined') return null;
		var key = 'adzero.v0.8.' + sid + '.' + kind;
		if (value === null) sessionStorage.removeItem(key);
		else if (value !== undefined) sessionStorage.setItem(key,JSON.stringify(value));
		else return JSON.parse(sessionStorage.getItem(key) || 'null');
	} catch (e) {} // Storage can be disabled; live state still works normally.
	return null;
}
function saveSnapshot(s) {
	// Presentation only. Never cache rule URLs, private tokens or permissions.
	var snapshot = {};
	['state','managed','configured','backend_enabled','dns_mode_safe','adguardhome_running','backend','adapter','client_dns_verified'].forEach(function(k) { snapshot[k]=s[k]; });
	snapshot.compatibility = {dns:{active_proxy_count:((s.compatibility || {}).dns || {}).active_proxy_count}};
	snapshot.policy = {pause:(s.policy || {}).pause || null};
	sessionValue('snapshot',{at:Date.now(),status:snapshot});
}
function readSnapshot() {
	var saved=sessionValue('snapshot');
	if (!saved || typeof saved.at !== 'number' || Date.now()-saved.at < 0 || Date.now()-saved.at > 300000 || !saved.status || typeof saved.status.state !== 'string') return null;
	return Object.assign({},saved.status,{stale:true,cached_at:saved.at});
}
function waitJob(reply) {
	if (!reply || !reply.ok) return Promise.reject(new Error(reply && reply.message || _('操作未完成，请重新检测。')));
	if (!reply.job) return Promise.resolve();
	var attempts=0;
	function check() {
		return sourceCalls.job_status(reply.job).then(function(result) {
			if (!result || !result.ok) throw new Error(result && result.message || _('任务结果未知，请重新检测。'));
			if (!result.pending) return;
			if (++attempts > 1200) throw new Error(_('后台任务仍可能执行，请重新检测后查看结果。'));
			return new Promise(function(resolve) { setTimeout(resolve,2000); }).then(check);
		});
	}
	return check();
}
function trackJob(reply,kind,action) {
	// Never persist domain scopes, custom URLs or private arguments in receipts.
	if (reply && reply.ok && !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(reply.job || '')) return Promise.reject(new Error(_('未收到有效任务回执，请重新检测。')));
	if (reply && reply.job) sessionValue('job',{job:reply.job,kind:kind,action:action});
	return waitJob(reply);
}

// Phosphor Icons (MIT), license: /usr/share/licenses/luci-app-adzero/.
var icons = {
	shield: 'M208,40H48A16,16,0,0,0,32,56v56c0,52.72,25.52,84.67,46.93,102.19,23.06,18.86,46,25.26,47,25.53a8,8,0,0,0,4.2,0c1-.27,23.91-6.67,47-25.53C198.48,196.67,224,164.72,224,112V56A16,16,0,0,0,208,40Zm0,72c0,37.07-13.66,67.16-40.6,89.42A129.3,129.3,0,0,1,128,223.62a128.25,128.25,0,0,1-38.92-21.81C61.82,179.51,48,149.3,48,112l0-56,160,0ZM82.34,141.66a8,8,0,0,1,11.32-11.32L112,148.69l50.34-50.35a8,8,0,0,1,11.32,11.32l-56,56a8,8,0,0,1-11.32,0Z',
	refresh: 'M224,48V96a8,8,0,0,1-8,8H168a8,8,0,0,1,0-16h28.69L182.06,73.37a79.56,79.56,0,0,0-56.13-23.43h-.45A79.52,79.52,0,0,0,69.59,72.71,8,8,0,0,1,58.41,61.27a96,96,0,0,1,135,.79L208,76.69V48a8,8,0,0,1,16,0ZM186.41,183.29a80,80,0,0,1-112.47-.66L59.31,168H88a8,8,0,0,0,0-16H40a8,8,0,0,0-8,8v48a8,8,0,0,0,16,0V179.31l14.63,14.63A95.43,95.43,0,0,0,130,222.06h.53a95.36,95.36,0,0,0,67.07-27.33,8,8,0,0,0-11.18-11.44Z',
	settings: 'M40,88H73a32,32,0,0,0,62,0h81a8,8,0,0,0,0-16H135a32,32,0,0,0-62,0H40a8,8,0,0,0,0,16Zm64-24A16,16,0,1,1,88,80,16,16,0,0,1,104,64ZM216,168H199a32,32,0,0,0-62,0H40a8,8,0,0,0,0,16h97a32,32,0,0,0,62,0h17a8,8,0,0,0,0-16Zm-48,24a16,16,0,1,1,16-16A16,16,0,0,1,168,192Z',
	check: 'M229.66,77.66l-128,128a8,8,0,0,1-11.32,0l-56-56a8,8,0,0,1,11.32-11.32L96,188.69,218.34,66.34a8,8,0,0,1,11.32,11.32Z',
	info: 'M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24Zm0,192a88,88,0,1,1,88-88A88.1,88.1,0,0,1,128,216Zm16-40a8,8,0,0,1-8,8,16,16,0,0,1-16-16V128a8,8,0,0,1,0-16,16,16,0,0,1,16,16v40A8,8,0,0,1,144,176ZM112,84a12,12,0,1,1,12,12A12,12,0,0,1,112,84Z'
};
var names = { nailink: 'NaiLink / daed', passwall: 'PassWall', passwall2: 'PassWall 2', openclash: 'OpenClash', nikki: 'Nikki' };
function el(tag, attrs, children) {
	// Native LuCI stringifies null inside arrays and treats scalar strings as
	// HTML. Always give it a flat, non-null array so dynamic strings are text.
	var safe = [];
	function append(value) {
		if (Array.isArray(value)) value.forEach(append);
		else if (value != null && value !== false) safe.push(value);
	}
	append(children);
	return E(tag, attrs || {}, safe);
}
function icon(name) {
	// Static local paths only. Server text is always inserted as text nodes.
	return el('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><path d="' + icons[name] + '"/></svg>',
		{ 'class': 'az-icon', 'aria-hidden': 'true', 'focusable': 'false', 'width': '20', 'height': '20' });
}
function getStatus() {
	return fs.exec('/usr/libexec/adzero/ctl', [ 'status' ]).then(function(result) {
		if (Number(result.code) !== 0) throw new Error(result.stderr || _('无法读取 AdZero 状态'));
		var status = JSON.parse(result.stdout);
		if (!status || typeof status.state !== 'string') throw new Error(_('返回的状态数据无法识别'));
		saveSnapshot(status);
		return status;
	});
}
function flags(s) {
	var enabled = s.state === 'configured_unverified';
	return { enabled: enabled, paused: s.state === 'paused', canDisable: !s.stale && (enabled || s.state === 'paused' || (s.state === 'inconsistent' && s.managed === true)),
		canEnable: !s.stale && s.state === 'disabled' && s.dns_mode_safe === true && !s.adguardhome_running &&
			!(s.compatibility && s.compatibility.dns && s.compatibility.dns.active_proxy_count > 1) };
}
function pill(text, tone) { return el('span', { 'class': 'az-pill az-' + (tone || 'neutral') }, text); }
function number(value) { return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? new Intl.NumberFormat().format(value) : '—'; }
function step(n, title, description, done) {
	return el('li', { 'class': 'az-step' + (done ? ' is-done' : '') }, [
		el('span', { 'class': 'az-step-mark', 'aria-hidden': 'true' }, done ? icon('check') : String(n)),
		el('div', {}, [ el('strong', {}, title), el('p', {}, description) ]) ]);
}
return view.extend({
	busy: null, currentStatus: null, lastChecked: null, notice: null, domainInput: '', domainResult: null, pauseSeconds: 300,
	load: function() {
		// Render first. A slow RPC must not hold LuCI's whole view behind a spinner.
		return Promise.resolve(readSnapshot() || { state: 'loading' });
	},
	renderPanel: function(s) {
		var self = this; self.currentStatus = s;
		var f = flags(s), inv = s.compatibility || {}, dns = inv.dns || {};
		var adapter = s.adapter || {}, backend = s.backend || {}, busy = self.busy, locked = busy || s.stale, loading = s.state === 'loading';
		var active = names[adapter.plugin] || (adapter.plugin === 'none' ? _('路由器 DNS') : _('接入待确认'));
		var synced = f.enabled && adapter.stage === 'configured_unverified' && adapter.plugin && adapter.plugin !== 'none';
		var ready = f.enabled && backend.state === 'ready', verified = s.client_dns_verified === true;
		var checked = self.lastChecked ? new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(self.lastChecked) : '—';
		var pause = (s.policy || {}).pause || {}, allowed = (s.policy || {}).allowed || [];
		var titles = { configured_unverified: _('广告过滤已开启'), disabled: _('广告过滤未开启'), paused: _('保护已临时暂停'),
			inconsistent: _('配置需要检查'), external_owner: _('当前由其他服务管理'),
			unavailable: _('过滤组件尚未就绪'), error: _('暂时无法读取状态'), loading: _('正在读取运行状态…') };
		var descriptions = { configured_unverified: _('规则已载入，当前接入配置已完成。'), disabled: _('开启后自动匹配当前网络，关闭时恢复原有设置。'),
			paused: pause.error ? _('自动恢复未完成，当前仍暂停。请尝试立即恢复，或关闭并恢复原设置。') : pause.remaining > 0 ? _('约 ') + Math.ceil(pause.remaining / 60) + _(' 分钟后自动恢复；重启路由器也会尝试恢复。') : _('暂停已到期，正在等待后台恢复保护。'),
			inconsistent: _('部分配置尚未确认，请关闭并恢复后再开启。'), external_owner: _('请先在原服务中关闭过滤后端，再启用 AdZero。'),
			unavailable: _('请检查插件依赖是否完整，然后重新检测。'), error: _('连接暂时中断，请重新检测后再操作。'), loading: _('页面已就绪，正在读取后端与代理状态。') };
		var blocker = s.adguardhome_running ? _('AdGuard Home 正在运行，请先关闭对应服务。') : dns.active_proxy_count > 1 ? _('多个代理同时启用，请保留一个正在使用的代理后重新检测。') :
			s.state === 'disabled' && s.dns_mode_safe !== true ? _('当前 DNS 模式不支持自动启用，请检查过滤后端设置。') : null;
		var toggle = f.canDisable && !f.enabled && !f.paused ? el('button', { id: 'az-toggle', 'class': 'az-button az-button-danger', type: 'button',
			'data-action': 'disable', disabled: locked ? true : null, click: function() { return self.runAction('disable'); } }, _('关闭并恢复')) : el('button', {
			id: 'az-toggle', 'class': 'az-toggle' + (f.enabled ? ' is-on' : ''), type: 'button', role: 'switch',
			'aria-label': _('广告过滤'), 'aria-checked': f.enabled ? 'true' : 'false', 'aria-describedby': 'az-operation-note',
			'data-action': f.paused ? 'resume' : f.enabled ? 'disable' : 'enable', disabled: locked || (!f.canEnable && !f.canDisable) ? true : null,
			click: function() { return f.paused ? self.runPolicy('resume', []) : self.runAction(f.enabled ? 'disable' : 'enable'); }
		}, el('span', { 'class': 'az-toggle-track', 'aria-hidden': 'true' }, el('span', { 'class': 'az-toggle-thumb' })));
		var nodes = [ el('div', { 'class': 'az-header' }, [
			el('div', { 'class': 'az-brand' }, [ el('span', { 'class': 'az-brand-mark', 'aria-hidden': 'true' }, icon('shield')),
				el('div', {}, [ el('h2', { translate: 'no' }, 'AdZero'), el('p', {}, _('运行概览')) ]) ]),
			el('div', { 'class': 'az-header-actions' }, [ el('span', { 'class': 'az-last-checked' }, s.stale ? (self.busy==='status' ? _('上次概览 · 后台核对') : _('上次概览 · 待重新检测')) : self.lastChecked ? _('刚刚检测于 ') + checked : _('正在连接路由器')),
				el('button', { id: 'az-status', type: 'button', 'class': 'az-button az-button-quiet', 'data-action': 'status', disabled: busy ? true : null,
					click: function() { return self.refreshStatus(); } }, [ icon('refresh'), busy === 'status' ? _('检测中…') : _('重新检测') ]) ]) ]) ];
		nodes.push(el('nav', { 'class':'az-tabs', 'aria-label':_('AdZero 页面') }, [
			el('button',{type:'button','class':!self.rulesOpen?'is-selected':'','aria-current':!self.rulesOpen?'page':null,click:function(){self.rulesOpen=false;self.paint();}},_('运行概览')),
			el('button',{type:'button','class':self.rulesOpen?'is-selected':'','aria-current':self.rulesOpen?'page':null,click:function(){return self.openRules();}},_('过滤规则')) ]));
		if (s.stale) nodes.push(el('p',{'class':'az-snapshot-hint',role:'status'},_('上次读取的概览，正在后台核对；取得新状态前暂停操作。')));
		if (self.notice) nodes.push(el('div', { 'class': 'az-notice az-notice-' + self.notice.kind, role: self.notice.kind === 'error' ? 'alert' : 'status' }, [
			icon(self.notice.kind === 'error' ? 'info' : 'check'), el('div', {}, [ el('strong', {}, self.notice.text),
				self.notice.detail ? el('details', { 'class': 'az-error-details' }, [ el('summary', {}, _('查看错误信息')), el('pre', {}, self.notice.detail) ]) : null ]) ]));
		if (busy && !loading && !(s.stale && busy === 'status')) nodes.push(el('div', { 'class': 'az-working', role: 'status', 'aria-live': 'polite' }, [ el('span', { 'class': 'az-spinner', 'aria-hidden': 'true' }),
			busy === 'rules' ? _('正在下载、校验并应用规则；离开页面后任务仍会继续。') : busy === 'enable' ? _('正在开启过滤…') : busy === 'disable' ? _('正在关闭并恢复…') : busy === 'refresh' ? _('正在更新并同步规则…') : busy === 'lookup' ? _('正在查询当前规则…') : busy === 'allow' || busy === 'revoke' ? _('正在应用放行名单并同步代理…') : busy === 'pause' ? _('正在暂停保护…') : busy === 'resume' ? _('正在恢复保护…') : _('正在检测状态…') ]));
		if (self.rulesOpen) { nodes.push(self.renderRules(s)); return el('div',{'class':'az-app'},nodes); }
		nodes.push(el('section', { 'class': 'az-card az-hero' + (f.enabled ? ' is-on' : '') + (loading ? ' is-loading' : ''), 'aria-busy': loading ? 'true' : 'false' }, [
			el('div', { 'class': 'az-hero-main' }, [ el('div', { 'class': 'az-hero-heading' }, [ icon('shield'),
				el('h3', { 'class': 'az-hero-title' }, titles[s.state] || _('状态暂未确认')),
				pill(s.stale ? _('上次状态') : loading ? _('检测中') : f.enabled ? _('已开启') : f.paused ? _('已暂停') : s.state === 'disabled' ? _('已关闭') : _('需要留意'), f.enabled ? 'positive' : s.state === 'disabled' || loading ? 'neutral' : 'attention') ]),
				el('p', { 'class': 'az-hero-copy' }, descriptions[s.state] || _('请重新检测当前状态。')), blocker ? el('p', { 'class': 'az-inline-warning' }, [ icon('info'), blocker ]) : null ]),
			el('div', { 'class': 'az-switch-control' }, [ el('span', {}, loading ? _('等待状态确认') : _('保护开关')), toggle ]) ]));
		if (f.enabled || f.paused) nodes.push(el('div', { 'class': 'az-pause-bar' }, f.paused ? [
			el('span', {}, _('暂时关闭过滤，保留个人放行名单。')),
			el('div', { 'class': 'az-action-row' }, [ el('button', { id: 'az-resume', type: 'button', 'class': 'az-button az-button-primary', disabled: locked ? true : null, click: function() { return self.runPolicy('resume', []); } }, _('立即恢复')),
				el('button', { type: 'button', 'class': 'az-button az-button-quiet', disabled: locked ? true : null, click: function() { return self.runAction('disable'); } }, _('保持关闭')) ])
		] : [ el('span', {}, _('网页或 App 异常？先暂停对比，或在下方查询域名。')),
			el('div', { 'class': 'az-action-row' }, [ el('label', { 'for': 'az-pause-duration', 'class': 'az-sr-only' }, _('暂停时长')),
				el('select', { id: 'az-pause-duration', disabled: locked ? true : null, change: function(e) { self.pauseSeconds = Number(e.target.value); } }, [300,900,1800].map(function(seconds) { return el('option', { value: seconds, selected: self.pauseSeconds === seconds ? true : null }, seconds / 60 + _(' 分钟')); })),
				el('button', { id: 'az-pause', type: 'button', 'class': 'az-button az-button-quiet', disabled: locked ? true : null, click: function() { return self.runPolicy('pause', [self.pauseSeconds]); } }, _('临时暂停')) ]) ]));
		nodes.push(el('div', { 'class': 'az-stats-grid', 'aria-busy': loading ? 'true' : 'false' }, [
			el('section', { 'class': 'az-card az-stat' }, [ el('div', { 'class': 'az-stat-heading' }, [ el('span', {}, _('规则域名')), icon('settings') ]),
				el('strong', { 'class': 'az-number' + (loading ? ' az-placeholder' : '') }, number(ready ? backend.domains : null)), el('p', {}, ready ? _('当前已加载的有效域名') : loading ? _('正在读取规则信息') : _('开启后自动载入')) ]),
			el('section', { 'class': 'az-card az-stat' }, [ el('div', { 'class': 'az-stat-heading' }, [ el('span', {}, _('当前接入')), icon('shield') ]),
				el('strong', { 'class': 'az-stat-value', translate: 'no' }, loading ? '—' : f.enabled ? active : _('自动匹配')), el('p', {}, synced ? _('代理规则已同步') : f.enabled && adapter.plugin === 'none' ? _('使用路由器 DNS') : f.enabled ? _('接入状态待确认') : _('开启时自动识别当前代理')) ]),
			el('section', { 'class': 'az-card az-stat' }, [ el('div', { 'class': 'az-stat-heading' }, [ el('span', {}, _('终端验证')), icon('info') ]),
				el('strong', { 'class': 'az-stat-value az-verification' }, loading ? '—' : verified ? _('已验证') : _('待验证')), el('p', {}, verified ? _('已有实际查询验证记录') : _('需在手机或电脑上确认效果')) ]) ]));
		nodes.push(el('section', { 'class': 'az-card az-domain-card' }, [
			el('div', { 'class': 'az-section-heading' }, [el('h3', {}, _('域名查询与放行')), pill(s.stale ? _('待核对') : allowed.length + _(' 项放行'))]),
			el('p', { 'class': 'az-card-copy', id: 'az-domain-help' }, _('检查域名是否命中 AdZero 当前规则，误拦截时可放行。支持粘贴网址。')),
			el('label', { 'for': 'az-domain', 'class': 'az-sr-only' }, _('域名或网址')),
			el('div', { 'class': 'az-domain-form' }, [ el('input', { id: 'az-domain', type: 'text', value: self.domainInput, placeholder: 'example.com 或 https://example.com', maxlength: 2048,
				'autocomplete': 'off', 'autocapitalize': 'none', 'spellcheck': 'false', 'aria-describedby': 'az-domain-help', disabled: locked || !f.enabled ? true : null,
				input: function(e) { self.domainInput = e.target.value; self.domainResult = null; var result = document.getElementById('az-domain-result'); if (result) dom.content(result, []); },
				keydown: function(e) { if (e.key === 'Enter') { e.preventDefault(); self.lookupDomain(); } } }),
				el('button', { id: 'az-lookup', type: 'button', 'class': 'az-button az-button-primary', disabled: locked || !f.enabled ? true : null, click: function() { return self.lookupDomain(); } }, _('查询域名')) ]),
			!f.enabled ? el('p', { 'class': 'az-card-copy' }, f.paused ? _('恢复保护后即可查询或修改放行名单。') : _('开启保护并载入规则后即可查询。')) : null,
			el('div', { id: 'az-domain-result', 'aria-live': 'polite' }, self.renderLookup()),
			allowed.length ? el('details', { 'class': 'az-allow-list' }, [ el('summary', {}, _('已放行 ') + allowed.length + _(' 项 · 管理名单')),
				el('ul', {}, allowed.map(function(name) { return el('li', {}, [ el('div', {}, [el('strong', { translate: 'no' }, name), el('small', {}, _('包含该域名及其子域'))]),
					el('button', { type: 'button', 'class': 'az-button az-button-quiet', 'aria-label': _('撤销放行 ') + name, disabled: locked || !f.enabled ? true : null,
						click: function() { return self.runPolicy('revoke', [name,name]); } }, _('撤销放行')) ]); })) ]) : null,
			el('p', { 'class': 'az-operation-note' }, _('放行仅移除 AdZero 的拦截，其他插件的独立规则仍可能生效。应用或撤销需重新处理规则，可能短暂重载 DNS 或代理。')) ]));
		nodes.push(el('div', { 'class': 'az-work-grid' }, [
			el('section', { 'class': 'az-card az-rules' }, [ el('div', { 'class': 'az-section-heading' }, [ el('h3', {}, _('过滤规则')), pill(ready ? _('已载入') : _('等待开启'), ready ? 'positive' : 'neutral') ]),
				el('p', { 'class': 'az-card-copy' }, _('更新当前启用的域名列表，并自动同步到当前接入。')),
				el('div', { 'class': 'az-rule-action' }, [ el('span', {}, _('已有自定义规则时优先沿用。')),
					el('div',{'class':'az-action-row'},[el('button',{type:'button','class':'az-button az-button-quiet',click:function(){return self.openRules();}},_('管理规则')),
					el('button', { id: 'az-update', 'class': 'az-button az-button-primary', type: 'button', 'data-action': 'refresh', disabled: locked || !f.enabled ? true : null,
						click: function() { return self.runSource('source_refresh',[]); } }, [ icon('refresh'), _('更新规则') ]) ]) ]),
				el('p', { id: 'az-operation-note', 'class': 'az-operation-note' }, _('开关与更新可能短暂重载 DNS 或当前代理；关闭后恢复原有设置。')) ]),
			el('section', { 'class': 'az-card az-progress' }, [ el('div', { 'class': 'az-section-heading' }, [ el('h3', {}, _('接入检查')), pill(verified ? _('终端已验证') : _('终端待验证')) ]),
				el('ol', { 'class': 'az-steps' }, [ step(1, _('载入规则'), ready ? _('后端运行正常') : _('开启后准备'), ready),
					step(2, _('网络接入'), synced ? _('代理已同步') : f.enabled && adapter.plugin === 'none' ? _('DNS 已配置') : _('自动识别代理'), !!(f.enabled && (synced || adapter.plugin === 'none'))),
					step(3, _('终端效果'), verified ? _('查询已验证') : _('尚待实际验证'), verified) ]),
				el('p', { 'class': 'az-progress-note' }, _('配置完成不等于所有终端的流量都已过滤。')) ]) ]));
		if (backend.errors > 0) nodes.push(el('p', { 'class': 'az-inline-warning', role: 'alert' }, _('过滤后端报告错误，请检查服务日志后重新检测。')));
		if (!s.compatibility && !loading && s.state !== 'error') nodes.push(el('p', { 'class': 'az-inline-warning', role: 'alert' }, _('网络环境检测未完成，请检查插件安装文件后重新检测。')));
		nodes.push(el('footer', { 'class': 'az-footer' }, [ icon('info'), _('DNS 过滤无法覆盖同域视频广告、网页占位或绕过路由器的请求。') ]));
		if (s.state === 'error' && s.error) nodes.push(el('details', { 'class': 'az-error-details az-load-error' }, [ el('summary', {}, _('查看连接错误')), el('pre', {}, s.error) ]));
		return el('div', { 'class': 'az-app' }, nodes);
	},
	renderRules: function(s) {
		var self=this,data=self.sourcesData,items=data ? data.items || [] : [],catalog=data ? data.catalog || [] : [];
		var enabled=flags(s).enabled, editable=!!data && !self.sourcesError && !self.busy && !self.sourcesLoading && !s.stale && !data.pending && (enabled || s.state==='disabled' && !s.managed);
		var form=self.customSource || (self.customSource={name:'',url:'',format:'domains'});
		function updateField(key) { return function(e) { form[key]=e.target.value; }; }
		function date(value) { return value ? new Intl.DateTimeFormat(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(value*1000)) : _('尚无记录'); }
		return el('div',{'class':'az-rules-page'},[
			el('section',{'class':'az-card az-source-header'},[
				el('div',{},[el('h3',{},_('我的过滤规则')),el('p',{'class':'az-card-copy'},_('按需添加订阅，选择要启用的列表。添加和开关会保留，保护总开关不变。'))]),
				el('button',{id:'az-source-refresh',type:'button','class':'az-button az-button-primary',disabled:!editable || !items.length ? true:null,click:function(){return self.runSource('source_refresh',[]);}},[icon('refresh'),_('更新已启用规则')]) ]),
			self.sourcesError ? el('div',{'class':'az-notice az-notice-error',role:'alert'},[el('span',{},self.sourcesError),el('button',{type:'button','class':'az-button az-button-quiet',disabled:self.busy?true:null,click:function(){return self.loadSources();}},_('重新读取'))]) : null,
			!data ? el('p',{'class':'az-card-copy',role:'status'},_('正在读取规则列表…')) : null,
			!editable && !self.busy ? el('p',{'class':'az-inline-warning'},s.stale ? _('正在核对状态，请稍候。') : self.sourcesLoading ? _('正在核对规则列表，请稍候。') : s.state==='paused' ? _('请先恢复保护或保持关闭，再调整规则。') : _('当前状态不支持更改规则，请先完成恢复或重新检测。')) : null,
			el('section',{'class':'az-card az-source-list'},items.length ? [
				el('div',{'class':'az-source-table-heading','aria-hidden':'true'},[el('span',{},_('规则名称 / 地址')),el('span',{},_('校验数量 / 最近更新')),el('span',{},_('操作'))]),
				items.map(function(item) { return el('div',{'class':'az-source-row'},[
					el('div',{'class':'az-source-identity'},[el('strong',{},item.name),el('span',{'class':'az-source-url',translate:'no'},item.url),el('small',{},item.format==='unknown'?_('后端已有格式'):item.format)]),
					el('div',{'class':'az-source-metadata'},[el('strong',{},number(item.domains)),el('span',{},date(item.updated))]),
					el('div',{'class':'az-source-actions'},[
						el('button',{type:'button','class':'az-toggle'+(item.enabled?' is-on':''),role:'switch','aria-checked':item.enabled?'true':'false','aria-label':_('启用规则 ')+item.name,disabled:!editable || !item.https && !item.enabled?true:null,
							click:function(){return self.runSource('source_toggle',[item.id,item.url,!item.enabled]);}},el('span',{'class':'az-toggle-track','aria-hidden':'true'},el('span',{'class':'az-toggle-thumb'}))),
						el('button',{type:'button','class':'az-button az-button-quiet',disabled:!editable?true:null,click:function(){self.removeSource=item.id;self.paint();}},_('删除')) ]),
					self.removeSource===item.id ? el('div',{'class':'az-source-confirm',role:'group','aria-label':_('确认删除规则')},[el('span',{},_('删除此订阅？个人放行名单会保留。')),
						el('button',{type:'button','class':'az-button az-button-danger',disabled:!editable?true:null,click:function(){return self.runSource('source_remove',[item.id,item.url]);}},_('确认删除')),
						el('button',{type:'button','class':'az-button az-button-quiet',click:function(){self.removeSource=null;self.paint();}},_('取消'))]) : null ]); })
			] : !data ? el('div',{'class':'az-source-empty'},_('规则列表尚未就绪。')) : el('div',{'class':'az-source-empty'},[el('strong',{},_('还没有添加订阅')),el('p',{},_('从下方规则库选择，或添加自己的 HTTPS 订阅地址。'))])),
			el('p',{'class':'az-source-footnote'},_('数量为各列表下载校验后的域名数，可能互相重叠；合并去重及个人放行后，以概览的有效域名数为准。关闭保护时保留选择。')),
			el('section',{'class':'az-card az-custom-source'},[
				el('div',{'class':'az-section-heading'},[el('h3',{},_('添加自定义订阅')),pill(_('HTTPS'))]),
				el('p',{'class':'az-card-copy'},_('支持域名、Hosts 和 ||domain^ 基础 DNS 规则。网页元素、正则、修饰符及高级例外不能导入。')),
				el('div',{'class':'az-custom-grid'},[
					el('label',{},[el('span',{},_('名称')),el('input',{id:'az-source-name',type:'text',maxlength:100,value:form.name,placeholder:_('例如：我的广告列表'),disabled:!editable?true:null,input:updateField('name')})]),
					el('label',{},[el('span',{},_('订阅地址')),el('input',{id:'az-source-url',type:'url',maxlength:2048,value:form.url,placeholder:'https://example.com/domains.txt',disabled:!editable?true:null,input:updateField('url'),'autocomplete':'off'})]),
					el('label',{},[el('span',{},_('文件格式')),el('select',{id:'az-source-format',disabled:!editable?true:null,change:updateField('format')},[['domains',_('域名列表')],['hosts','Hosts'],['adblock',_('基础 DNS Adblock')]].map(function(option){return el('option',{value:option[0],selected:form.format===option[0]?true:null},option[1]);}))]) ]),
				el('div',{'class':'az-custom-submit'},[el('span',{},_('先校验再应用。下载或同步失败时尝试恢复原配置。')),
					el('button',{id:'az-source-add',type:'button','class':'az-button az-button-primary',disabled:!editable?true:null,click:function(){return self.runSource('source_add',['',form.name.trim(),form.url.trim(),form.format]);}},_('添加并启用'))]) ]),
			el('div',{'class':'az-library-title'},[el('h3',{},_('规则库')),el('span',{},_('按需添加；同系列列表通常选一项即可，叠加不一定更好。'))]),
			el('div',{'class':'az-library-grid'},catalog.map(function(rule){var added=items.some(function(i){return i.url===rule.url;});return el('section',{'class':'az-card az-library-item'},[
				el('div',{'class':'az-section-heading'},[el('h3',{},rule.name),pill(rule.group)]),el('p',{},rule.description),
				el('div',{'class':'az-library-footer'},[el('a',{href:rule.home,target:'_blank',rel:'noopener noreferrer'},_('项目主页')),
					el('button',{type:'button','class':'az-button '+(added?'az-button-quiet':'az-button-primary'),disabled:added || !editable?true:null,click:function(){return self.runSource('source_add',[rule.id,'','','domains']);}},added?_('已添加'):_('添加规则'))]) ]);})),
			data && data.last ? el('p',{'class':'az-source-footnote'},_('最近完成：')+date(data.last.at)+(enabled?_(' · 当前接入已同步。'):_(' · 开启保护后应用所选规则。'))) : null ]);
	},
	openRules: function() {
		this.rulesOpen=true;this.paint();
		return this.loadSources();
	},
	loadSources: function() {
		var self=this;
		self.sourcesLoading=true;self.paint();
		return sourceCalls.source_list().then(function(reply){if (!reply || !reply.ok || !reply.data || !Array.isArray(reply.data.items)) throw new Error(reply && reply.message || _('无法读取规则列表。'));self.sourcesData=reply.data;self.sourcesError=null;})
			.catch(function(e){self.sourcesError=String(e.message || e);}).then(function(){self.sourcesLoading=false;self.paint();});
	},
	continueSourceJob: function(reply) {
		var self=this,failure=null;self.busy='rules';self.notice=null;self.paint();
		return trackJob(reply,'source',null).catch(function(e){failure=String(e.message || e);}).then(getStatus).then(function(s){
			self.currentStatus=s;self.lastChecked=new Date();self.domainResult=null;self.removeSource=null;
			var healthy=s.state==='disabled' || s.state==='configured_unverified';
			self.notice=failure || !healthy ? {kind:'error',text:_('规则未确认应用，已重新读取当前状态。'),detail:failure || _('请先处理恢复记录。')} :
				{kind:'success',text:s.state==='disabled'?_('规则选择已保存，开启保护后应用。'):_('规则已应用并同步到当前接入。')};
		}).catch(function(e){self.currentStatus={state:'error',error:String(e)};self.notice={kind:'error',text:_('规则任务结果暂时无法确认，请重新检测。')};})
			.then(function(){sessionValue('job',null);self.busy=null;return self.loadSources();}).then(function(){
				if (self.sourcesError) { self.notice={kind:'error',text:_('任务已结束，但规则列表暂时无法核对，请重新读取。')};self.paint(); }
			});
	},
	runSource: function(method,args) {
		var self=this,s=self.currentStatus || {};
		if (self.busy || s.stale || !(flags(s).enabled || s.state==='disabled' && !s.managed)) return Promise.resolve();
		if (method==='source_add' && !args[0] && (!args[1] || !/^https:\/\//i.test(args[2]))) {self.notice={kind:'error',text:_('请填写名称和 HTTPS 订阅地址。')};self.paint('az-source-name');return Promise.resolve();}
		if (['source_add','source_toggle','source_remove','source_refresh'].indexOf(method)<0) return Promise.resolve();
		self.busy='rules';self.notice=null;self.paint();
		return sourceCalls[method].apply(null,args).then(function(reply){return self.continueSourceJob(reply);}).then(function(){
			if (!self.notice || self.notice.kind!=='success') return;
			var items=(self.sourcesData || {}).items || [], matches=true;
			if (method==='source_add') matches=items.some(function(i){return args[0] ? i.catalog_id===args[0] : i.url===String(args[2]).replace(/^(https:\/\/[^/?]+)$/,'$1/');});
			if (method==='source_toggle') matches=items.some(function(i){return i.id===args[0] && i.url===args[1] && i.enabled===args[2];});
			if (method==='source_remove') matches=!items.some(function(i){return i.id===args[0];});
			if (!matches || self.sourcesError) self.notice={kind:'error',text:_('任务已结束，但规则选择尚未核对成功。请重新读取列表。')};
			else if (method==='source_add' && !args[0]) self.customSource={name:'',url:'',format:'domains'};
			self.paint();
		})
			.catch(function(e){self.busy=null;self.notice={kind:'error',text:_('规则操作未完成。'),detail:String(e.message || e)};self.paint();});
	},
	renderLookup: function() {
		var self = this, r = self.domainResult;
		if (!r) return [];
		if (r.error) return el('p', { 'class': 'az-inline-warning', role: 'alert' }, r.error);
		var hit = r.match === 'exact' || r.match === 'parent';
		return el('div', { 'class': 'az-lookup-result' }, [
			el('div', {}, [ el('strong', {}, r.match === 'allowed' ? _('已在个人放行名单中') : hit ? _('命中 AdZero 过滤规则') : _('未命中当前规则')),
				el('p', { translate: 'no' }, r.domain), hit ? el('p', {}, [ _('命中规则：'), el('strong', { translate: 'no' }, r.rule) ]) : null,
				hit ? el('p', { 'class': 'az-scope-note' }, [_('将放行 '), el('strong', { translate: 'no' }, r.scope), _(' 及其所有子域。')]) : el('p', {}, _('这是当前规则匹配结果，不能代替终端 DNS 实测。')) ]),
			hit ? el('button', { id: 'az-allow', type: 'button', 'class': 'az-button az-button-primary', disabled: self.busy ? true : null,
				click: function() { return self.runPolicy('allow', [r.domain,r.scope]); } }, _('放行此范围')) : null ]);
	},
	lookupDomain: function() {
		var self = this;
		if (self.busy || (self.currentStatus || {}).stale || !flags(self.currentStatus || {}).enabled) return Promise.resolve();
		var input = (self.domainInput || '').trim();
		if (!input) { self.domainResult = {error:_('请输入要查询的域名或网址。')}; self.paint('az-domain'); return Promise.resolve(); }
		self.busy = 'lookup'; self.notice = null; self.domainResult = null; self.paint();
		return policyCalls.lookup(input).then(function(result) {
			if (!result || !result.ok || !result.data || !result.data.available) throw new Error(result && result.message || _('当前规则无法查询，请重新检测。'));
			self.domainResult = result.data;
		}).catch(function(err) { self.domainResult = {error:String(err.message || err)}; })
			.then(function() { self.busy = null; self.paint('az-domain'); });
	},
	runPolicy: function(action, args, receipt) {
		var self = this, f = flags(self.currentStatus || {});
		if (['allow','revoke','pause','resume'].indexOf(action)<0 || self.busy || !receipt && ((self.currentStatus || {}).stale || !((action === 'resume' && f.paused) || (['allow','revoke','pause'].indexOf(action) >= 0 && f.enabled)))) return Promise.resolve();
		self.busy = action; self.notice = null; self.paint();
		var failure;
		return (receipt ? Promise.resolve(receipt) : policyCalls[action].apply(null,args)).then(function(result) {
			return trackJob(result,'policy',action);
		}).catch(function(err) { failure = String(err.message || err); }).then(getStatus).then(function(s) {
			self.currentStatus = s; self.lastChecked = new Date(); self.domainResult = null;
			var allowed = (s.policy || {}).allowed || [], expected = action === 'pause' ? s.state === 'paused' : s.state === 'configured_unverified';
			if (action === 'allow' && !receipt) expected = expected && allowed.indexOf(args[1]) >= 0;
			if (action === 'revoke' && !receipt) expected = expected && allowed.indexOf(args[1]) < 0;
			self.notice = failure || !expected ? {kind:'error',text:_('操作未确认完成，已重新读取当前状态。'),detail:failure || _('请检查当前状态后重试。')} :
				{kind:'success',text: action === 'pause' ? _('保护已暂停，到期后自动尝试恢复。') : action === 'resume' ? _('保护已恢复。') : action === 'allow' ? _('放行名单已应用，并同步到当前接入。') : _('已撤销放行，并同步到当前接入。')};
		}).catch(function(err) {
			self.currentStatus = {state:'error',error:String(err)};
			self.notice = {kind:'error',text:_('操作结果暂时无法确认，请重新检测。'),detail:failure || String(err)};
		}).then(function() { sessionValue('job',null); self.busy = null; self.paint(action === 'allow' || action === 'revoke' ? 'az-domain' : 'az-toggle'); });
	},
	paint: function(focusId) {
		var panel = this.panelNode || document.getElementById('adzero-panel');
		if (!panel) return;
		var active = document.activeElement, mayFocus = !active || active === document.body || panel.contains(active);
		dom.content(panel, this.renderPanel(this.currentStatus || { state: 'loading' }));
		if (focusId && mayFocus) {
			var target = document.getElementById(focusId);
			if (!target || target.disabled) target = document.getElementById('az-status');
			if (target && !target.disabled) target.focus();
		}
	},
	refreshStatus: function(initial) {
		var self = this;
		if (self.busy) return Promise.resolve();
		var previous=self.currentStatus;
		self.busy = 'status'; self.notice = null; self.paint();
		return getStatus().then(function(s) { self.currentStatus = s; self.lastChecked = new Date(); })
			.catch(function(err) {
				if (previous && previous.state!=='loading' && previous.state!=='error') { self.currentStatus=Object.assign({},previous,{stale:true}); self.notice={kind:'error',text:_('无法取得新状态，上次概览仅供参考。请重新检测。')}; }
				else self.currentStatus = { state: 'error', error: String(err) };
			})
			.then(function() { self.busy = null; self.paint(initial === true ? null : 'az-status'); });
	},
	runAction: function(action, receipt) {
		var self = this, f = flags(self.currentStatus || {});
		if (['enable','disable','refresh'].indexOf(action)<0 || self.busy || !receipt && ((self.currentStatus || {}).stale || !((action === 'enable' && f.canEnable) || (action === 'disable' && f.canDisable) || (action === 'refresh' && f.enabled)))) return Promise.resolve();
		self.busy = action; self.notice = null; self.paint();
		var failure = null;
		return (receipt ? Promise.resolve(receipt) : policyCalls[action]()).then(function(result) {
			return trackJob(result,'action',action);
		}).catch(function(err) { failure = String(err); }).then(function() { return getStatus(); }).then(function(s) {
			self.currentStatus = s; self.lastChecked = new Date();
			var expected = action === 'disable' ? 'disabled' : 'configured_unverified';
			if (failure || s.state !== expected) self.notice = { kind: 'error', text: _('操作未完成，已重新读取当前状态。'), detail: failure || _('当前状态尚未满足操作结果，请检查服务日志后重新检测。') };
			else self.notice = { kind: 'success', text: action === 'enable' ? _('广告过滤已开启，规则配置已同步。') : action === 'disable' ? _('广告过滤已关闭，原有设置已恢复。') : _('规则已更新，当前配置已同步。') };
		}).catch(function(err) {
			self.currentStatus = { state: 'error', error: String(err) };
			self.notice = { kind: 'error', text: _('操作结果暂时无法确认，请重新检测。'), detail: failure || String(err) };
		}).then(function() { sessionValue('job',null); self.busy = null; self.paint(action === 'refresh' ? 'az-update' : 'az-toggle'); });
	},
	render: function(status) {
		var self = this;
		status = status || { state: 'loading' };
		this.panelNode = el('div', { id: 'adzero-panel' }, this.renderPanel(status));
		var root = el('div', { 'class': 'az-root' }, [ el('link', { rel: 'stylesheet', href: L.resource('view/adzero/overview.css') + '?v=0.8.2' }), this.panelNode ]);
		if (!this.pausePoll) {
			var self = this;
			this.pausePoll = function() {
				if (!document.contains(self.panelNode)) { poll.remove(self.pausePoll); self.pausePoll = null; return Promise.resolve(); }
				if (!self.busy && !(self.currentStatus || {}).stale && flags(self.currentStatus || {}).paused) return getStatus().then(function(s) {
					if (!self.busy && !(self.currentStatus || {}).stale && flags(self.currentStatus || {}).paused) {
						if (s.state !== 'paused') self.notice = null;
						self.currentStatus = s; self.lastChecked = new Date(); self.paint();
					}
				}).catch(function() {});
				return Promise.resolve();
			};
			poll.add(this.pausePoll, 5);
		}
		if (status.cached_at) this.lastChecked=new Date(status.cached_at);
		if (status.state === 'loading' || status.stale) {
			var pendingJob=sessionValue('job');
			this.initialRequest = this.refreshStatus(true).then(function(){
				if (typeof pendingJob==='string') pendingJob={job:pendingJob,kind:'source'};
				if (!pendingJob || !/^[a-f0-9-]{36}$/.test(pendingJob.job || '')) return;
				var receipt={ok:true,job:pendingJob.job};
				if (pendingJob.kind==='action') return self.runAction(pendingJob.action,receipt);
				if (pendingJob.kind==='policy') return self.runPolicy(pendingJob.action,[],receipt);
				if (pendingJob.kind==='source') { self.rulesOpen=true; self.loadSources(); return self.continueSourceJob(receipt); }
			});
		}
		return root;
	},
	handleSave: null, handleSaveApply: null, handleReset: null
});
