'use strict';
'require view';
'require fs';
'require ui';
'require dom';

/*
 * AdZero uses the already authenticated LuCI session.
 * All privileged operations are a small fixed list in rpcd ACL, not a shell.
 */

function getStatus() {
	return fs.exec('/usr/libexec/adzero/ctl', [ 'status' ]).then(function(result) {
		if (Number(result.code) !== 0)
			throw new Error(result.stderr || _('无法读取 AdZero 状态'));

		return JSON.parse(result.stdout);
	});
}

function stateText(state) {
	switch (state) {
	case 'disabled': return _('已关闭');
	case 'configured_unverified': return _('后端已启用（DNS 链路待验证）');
	case 'external_owner': return _('后端已被其他配置管理');
	case 'inconsistent': return _('配置状态异常，请检查');
	case 'unavailable': return _('未安装 AdBlock-Fast 后端');
	default: return _('未知');
	}
}

return view.extend({
	load: function() {
		return getStatus().catch(function(err) {
			return { state: 'error', error: String(err) };
		});
	},

	renderPanel: function(status) {
		var self = this;
		var enabled = status.state === 'configured_unverified';
		var unavailable = status.state === 'unavailable' || status.state === 'error';
		var externallyManaged = status.state === 'external_owner';
		var canDisable = enabled || (status.state === 'inconsistent' && status.managed);
		var action = canDisable ? 'disable' : 'enable';
		var mayEnable = status.state === 'disabled' && status.dns_mode_safe === true && !status.adguardhome_running;
		var primary = E('button', {
			'class': 'cbi-button ' + (canDisable ? 'cbi-button-negative' : 'cbi-button-positive'),
			'disabled': unavailable || externallyManaged || (!canDisable && !mayEnable),
			'click': function() { return self.runAction(action); }
		}, canDisable ? _('关闭拦截') : _('开启广告拦截'));

		var explanations = [
			E('p', {}, [
				E('strong', {}, _('当前状态：')),
				stateText(status.state)
			]),
			E('p', {}, _('DNS 模式：') + (status.resolver || _('未知'))),
			E('p', {}, _('AdZero 将规则接入当前代理的原生 DNS 扩展入口，并保存恢复记录；启用时可能重启代理和 DNS 服务。'))
		];
		if (status.rule_sources === 'empty' || status.rule_sources === 'unknown')
			explanations.push(E('p', { 'class': 'alert-message warning' }, status.rule_sources === 'empty'
				? _('尚未配置拦截规则；首次开启将添加轻量默认规则，并保留已有用户列表。')
				: _('无法确认规则配置，请检查后端。')));
		if (status.adapter && status.adapter.stage !== 'inactive') {
			explanations.push(E('p', {}, _('DNS 适配：') + status.adapter.plugin + ' / ' + status.adapter.stage + _('；域名数：') + status.adapter.domains));
			if (status.adapter.stage === 'recovery_required')
				explanations.push(E('p', { 'class': 'alert-message danger' }, _('代理适配需要恢复，请先关闭保护并检查恢复记录。')));
		}

		if (status.nailink_detected && !status.compatibility) {
			var proxyState = status.nailink_running ? _('进程正在运行')
				: status.nailink_enabled ? _('配置已启用，进程未确认') : _('已安装，未确认运行');
			explanations.push(E('p', { 'class': 'alert-message warning' },
				_('NaiLink 已识别：') + proxyState + _('。它沿用 daed 服务，可能由代理内核处理 DNS；是否经过当前 DNS 过滤器仍需终端验证。')));
		}

		if (status.compatibility) {
			var inventory = status.compatibility;
			var platform = inventory.platform || {};
			var names = { nailink: 'NaiLink / daed', passwall: 'PassWall', passwall2: 'PassWall 2', openclash: 'OpenClash', nikki: 'Nikki' };
			var plugins = (inventory.plugins || []).filter(function(plugin) { return plugin.installed; });
			var runtimeText = { running: _('服务运行中'), stopped: _('服务已停止'), unknown: _('运行状态未确认') };
			explanations.push(E('div', { 'class': 'cbi-section' }, [
				E('h4', {}, _('设备与代理环境')),
				E('p', {}, _('固件：') + (platform.distribution || _('未知')) + ' ' + (platform.version || '')),
				E('p', {}, _('CPU / 软件包架构：') + (platform.cpu || _('未知')) + ' / ' + (platform.package_arch || _('未知'))),
				E('p', {}, _('包管理器：') + (platform.package_manager || _('未知'))),
				E('ul', {}, plugins.map(function(plugin) {
					return E('li', {}, (names[plugin.id] || plugin.id) + '：' +
						(plugin.enabled === true ? _('配置开启，') : plugin.enabled === false ? _('配置关闭，') : _('配置状态未知，')) +
						(runtimeText[plugin.runtime] || _('运行状态未确认')) + _('；DNS 接入未验证'));
				})),
				E('p', {}, plugins.length ? _('已识别代理插件；保护范围需结合实际 DNS 请求验证。') : _('未发现已知代理插件；仍需验证终端 DNS 路径。'))
			]));
			if (inventory.dns && inventory.dns.active_proxy_count > 1)
				explanations.push(E('p', { 'class': 'alert-message warning' }, _('多个代理插件处于启用或运行状态，DNS 路径需要进一步检查。')));
			if (platform.package_manager === 'ambiguous')
				explanations.push(E('p', { 'class': 'alert-message warning' }, _('同时发现 OPKG 和 APK 环境，安装包类型尚未确定。')));
			if (platform.resource_hint === 'low_memory')
				explanations.push(E('p', { 'class': 'alert-message warning' }, _('设备内存较少，应使用轻量规则并验证更新时的内存占用。')));
		} else {
			explanations.push(E('p', { 'class': 'alert-message warning' }, _('环境检测暂不可用；请检查插件安装文件。')));
		}

		if (status.adguardhome_running)
			explanations.push(E('p', { 'class': 'alert-message warning' },
				_('检测到 AdGuard Home 正在运行，AdZero 不会抢占它的 DNS 端口。')));

		if (status.state === 'external_owner')
			explanations.push(E('p', { 'class': 'alert-message warning' },
				_('AdBlock-Fast 已由外部启用，为避免误操作，AdZero 不会擅自接管。')));

		if (status.state === 'configured_unverified')
			explanations.push(E('p', {},
				_('后端已启用，但尚未验证真实设备 DNS 流量及广告过滤效果。')));

		explanations.push(E('div', { 'class': 'cbi-section' }, [
			E('h4', {}, _('安全与 DNS 兼容性体检')),
			E('ul', {}, [
				E('li', {}, _('DNS 后端模式：') + (status.resolver || _('未知')) +
					(status.dns_mode_safe ? _('（支持安全域名模式）') : _('（不支持自动启用）'))),
				E('li', {}, _('上游 DNS 强制重定向：') +
					(status.force_dns === 'off' ? _('已关闭')
						: status.force_dns === 'default_on' ? _('继承上游默认开启（启用 AdZero 时会临时关闭）')
						: status.force_dns === 'on' ? _('已开启（启用 AdZero 时会临时关闭）') : _('未知'))),
				E('li', {}, _('过滤规则下载的 HTTPS 证书验证：') +
					(status.tls_download === 'strict' ? _('严格验证')
						: status.tls_download === 'default_insecure' ? _('默认允许跳过（启用 AdZero 时将改为严格验证）')
						: status.tls_download === 'insecure' ? _('允许跳过（启用 AdZero 时将改为严格验证）')
						: _('未知配置'))),
				E('li', {}, _('dnsmasq 端口配置提示：') +
					(status.dnsmasq_port_hint === 'default' ? _('默认或未指定')
						: status.dnsmasq_port_hint === 'disabled' ? _('DNS 监听已关闭')
						: _('使用非默认端口'))),
				E('li', {}, _('终端真实 DNS 请求路径：未验证。配置检测不能代替实际查询测试。'))
			]),
			(status.dns_review_needed || (status.compatibility && status.compatibility.dns && status.compatibility.dns.active_proxy_count > 0))
				? E('p', { 'class': 'alert-message warning' },
					_('检测到潜在兼容性问题：请确认终端 DNS、代理内核 DNS 与当前过滤后端的连接关系。'))
				: E('p', {}, _('未发现已知的配置冲突，但拦截效果仍需在终端验证。'))
		]));

		if (status.state === 'error' && status.error)
			explanations.push(E('p', { 'class': 'alert-message danger' }, status.error));

		return E('div', { 'class': 'cbi-section' }, [
			E('h3', {}, _('一键广告拦截')),
			...explanations,
			E('div', { 'class': 'cbi-page-actions' }, [
				primary, ' ',
				E('button', {
					'class': 'cbi-button',
					'disabled': !enabled,
					'click': function() { return self.runAction('refresh'); }
				}, _('更新拦截规则')), ' ',
				E('button', {
					'class': 'cbi-button',
					'click': function() { return self.refreshStatus(); }
				}, _('重新检测配置'))
			]),
			E('p', { 'style': 'opacity:0.75;font-size:0.9em' },
				_('仅靠 DNS 拦截无法可靠去除同域视频广告和网页元素占位。'))
		]);
	},

	refreshStatus: function() {
		var self = this;
		return getStatus().then(function(status) {
			var panel = document.getElementById('adzero-panel');
			if (panel)
				dom.content(panel, self.renderPanel(status));
		}).catch(function(err) {
			ui.addNotification(null, E('p', {}, String(err)), 'error');
		});
	},

	runAction: function(action) {
		var self = this;
		var panel = document.getElementById('adzero-panel');
		if (panel) {
			var buttons = panel.querySelectorAll('button');
			for (var i = 0; i < buttons.length; i++)
				buttons[i].disabled = true;
		}

		return fs.exec('/usr/libexec/adzero/ctl', [ action ]).then(function(result) {
			if (Number(result.code) !== 0)
				throw new Error(result.stderr || _('操作执行失败'));
			ui.addNotification(null, E('p', {}, _('AdZero 操作已完成。')), 'info');
		}).catch(function(err) {
			ui.addNotification(null, E('p', {}, String(err)), 'error');
		}).then(function() {
			return getStatus();
		}).then(function(status) {
			if (panel)
				dom.content(panel, self.renderPanel(status));
		}).catch(function(err) {
			if (panel)
				dom.content(panel, self.renderPanel({ state: 'error', error: String(err) }));
		});
	},

	render: function(status) {
		return E('div', { 'class': 'cbi-map' }, [
			E('h2', {}, _('AdZero · 智能广告拦截')),
			E('p', {}, _('一键开启，无需独立登录，保留现有网络配置。')),
			E('div', { 'id': 'adzero-panel' }, this.renderPanel(status))
		]);
	},

	handleSave: null,
	handleSaveApply: null,
	handleReset: null
});
