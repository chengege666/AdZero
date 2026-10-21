#!/usr/bin/env node
/* LuCI view smoke tests with a fake DOM and rpcd. No router or network access. */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(
	path.join(__dirname, '../luci-app-adzero/htdocs/luci-static/resources/view/adzero/overview.js'),
	'utf8'
);

function element(tag, attrs, children) {
	if (!Array.isArray(children) && children !== undefined)
		children = [children];
	return { tag, attrs: attrs || {}, children: children || [] };
}

function treeNodes(node, predicate, results = []) {
	if (node == null) return results;
	if (Array.isArray(node)) {
		for (const child of node) treeNodes(child, predicate, results);
		return results;
	}
	if (typeof node === 'object') {
		if (predicate(node)) results.push(node);
		treeNodes(node.children, predicate, results);
	}
	return results;
}

function toText(node) {
	if (node == null) return '';
	if (Array.isArray(node)) return node.map(toText).join(' ');
	if (typeof node !== 'object') return String(node);
	return toText(node.children);
}

const notifications = [];
const commands = [];
const panel = { content: null, querySelectorAll: () => [] };
const document = {
	getElementById: () => panel
};
const dom = { content: (target, content) => { target.content = content; } };
const view = { extend: x => x };
const ui = { addNotification: (_title, message, kind) => notifications.push({kind, message}) };
const state = {
	current: {
		state: 'disabled', managed: false, resolver: 'dnsmasq.servers',
		dns_mode_safe: true, dns_review_needed: false, force_dns: 'default_on',
		tls_download: 'default_insecure',
		dnsmasq_port_hint: 'default', client_dns_verified: false,
		nailink_detected: false, adguardhome_running: false
	},
	failAction: false
};
const fakeFs = {
	exec: (program, args) => {
		assert.equal(program, '/usr/libexec/adzero/ctl');
		commands.push(args.join(' '));
		if (args[0] === 'status')
			return Promise.resolve({code: 0, stdout: JSON.stringify(state.current)});
		if (state.failAction)
			return Promise.resolve({code: 1, stderr: 'simulated failure'});
		if (args[0] === 'enable') state.current.state = 'configured_unverified';
		if (args[0] === 'disable') state.current.state = 'disabled';
		return Promise.resolve({code: 0, stdout: 'ok'});
	}
};
const script = Function('view', 'fs', 'ui', 'dom', '_', 'E', 'document', source);
const app = script(view, fakeFs, ui, dom, text => text, element, document);

function buttons() {
	return treeNodes(app.renderPanel(state.current), n => n.tag === 'button');
}

(async () => {
	assert.equal(buttons().length, 3);
	assert.equal(buttons()[0].attrs.disabled, false);
	assert.match(toText(buttons()[0]), /开启广告拦截/);
	await buttons()[0].attrs.click();
	assert.equal(commands.slice(-2).join(','), 'enable,status');
	assert.equal(state.current.state, 'configured_unverified');
	assert.ok(notifications.some(x => x.kind === 'info'));
	assert.match(toText(app.renderPanel(state.current)), /终端真实 DNS 请求路径：未验证/);
	assert.match(toText(app.renderPanel(state.current)), /过滤规则下载的 HTTPS 证书验证/);

	await buttons()[1].attrs.click();
	assert.ok(commands.includes('refresh'));
	await buttons()[0].attrs.click();
	assert.equal(state.current.state, 'disabled');

	state.current.resolver = 'dnsmasq.nftset';
	state.current.dns_mode_safe = false;
	assert.equal(buttons()[0].attrs.disabled, true);
	state.current.resolver = 'dnsmasq.servers';
	state.current.dns_mode_safe = true;

	state.current.adguardhome_running = true;
	assert.equal(buttons()[0].attrs.disabled, true);
	state.current.adguardhome_running = false;

	state.current.state = 'external_owner';
	assert.equal(buttons()[0].attrs.disabled, true);
	state.current.state = 'inconsistent';
	state.current.managed = true;
	assert.match(toText(buttons()[0]), /关闭拦截/);
	assert.equal(buttons()[0].attrs.disabled, false);
	state.current.state = 'disabled';
	state.current.managed = false;

	state.current.nailink_detected = true;
	state.current.nailink_running = true;
	state.current.nailink_enabled = true;
	state.current.dns_review_needed = true;
	assert.match(toText(app.renderPanel(state.current)), /进程正在运行/);
	assert.match(toText(app.renderPanel(state.current)), /可能由代理内核处理 DNS/);
	state.current.compatibility = {
		platform: { distribution: 'ImmortalWrt', version: '25.12.5', cpu: 'aarch64', package_arch: 'aarch64_cortex-a53', package_manager: 'apk', resource_hint: 'normal' },
		plugins: ['nailink', 'passwall', 'passwall2', 'openclash', 'nikki'].map(id => ({ id, installed: true, enabled: true, runtime: 'unknown' })),
		dns: { active_proxy_count: 5 }
	};
	const inventoryText = toText(app.renderPanel(state.current));
	for (const name of ['NaiLink', 'PassWall', 'PassWall 2', 'OpenClash', 'Nikki', 'ImmortalWrt', '25.12.5', 'aarch64_cortex-a53', 'apk'])
		assert.ok(inventoryText.includes(name), name);
	assert.match(inventoryText, /多个代理插件/);
	assert.match(inventoryText, /DNS 接入未验证/);
	state.current.compatibility.platform.package_manager = 'ambiguous';
	state.current.compatibility.platform.resource_hint = 'low_memory';
	assert.match(toText(app.renderPanel(state.current)), /同时发现 OPKG 和 APK/);
	assert.match(toText(app.renderPanel(state.current)), /内存较少/);
	delete state.current.compatibility;

	state.failAction = true;
	await buttons()[0].attrs.click();
	assert.equal(state.current.state, 'disabled');
	assert.ok(notifications.some(x => x.kind === 'error' &&
		toText(x.message).includes('simulated failure')));
	state.failAction = false;

	const statusBefore = commands.filter(x => x === 'status').length;
	await buttons()[2].attrs.click();
	assert.equal(commands.filter(x => x === 'status').length, statusBefore + 1);
	assert.ok(panel.content);
	assert.equal(typeof app.load, 'function');
	assert.equal(typeof app.render, 'function');

	console.log('AdZero LuCI mock: status, enable, disable, refresh, diagnosis, unsafe-mode guard, NaiLink hints, error path — OK');
})().catch(err => {
	console.error(err);
	process.exitCode = 1;
});
