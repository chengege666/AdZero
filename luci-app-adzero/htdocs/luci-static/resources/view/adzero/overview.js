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
function icon(name) {
	// Static local paths only. Server text is always inserted as text nodes.
	return E('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><path d="' + icons[name] + '"/></svg>',
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
function pill(text, tone) { return E('span', { 'class': 'az-pill az-' + (tone || 'neutral') }, text); }
function row(label, value) { return E('div', { 'class': 'az-detail-row' }, [ E('dt', {}, label), E('dd', {}, value || _('未知')) ]); }
function number(value) { return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? new Intl.NumberFormat().format(value) : '—'; }
function step(n, title, description, done) {
	return E('li', { 'class': 'az-step' + (done ? ' is-done' : '') }, [
		E('span', { 'class': 'az-step-mark', 'aria-hidden': 'true' }, done ? icon('check') : String(n)),
		E('div', {}, [ E('strong', {}, title), E('p', {}, description) ]) ]);
}
return view.extend({
	busy: null, currentStatus: null, lastChecked: null, notice: null,
	diagnosticsOpen: false, pluginsOpen: false,
	load: function() {
		var self = this;
		return getStatus().then(function(s) { self.lastChecked = new Date(); return s; })
			.catch(function(err) { return { state: 'error', error: String(err) }; });
	},
	renderPanel: function(s) {
		var self = this; self.currentStatus = s;
		var f = flags(s), inv = s.compatibility || {}, platform = inv.platform || {}, dns = inv.dns || {};
		var adapter = s.adapter || {}, backend = s.backend || {}, busy = self.busy;
		var plugins = (inv.plugins || []).filter(function(p) { return p.installed; });
		var active = names[adapter.plugin] || (adapter.plugin === 'none' ? _('路由器 DNS') : _('待自动匹配'));
		var synced = f.enabled && adapter.stage === 'configured_unverified' && adapter.plugin && adapter.plugin !== 'none';
		var ready = f.enabled && backend.state === 'ready', verified = s.client_dns_verified === true;
		var titles = { configured_unverified: _('广告过滤已开启'), disabled: _('广告过滤未开启'),
			inconsistent: _('配置需要检查'), external_owner: _('当前由其他服务管理'),
			unavailable: _('过滤组件尚未就绪'), error: _('暂时无法读取状态'), loading: _('正在读取状态…') };
		var descriptions = { configured_unverified: _('规则已载入，自动匹配当前网络环境。'),
			disabled: _('一键开启广告域名过滤，自动匹配当前代理。'),
			inconsistent: _('部分配置或恢复状态尚未确认。请先关闭并恢复，再重新开启。'),
			external_owner: _('过滤后端已被其他配置启用。请先在原服务中关闭，再启用 AdZero。'),
			unavailable: _('请检查插件依赖是否安装完整，然后重新检测状态。'),
			error: _('连接可能暂时中断。重新检测后，再进行开关或更新操作。'), loading: _('正在检查规则与当前代理，请稍候。') };
		var blocker = s.adguardhome_running ? _('AdGuard Home 正在运行，请先关闭对应服务后再启用。') :
			dns.active_proxy_count > 1 ? _('多个代理同时启用，请保留一个正在使用的代理后重新检测。') :
			s.state === 'disabled' && s.dns_mode_safe !== true ? _('当前 DNS 模式不支持自动启用，请展开连接与诊断检查。') : null;
		var toggle = f.canDisable && !f.enabled ? E('button', { 'id': 'az-toggle', 'class': 'az-button az-button-danger',
			'type': 'button', 'data-action': 'disable', 'disabled': busy ? true : null,
			'click': function() { return self.runAction('disable'); } }, _('关闭并恢复')) : E('button', {
			'id': 'az-toggle', 'class': 'az-toggle' + (f.enabled ? ' is-on' : ''), 'type': 'button', 'role': 'switch',
			'aria-label': _('广告过滤'), 'aria-checked': f.enabled ? 'true' : 'false', 'aria-describedby': 'az-operation-note',
			'data-action': f.enabled ? 'disable' : 'enable',
			// false becomes disabled="false" in LuCI E(); omit enabled boolean attributes.
			'disabled': busy || (!f.canEnable && !f.canDisable) ? true : null,
			'click': function() { return self.runAction(f.enabled ? 'disable' : 'enable'); }
		}, E('span', { 'class': 'az-toggle-track', 'aria-hidden': 'true' }, E('span', { 'class': 'az-toggle-thumb' })));
		var checked = self.lastChecked ? new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(self.lastChecked) : '—';
		var nodes = [ E('header', { 'class': 'az-header' }, [
			E('div', { 'class': 'az-brand' }, [ E('span', { 'class': 'az-brand-mark', 'aria-hidden': 'true' }, icon('shield')),
				E('div', {}, [ E('h2', { 'translate': 'no' }, 'AdZero'), E('p', {}, _('广告域名过滤')) ]) ]),
			E('button', { 'id': 'az-status', 'type': 'button', 'class': 'az-button az-button-quiet', 'data-action': 'status',
				'disabled': busy ? true : null, 'click': function() { return self.refreshStatus(); } }, [ icon('refresh'), busy === 'status' ? _('正在检测…') : _('重新检测') ])
		]) ];
		if (self.notice) nodes.push(E('div', { 'class': 'az-notice az-notice-' + self.notice.kind, 'role': self.notice.kind === 'error' ? 'alert' : 'status' }, [
			icon(self.notice.kind === 'error' ? 'info' : 'check'), E('div', {}, [ E('strong', {}, self.notice.text),
				self.notice.detail ? E('details', { 'class': 'az-error-details' }, [ E('summary', {}, _('查看错误信息')), E('pre', {}, self.notice.detail) ]) : null ]) ]));
		if (busy) nodes.push(E('div', { 'class': 'az-working', 'role': 'status', 'aria-live': 'polite' }, [
			E('span', { 'class': 'az-spinner', 'aria-hidden': 'true' }),
			busy === 'enable' ? _('正在开启过滤…') : busy === 'disable' ? _('正在关闭并恢复…') : busy === 'refresh' ? _('正在更新并同步规则…') : _('正在检测状态…'),
			E('span', {}, _('操作完成后将自动刷新。')) ]));
		nodes.push(E('div', { 'class': 'az-overview-grid', 'aria-busy': busy ? 'true' : 'false' }, [
			E('section', { 'class': 'az-card az-hero' + (f.enabled ? ' is-on' : '') }, [
				E('div', { 'class': 'az-hero-top' }, [ pill(f.enabled ? _('已开启') : s.state === 'disabled' ? _('未开启') : _('需要留意'), f.enabled ? 'positive' : s.state === 'disabled' ? 'neutral' : 'attention'),
					E('div', { 'class': 'az-switch-control' }, [ E('span', {}, _('广告过滤')), toggle ]) ]),
				E('h3', { 'class': 'az-hero-title' }, titles[s.state] || _('状态暂未确认')),
				E('p', { 'class': 'az-hero-copy' }, descriptions[s.state] || _('请重新检测当前状态。')),
				blocker ? E('p', { 'class': 'az-inline-warning', 'role': 'note' }, [ icon('info'), blocker ]) : null,
				E('div', { 'class': 'az-metrics' }, [
					E('div', {}, [ E('span', { 'class': 'az-metric-label' }, _('已加载域名')), E('strong', { 'class': 'az-number' }, number(ready ? backend.domains : null)),
						E('span', { 'class': 'az-metric-note' }, ready ? _('当前有效的过滤规则') : _('开启后自动载入')) ]),
					E('div', {}, [ E('span', { 'class': 'az-metric-label' }, _('当前接入')), E('strong', { 'class': 'az-proxy-name', 'translate': 'no' }, f.enabled ? active : _('自动匹配')),
						E('span', { 'class': 'az-metric-note' }, synced ? _('代理规则已同步') : f.enabled ? _('使用路由器 DNS 过滤') : _('支持常见代理插件')) ]) ]),
				E('p', { 'id': 'az-operation-note', 'class': 'az-operation-note' }, _('开关及规则更新可能短暂重载 DNS 或当前代理。关闭后自动恢复原有设置。'))
			]),
			E('section', { 'class': 'az-card az-progress' }, [
				E('div', { 'class': 'az-section-heading' }, [ E('h3', {}, _('配置进度')), pill(verified ? _('终端已验证') : _('终端待验证')) ]),
				E('ol', { 'class': 'az-steps' }, [ step(1, _('载入域名规则'), ready ? _('过滤后端运行正常') : _('开启后自动准备'), ready),
					step(2, _('接入当前网络'), synced ? active + _(' · 规则已同步') : f.enabled && adapter.plugin === 'none' ? _('路由器 DNS 已配置') : _('自动识别正在使用的代理'), !!(f.enabled && (synced || adapter.plugin === 'none'))),
					step(3, _('确认终端效果'), verified ? _('已有实际查询验证记录') : _('连接路由器的设备尚待验证'), verified) ]),
				E('p', { 'class': 'az-progress-note' }, _('配置完成后，仍需在手机或电脑上确认实际过滤效果。'))
			]) ]));
		nodes.push(E('section', { 'class': 'az-card az-rules' }, [
			E('div', { 'class': 'az-rules-copy' }, [ E('span', { 'class': 'az-tile-icon', 'aria-hidden': 'true' }, icon('settings')),
				E('div', {}, [ E('h3', {}, _('过滤规则')), E('p', {}, f.enabled ? _('更新域名列表后，自动同步到当前接入。') : _('开启过滤后，即可更新与同步域名规则。')) ]) ]),
			E('button', { 'id': 'az-update', 'class': 'az-button az-button-primary', 'type': 'button', 'data-action': 'refresh',
				'disabled': busy || !f.enabled ? true : null, 'click': function() { return self.runAction('refresh'); } }, [ icon('refresh'), _('更新规则') ]) ]));
		nodes.push(E('div', { 'class': 'az-bottom-grid' }, [
			E('section', { 'class': 'az-card az-device' }, [ E('h3', {}, _('本机环境')), E('dl', { 'class': 'az-device-list' }, [
				row(_('固件'), (platform.distribution || _('未知')) + ' ' + (platform.version || '')),
				row(_('处理器'), platform.cpu === 'aarch64' ? 'ARM64' : platform.cpu), row(_('设备目标'), platform.target), row(_('最后检查'), checked) ]) ]),
			E('details', { 'id': 'az-plugins', 'class': 'az-card az-disclosure', 'open': self.pluginsOpen ? true : null,
				'toggle': function(ev) { self.pluginsOpen = ev.currentTarget.open; } }, [
				E('summary', {}, [ E('div', {}, [ E('h3', {}, _('代理兼容')), E('p', {}, synced ? active + _(' 已接入') : _('自动匹配当前使用的代理')) ]),
					E('span', { 'class': 'az-summary-end' }, [ pill(String(plugins.length) + _(' 项已安装')), E('span', { 'class': 'az-chevron', 'aria-hidden': 'true' }) ]) ]),
				E('div', { 'class': 'az-disclosure-body' }, plugins.length ? plugins.map(function(p) {
					return E('div', { 'class': 'az-plugin-row' }, [ E('div', {}, [ E('strong', { 'translate': 'no' }, names[p.id] || p.id),
						E('span', {}, p.id === 'passwall2' ? _('当前版本仅识别，暂不自动接入') : p.runtime === 'running' ? _('服务运行中') : p.enabled === false ? _('配置未启用') : _('运行状态待确认')) ]),
						pill(synced && adapter.plugin === p.id ? _('当前接入') : p.enabled === true ? _('已启用') : _('未接入'), synced && adapter.plugin === p.id ? 'positive' : 'neutral') ]);
				}) : E('p', {}, _('未检测到已知代理，AdZero 将使用路由器 DNS 过滤。'))) ]) ]));
		nodes.push(E('details', { 'id': 'az-diagnostics', 'class': 'az-card az-disclosure az-diagnostics', 'open': self.diagnosticsOpen ? true : null,
			'toggle': function(ev) { self.diagnosticsOpen = ev.currentTarget.open; } }, [
			E('summary', {}, [ E('div', { 'class': 'az-summary-title' }, [ icon('settings'), E('div', {}, [ E('h3', {}, _('连接与诊断')), E('p', {}, _('查看 DNS 模式、安全设置和设备兼容信息')) ]) ]),
				E('span', { 'class': 'az-summary-end' }, [ E('span', { 'class': 'az-summary-status' }, ready ? _('后端检查通过') : _('按需查看详情')), E('span', { 'class': 'az-chevron', 'aria-hidden': 'true' }) ]) ]),
			E('div', { 'class': 'az-disclosure-body' }, [ E('dl', { 'class': 'az-diagnostic-grid' }, [
				row(_('过滤后端'), backend.state === 'ready' ? _('运行正常') : backend.state === 'stopped' ? _('已停止') : _('尚未确认')),
				row(_('DNS 模式'), s.resolver), row(_('额外 DNS 强制重定向'), s.force_dns === 'off' ? _('已关闭') : _('开启过滤时自动关闭')),
				row(_('HTTPS 规则下载'), s.tls_download === 'strict' ? _('严格验证证书') : _('开启过滤时启用严格验证')),
				row(_('终端过滤效果'), verified ? _('已验证') : _('尚未验证')), row(_('软件包架构'), platform.declared_arch || platform.package_arch),
				row(_('包管理器'), platform.package_manager), row(_('DNS 监听端口'), s.dnsmasq_port_hint === 'default' ? _('默认端口') : s.dnsmasq_port_hint === 'disabled' ? _('监听已关闭') : _('非默认端口')) ]),
				backend.errors > 0 ? E('p', { 'class': 'az-inline-warning' }, _('后端报告错误，请检查服务日志后重新检测。')) : null,
				backend.warnings > 0 ? E('p', { 'class': 'az-note' }, _('后端有建议项，可结合服务日志查看。')) : null,
				platform.resource_hint === 'low_memory' ? E('p', { 'class': 'az-inline-warning' }, _('设备内存较少，建议保持轻量规则，并留意更新时的内存占用。')) : null,
				platform.package_manager === 'ambiguous' ? E('p', { 'class': 'az-inline-warning' }, _('同时发现 OPKG 和 APK，请先确认固件的软件包环境。')) : null,
				!s.compatibility ? E('p', { 'class': 'az-inline-warning' }, _('设备环境检测暂不可用，请检查插件安装文件。')) : null,
				E('p', { 'class': 'az-note' }, _('配置检查不能替代终端查询。请从连接路由器的设备确认 DNS 使用情况，并分别检查拦截域名和正常网站。')) ]) ]));
		nodes.push(E('footer', { 'class': 'az-footer' }, [ icon('info'), _('DNS 过滤针对广告域名；同域视频广告、网页占位及绕过路由器的请求可能不受影响。') ]));
		if (s.state === 'error' && s.error) nodes.push(E('details', { 'class': 'az-error-details az-load-error' }, [ E('summary', {}, _('查看连接错误')), E('pre', {}, s.error) ]));
		return E('div', { 'class': 'az-app' }, nodes);
	},
	paint: function(focusId) {
		var panel = document.getElementById('adzero-panel');
		if (!panel) return;
		var active = document.activeElement, mayFocus = !active || active === document.body || panel.contains(active);
		dom.content(panel, this.renderPanel(this.currentStatus || { state: 'loading' }));
		if (focusId && mayFocus) {
			var target = document.getElementById(focusId);
			if (!target || target.disabled) target = document.getElementById('az-status');
			if (target && !target.disabled) target.focus();
		}
	},
	refreshStatus: function() {
		var self = this;
		if (self.busy) return Promise.resolve();
		self.busy = 'status'; self.notice = null; self.paint();
		return getStatus().then(function(s) { self.currentStatus = s; self.lastChecked = new Date(); })
			.catch(function(err) { self.currentStatus = { state: 'error', error: String(err) }; })
			.then(function() { self.busy = null; self.paint('az-status'); });
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
			if (failure || s.state !== expected) self.notice = { kind: 'error', text: _('操作未完成，已重新读取当前状态。'), detail: failure || _('当前状态尚未满足操作结果，请展开连接与诊断检查。') };
			else self.notice = { kind: 'success', text: action === 'enable' ? _('广告过滤已开启，规则配置已同步。') : action === 'disable' ? _('广告过滤已关闭，原有设置已恢复。') : _('规则已更新，当前配置已同步。') };
		}).catch(function(err) {
			self.currentStatus = { state: 'error', error: String(err) };
			self.notice = { kind: 'error', text: _('操作结果暂时无法确认，请重新检测。'), detail: failure || String(err) };
		}).then(function() { self.busy = null; self.paint(action === 'refresh' ? 'az-update' : 'az-toggle'); });
	},
	render: function(status) {
		return E('div', { 'class': 'az-root' }, [ E('link', { 'rel': 'stylesheet', 'href': L.resource('view/adzero/overview.css') + '?v=0.6.0' }),
			E('div', { 'id': 'adzero-panel' }, this.renderPanel(status)) ]);
	},
	handleSave: null, handleSaveApply: null, handleReset: null
});
