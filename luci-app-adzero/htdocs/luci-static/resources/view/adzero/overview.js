'use strict';
'require view';
'require fs';
'require dom';

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
		return status;
	});
}
function flags(s) {
	var enabled = s.state === 'configured_unverified';
	return { enabled: enabled, canDisable: enabled || (s.state === 'inconsistent' && s.managed === true),
		canEnable: s.state === 'disabled' && s.dns_mode_safe === true && !s.adguardhome_running &&
			!(s.compatibility && s.compatibility.dns && s.compatibility.dns.active_proxy_count > 1) };
}
function pill(text, tone) { return el('span', { 'class': 'az-pill az-' + (tone || 'neutral') }, text); }
function row(label, value) { return el('div', { 'class': 'az-detail-row' }, [ el('dt', {}, label), el('dd', {}, value || _('未知')) ]); }
function number(value) { return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? new Intl.NumberFormat().format(value) : '—'; }
function step(n, title, description, done) {
	return el('li', { 'class': 'az-step' + (done ? ' is-done' : '') }, [
		el('span', { 'class': 'az-step-mark', 'aria-hidden': 'true' }, done ? icon('check') : String(n)),
		el('div', {}, [ el('strong', {}, title), el('p', {}, description) ]) ]);
}
return view.extend({
	busy: null, currentStatus: null, lastChecked: null, notice: null,
	diagnosticsOpen: false, pluginsOpen: false,
	load: function() {
		// Render first. A slow RPC must not hold LuCI's whole view behind a spinner.
		return Promise.resolve({ state: 'loading' });
	},
	renderPanel: function(s) {
		var self = this; self.currentStatus = s;
		var f = flags(s), inv = s.compatibility || {}, platform = inv.platform || {}, dns = inv.dns || {};
		var adapter = s.adapter || {}, backend = s.backend || {}, busy = self.busy, loading = s.state === 'loading';
		var plugins = (inv.plugins || []).filter(function(p) { return p.installed; });
		var active = names[adapter.plugin] || (adapter.plugin === 'none' ? _('路由器 DNS') : _('接入待确认'));
		var synced = f.enabled && adapter.stage === 'configured_unverified' && adapter.plugin && adapter.plugin !== 'none';
		var ready = f.enabled && backend.state === 'ready', verified = s.client_dns_verified === true;
		var checked = self.lastChecked ? new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(self.lastChecked) : '—';
		var titles = { configured_unverified: _('广告过滤已开启'), disabled: _('广告过滤未开启'),
			inconsistent: _('配置需要检查'), external_owner: _('当前由其他服务管理'),
			unavailable: _('过滤组件尚未就绪'), error: _('暂时无法读取状态'), loading: _('正在读取运行状态…') };
		var descriptions = { configured_unverified: _('规则已载入，当前接入配置已完成。'), disabled: _('开启后自动匹配当前网络，关闭时恢复原有设置。'),
			inconsistent: _('部分配置尚未确认，请关闭并恢复后再开启。'), external_owner: _('请先在原服务中关闭过滤后端，再启用 AdZero。'),
			unavailable: _('请检查插件依赖是否完整，然后重新检测。'), error: _('连接暂时中断，请重新检测后再操作。'), loading: _('页面已就绪，正在读取后端与代理状态。') };
		var blocker = s.adguardhome_running ? _('AdGuard Home 正在运行，请先关闭对应服务。') : dns.active_proxy_count > 1 ? _('多个代理同时启用，请保留一个正在使用的代理后重新检测。') :
			s.state === 'disabled' && s.dns_mode_safe !== true ? _('当前 DNS 模式不支持自动启用，请展开诊断检查。') : null;
		var toggle = f.canDisable && !f.enabled ? el('button', { id: 'az-toggle', 'class': 'az-button az-button-danger', type: 'button',
			'data-action': 'disable', disabled: busy ? true : null, click: function() { return self.runAction('disable'); } }, _('关闭并恢复')) : el('button', {
			id: 'az-toggle', 'class': 'az-toggle' + (f.enabled ? ' is-on' : ''), type: 'button', role: 'switch',
			'aria-label': _('广告过滤'), 'aria-checked': f.enabled ? 'true' : 'false', 'aria-describedby': 'az-operation-note',
			'data-action': f.enabled ? 'disable' : 'enable', disabled: busy || (!f.canEnable && !f.canDisable) ? true : null,
			click: function() { return self.runAction(f.enabled ? 'disable' : 'enable'); }
		}, el('span', { 'class': 'az-toggle-track', 'aria-hidden': 'true' }, el('span', { 'class': 'az-toggle-thumb' })));
		var nodes = [ el('header', { 'class': 'az-header' }, [
			el('div', { 'class': 'az-brand' }, [ el('span', { 'class': 'az-brand-mark', 'aria-hidden': 'true' }, icon('shield')),
				el('div', {}, [ el('h2', { translate: 'no' }, 'AdZero'), el('p', {}, _('运行概览')) ]) ]),
			el('div', { 'class': 'az-header-actions' }, [ el('span', { 'class': 'az-last-checked' }, self.lastChecked ? _('刚刚检测于 ') + checked : _('正在连接路由器')),
				el('button', { id: 'az-status', type: 'button', 'class': 'az-button az-button-quiet', 'data-action': 'status', disabled: busy ? true : null,
					click: function() { return self.refreshStatus(); } }, [ icon('refresh'), busy === 'status' ? _('检测中…') : _('重新检测') ]) ]) ]) ];
		if (self.notice) nodes.push(el('div', { 'class': 'az-notice az-notice-' + self.notice.kind, role: self.notice.kind === 'error' ? 'alert' : 'status' }, [
			icon(self.notice.kind === 'error' ? 'info' : 'check'), el('div', {}, [ el('strong', {}, self.notice.text),
				self.notice.detail ? el('details', { 'class': 'az-error-details' }, [ el('summary', {}, _('查看错误信息')), el('pre', {}, self.notice.detail) ]) : null ]) ]));
		if (busy && !loading) nodes.push(el('div', { 'class': 'az-working', role: 'status', 'aria-live': 'polite' }, [ el('span', { 'class': 'az-spinner', 'aria-hidden': 'true' }),
			busy === 'enable' ? _('正在开启过滤…') : busy === 'disable' ? _('正在关闭并恢复…') : busy === 'refresh' ? _('正在更新并同步规则…') : _('正在检测状态…') ]));
		nodes.push(el('section', { 'class': 'az-card az-hero' + (f.enabled ? ' is-on' : '') + (loading ? ' is-loading' : ''), 'aria-busy': loading ? 'true' : 'false' }, [
			el('div', { 'class': 'az-hero-main' }, [ el('div', { 'class': 'az-hero-heading' }, [ icon('shield'),
				el('h3', { 'class': 'az-hero-title' }, titles[s.state] || _('状态暂未确认')),
				pill(loading ? _('检测中') : f.enabled ? _('已开启') : s.state === 'disabled' ? _('已关闭') : _('需要留意'), f.enabled ? 'positive' : s.state === 'disabled' || loading ? 'neutral' : 'attention') ]),
				el('p', { 'class': 'az-hero-copy' }, descriptions[s.state] || _('请重新检测当前状态。')), blocker ? el('p', { 'class': 'az-inline-warning' }, [ icon('info'), blocker ]) : null ]),
			el('div', { 'class': 'az-switch-control' }, [ el('span', {}, loading ? _('等待状态确认') : _('保护开关')), toggle ]) ]));
		nodes.push(el('div', { 'class': 'az-stats-grid', 'aria-busy': loading ? 'true' : 'false' }, [
			el('section', { 'class': 'az-card az-stat' }, [ el('div', { 'class': 'az-stat-heading' }, [ el('span', {}, _('规则域名')), icon('settings') ]),
				el('strong', { 'class': 'az-number' + (loading ? ' az-placeholder' : '') }, number(ready ? backend.domains : null)), el('p', {}, ready ? _('当前已加载的有效域名') : loading ? _('正在读取规则信息') : _('开启后自动载入')) ]),
			el('section', { 'class': 'az-card az-stat' }, [ el('div', { 'class': 'az-stat-heading' }, [ el('span', {}, _('当前接入')), icon('shield') ]),
				el('strong', { 'class': 'az-stat-value', translate: 'no' }, loading ? '—' : f.enabled ? active : _('自动匹配')), el('p', {}, synced ? _('代理规则已同步') : f.enabled && adapter.plugin === 'none' ? _('使用路由器 DNS') : f.enabled ? _('接入状态待确认') : _('开启时自动识别当前代理')) ]),
			el('section', { 'class': 'az-card az-stat' }, [ el('div', { 'class': 'az-stat-heading' }, [ el('span', {}, _('终端验证')), icon('info') ]),
				el('strong', { 'class': 'az-stat-value az-verification' }, loading ? '—' : verified ? _('已验证') : _('待验证')), el('p', {}, verified ? _('已有实际查询验证记录') : _('需在手机或电脑上确认效果')) ]) ]));
		nodes.push(el('div', { 'class': 'az-work-grid' }, [
			el('section', { 'class': 'az-card az-rules' }, [ el('div', { 'class': 'az-section-heading' }, [ el('h3', {}, _('过滤规则')), pill(ready ? _('已载入') : _('等待开启'), ready ? 'positive' : 'neutral') ]),
				el('p', { 'class': 'az-card-copy' }, _('更新当前启用的域名列表，并自动同步到当前接入。')),
				el('div', { 'class': 'az-rule-action' }, [ el('span', {}, _('已有自定义规则时优先沿用。')),
					el('button', { id: 'az-update', 'class': 'az-button az-button-primary', type: 'button', 'data-action': 'refresh', disabled: busy || !f.enabled ? true : null,
						click: function() { return self.runAction('refresh'); } }, [ icon('refresh'), _('更新规则') ]) ]),
				el('p', { id: 'az-operation-note', 'class': 'az-operation-note' }, _('开关与更新可能短暂重载 DNS 或当前代理；关闭后恢复原有设置。')) ]),
			el('section', { 'class': 'az-card az-progress' }, [ el('div', { 'class': 'az-section-heading' }, [ el('h3', {}, _('接入检查')), pill(verified ? _('终端已验证') : _('终端待验证')) ]),
				el('ol', { 'class': 'az-steps' }, [ step(1, _('载入规则'), ready ? _('后端运行正常') : _('开启后准备'), ready),
					step(2, _('网络接入'), synced ? _('代理已同步') : f.enabled && adapter.plugin === 'none' ? _('DNS 已配置') : _('自动识别代理'), !!(f.enabled && (synced || adapter.plugin === 'none'))),
					step(3, _('终端效果'), verified ? _('查询已验证') : _('尚待实际验证'), verified) ]),
				el('p', { 'class': 'az-progress-note' }, _('配置完成不等于所有终端的流量都已过滤。')) ]) ]));
		nodes.push(el('div', { 'class': 'az-bottom-grid' }, [
			el('details', { id: 'az-plugins', 'class': 'az-card az-disclosure', open: self.pluginsOpen ? true : null, toggle: function(ev) { self.pluginsOpen = ev.currentTarget.open; } }, [
				el('summary', {}, [ el('div', {}, [ el('h3', {}, _('代理兼容')), el('p', {}, synced ? active + _(' 已接入') : _('查看已安装代理与接入状态')) ]), el('span', { 'class': 'az-summary-end' }, [ pill(String(plugins.length) + _(' 项已安装')), el('span', { 'class': 'az-chevron', 'aria-hidden': 'true' }) ]) ]),
				el('div', { 'class': 'az-disclosure-body' }, plugins.length ? plugins.map(function(p) {
					return el('div', { 'class': 'az-plugin-row' }, [ el('div', {}, [ el('strong', { translate: 'no' }, names[p.id] || p.id),
						el('span', {}, p.id === 'passwall2' ? _('仅识别，暂不自动接入') : p.runtime === 'running' ? _('服务运行中') : p.enabled === false ? _('配置未启用') : _('运行状态待确认')) ]),
						pill(synced && adapter.plugin === p.id ? _('当前接入') : p.enabled === true ? _('已启用') : _('未接入'), synced && adapter.plugin === p.id ? 'positive' : 'neutral') ]);
				}) : el('p', { 'class': 'az-note' }, loading ? _('正在读取代理环境…') : _('未检测到已知代理，将使用路由器 DNS。'))) ]),
			el('details', { id: 'az-diagnostics', 'class': 'az-card az-disclosure', open: self.diagnosticsOpen ? true : null, toggle: function(ev) { self.diagnosticsOpen = ev.currentTarget.open; } }, [
				el('summary', {}, [ el('div', {}, [ el('h3', {}, _('设备与诊断')), el('p', {}, platform.distribution ? platform.distribution + ' ' + platform.version + ' · ' + (platform.cpu === 'aarch64' ? 'ARM64' : platform.cpu || _('架构未知')) : _('固件、DNS 模式与安全设置')) ]),
					el('span', { 'class': 'az-summary-end' }, [ el('span', { 'class': 'az-summary-status' }, ready ? _('后端正常') : _('查看详情')), el('span', { 'class': 'az-chevron', 'aria-hidden': 'true' }) ]) ]),
				el('div', { 'class': 'az-disclosure-body' }, [ el('dl', { 'class': 'az-diagnostic-grid' }, [
					row(_('固件'), (platform.distribution || _('未知')) + ' ' + (platform.version || '')), row(_('设备目标'), platform.target), row(_('处理器'), platform.cpu),
					row(_('软件包架构'), platform.declared_arch || platform.package_arch), row(_('包管理器'), platform.package_manager), row(_('最后检测'), checked),
					row(_('过滤后端'), backend.state === 'ready' ? _('运行正常') : backend.state === 'stopped' ? _('已停止') : _('尚未确认')), row(_('DNS 模式'), s.resolver),
					row(_('额外 DNS 强制重定向'), s.force_dns === 'off' ? _('已关闭') : _('开启过滤时自动关闭')), row(_('HTTPS 规则下载'), s.tls_download === 'strict' ? _('严格验证证书') : _('开启过滤时严格验证')),
					row(_('终端过滤效果'), verified ? _('已验证') : _('尚未验证')), row(_('DNS 监听端口'), s.dnsmasq_port_hint === 'default' ? _('默认端口') : s.dnsmasq_port_hint === 'disabled' ? _('监听已关闭') : _('非默认端口')) ]),
					backend.errors > 0 ? el('p', { 'class': 'az-inline-warning' }, _('后端报告错误，请检查服务日志。')) : null,
					backend.warnings > 0 ? el('p', { 'class': 'az-note' }, _('后端有建议项，可结合服务日志查看。')) : null,
					platform.resource_hint === 'low_memory' ? el('p', { 'class': 'az-inline-warning' }, _('设备内存较少，建议使用轻量规则。')) : null,
					platform.package_manager === 'ambiguous' ? el('p', { 'class': 'az-inline-warning' }, _('同时发现 OPKG 和 APK，请确认软件包环境。')) : null,
					!s.compatibility && !loading ? el('p', { 'class': 'az-inline-warning' }, _('设备环境检测不可用，请检查安装文件。')) : null,
					el('p', { 'class': 'az-note' }, _('配置检查不能替代终端查询；请分别检查拦截域名与正常网站。')) ]) ]) ]));
		nodes.push(el('footer', { 'class': 'az-footer' }, [ icon('info'), _('DNS 过滤无法覆盖同域视频广告、网页占位或绕过路由器的请求。') ]));
		if (s.state === 'error' && s.error) nodes.push(el('details', { 'class': 'az-error-details az-load-error' }, [ el('summary', {}, _('查看连接错误')), el('pre', {}, s.error) ]));
		return el('div', { 'class': 'az-app' }, nodes);
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
		self.busy = 'status'; self.notice = null; self.paint();
		return getStatus().then(function(s) { self.currentStatus = s; self.lastChecked = new Date(); })
			.catch(function(err) { self.currentStatus = { state: 'error', error: String(err) }; })
			.then(function() { self.busy = null; self.paint(initial === true ? null : 'az-status'); });
	},
	runAction: function(action) {
		var self = this, f = flags(self.currentStatus || {});
		if (self.busy || !((action === 'enable' && f.canEnable) || (action === 'disable' && f.canDisable) || (action === 'refresh' && f.enabled))) return Promise.resolve();
		self.busy = action; self.notice = null; self.paint();
		var failure = null;
		return fs.exec('/usr/libexec/adzero/ctl', [ action ]).then(function(result) {
			if (Number(result.code) !== 0) throw new Error(result.stderr || _('操作未完成，请查看诊断。'));
		}).catch(function(err) { failure = String(err); }).then(function() { return getStatus(); }).then(function(s) {
			self.currentStatus = s; self.lastChecked = new Date();
			var expected = action === 'disable' ? 'disabled' : 'configured_unverified';
			if (failure || s.state !== expected) self.notice = { kind: 'error', text: _('操作未完成，已重新读取当前状态。'), detail: failure || _('当前状态尚未满足操作结果，请展开设备与诊断检查。') };
			else self.notice = { kind: 'success', text: action === 'enable' ? _('广告过滤已开启，规则配置已同步。') : action === 'disable' ? _('广告过滤已关闭，原有设置已恢复。') : _('规则已更新，当前配置已同步。') };
		}).catch(function(err) {
			self.currentStatus = { state: 'error', error: String(err) };
			self.notice = { kind: 'error', text: _('操作结果暂时无法确认，请重新检测。'), detail: failure || String(err) };
		}).then(function() { self.busy = null; self.paint(action === 'refresh' ? 'az-update' : 'az-toggle'); });
	},
	render: function(status) {
		status = status || { state: 'loading' };
		this.panelNode = el('div', { id: 'adzero-panel' }, this.renderPanel(status));
		var root = el('div', { 'class': 'az-root' }, [ el('link', { rel: 'stylesheet', href: L.resource('view/adzero/overview.css') + '?v=0.6.2' }), this.panelNode ]);
		if (status.state === 'loading') this.initialRequest = this.refreshStatus(true);
		return root;
	},
	handleSave: null, handleSaveApply: null, handleReset: null
});
