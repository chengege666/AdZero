'use strict';
// Read-only inventory. No subscriptions, passwords, or full process arguments leave here.
import * as fs from 'fs';
import { cursor } from 'uci';
import { connect } from 'ubus';

const root = getenv('ADZERO_PROBE_ROOT') ?? '';
const uci = cursor(root + '/etc/config');
function release_file(path) {
	let data = {};
	for (let line in split(fs.readfile(root + path) ?? '', '\n')) {
		let m = match(line, /^([A-Z_]+)=(.*)\r?$/);
		if (!m) continue;
		let value = replace(m[2], /\r$/, '');
		if ((substr(value, 0, 1) == "'" && substr(value, -1) == "'") ||
			(substr(value, 0, 1) == '"' && substr(value, -1) == '"')) value = substr(value, 1, length(value)-2);
		data[m[1]] = value;
	}
	return data;
}
function quote(value) { return "'" + replace(value, /'/g, "'\\''") + "'"; }
function command(name, args) {
	let executable = getenv('ADZERO_' + uc(name)) ?? name;
	let proc = fs.popen(join(' ', map([executable, ...args], quote)) + ' 2>/dev/null', 'r');
	if (!proc) return '';
	let result = proc.read('all'), rc = proc.close();
	return rc == 0 ? trim(result) : '';
}
function has_command(name) {
	let executable = getenv('ADZERO_' + uc(name)) ?? name;
	if (index(executable, '/') >= 0) return fs.access(executable, 'x');
	for (let path in split(getenv('PATH') ?? '/usr/sbin:/usr/bin:/sbin:/bin', ':'))
		if (fs.access(path + '/' + executable, 'x')) return true;
	return false;
}
const processes = {};
for (let path in fs.glob(root + '/proc/[0-9]*/comm') ?? []) {
	let name = trim(fs.readfile(path) ?? '');
	if (index(['dae','daed','mihomo','clash','xray','sing-box','dnsmasq','smartdns','unbound','AdGuardHome'], name) >= 0) processes[name] = true;
}
let services = {};
const fixture = getenv('ADZERO_PROBE_SERVICE_FIXTURE');
try {
	if (fixture && root) services = json(fs.readfile(fixture));
	else {
		let bus = connect();
		if (bus) { services = bus.call('service', 'list', {}) ?? {}; bus.disconnect(); }
	}
} catch (e) { services = {}; }
if (type(services) != 'object') services = {};
function service_state(name) {
	let instances = services[name]?.instances, stopped = false;
	if (type(instances) != 'object') return 'unknown';
	for (let id in keys(instances ?? {})) {
		if (instances[id].running === true) return 'running';
		if (instances[id].running === false) stopped = true;
	}
	return stopped ? 'stopped' : 'unknown';
}
function section(config, type) {
	let first = null;
	uci.foreach(config, type, s => { first ??= s['.name']; });
	return first;
}
function value(config, name, option) { return name ? uci.get(config, name, option) : null; }
const plugins = [], rows = [
	['nailink','daed','main','enabled',null,null],
	['passwall','passwall',section('passwall','global'),'enabled',null,'dns_redirect'],
	['passwall2','passwall2',section('passwall2','global'),'enabled',null,'dns_redirect'],
	['openclash','openclash','config','enable',null,'enable_redirect_dns'],
	['nikki','nikki','config','enabled','proxy','ipv4_dns_hijack']
];
let proxy_count = 0, active_proxy_count = 0;
for (let row in rows) {
	let id = row[0], service = row[1], name = row[2], flag = row[3], hint_section = row[4], hint_option = row[5];
	let installed = !!(fs.stat(root + '/etc/config/' + service) || fs.stat(root + '/etc/init.d/' + service));
	let runtime = 'unknown', hint = 'unknown', enabled = null;
	if (id == 'nailink') {
		installed ||= !!fs.stat(root + '/usr/share/daed-router/version') || !!processes.daed;
		if (processes.daed) runtime = 'running';
		hint = 'proxy_core_dns';
	}
	let setting = value(service, name, flag);
	if (setting == '1') enabled = true; else if (setting == '0') enabled = false;
	if (installed && runtime == 'unknown') runtime = service_state(service);
	if (hint_option) {
		let setting = value(service, hint_section ?? name, hint_option);
		if (setting == '0') hint = 'disabled';
		else if (setting == '1') hint = 'plugin_redirect';
		else if (id == 'openclash' && setting == '2') hint = 'firewall_redirect';
	}
	if (installed) proxy_count++;
	if (installed && (enabled === true || runtime == 'running')) active_proxy_count++;
	push(plugins, {id, installed, enabled, runtime, dns_hint:hint, integration:'unverified'});
}
const release = release_file('/etc/openwrt_release'), os = release_file('/etc/os-release');
const vendor = release.DISTRIB_ID || os.NAME || '', version = release.DISTRIB_RELEASE || os.VERSION_ID || '';
let family = 'unknown', lower = lc(vendor);
for (let name in ['istoreos','immortalwrt','openwrt']) if (index(lower, name) >= 0) { family = name; break; }
let track = 'unvalidated';
if (match(version, /^(24\.10|25\.12)(\.|$)/)) track = 'candidate';
else if (match(version, /^23\.05(\.|$)/)) track = 'legacy_candidate';
else if (index(lc(version), 'snapshot') >= 0) track = 'snapshot';
const opkg = has_command('opkg'), apk = has_command('apk');
const opkg_db = !!(fs.stat(root + '/usr/lib/opkg/status') || fs.stat(root + '/var/lib/opkg/status'));
const apk_db = !!fs.stat(root + '/lib/apk/db/installed');
let manager = 'unknown', arch = 'unknown';
if (opkg_db && apk_db) manager = 'ambiguous';
else if (opkg_db && opkg) manager = 'opkg';
else if (apk_db && apk) manager = 'apk';
else if (opkg && !apk) manager = 'opkg';
else if (apk && !opkg) manager = 'apk';
else if (opkg && apk) manager = 'ambiguous';
if (manager == 'apk') arch = command('apk', ['--print-arch']);
else if (manager == 'opkg') {
	let priority = 0;
	for (let line in split(command('opkg', ['print-architecture']), '\n')) {
		let fields = split(trim(line), /[[:space:]]+/);
		if (fields[0] == 'arch' && fields[1] != 'all' && fields[1] != 'noarch' && int(fields[2]) > priority) {
			arch = fields[1]; priority = int(fields[2]);
		}
	}
}
if (!match(arch, /^[a-zA-Z0-9_+-]+$/)) arch = 'unknown';
let memory = match(fs.readfile(root + '/proc/meminfo') ?? '', /MemTotal:[[:space:]]*([0-9]+)/);
memory = memory ? int(memory[1]) : 0;
let dnsmasq_instances = 0, disabled_instances = 0;
uci.foreach('dhcp', 'dnsmasq', s => {
	if (dnsmasq_instances >= 64) return;
	dnsmasq_instances++;
	if (s.port == '0') disabled_instances++;
});
print(sprintf('%J\n', {schema_version:1, platform:{family, distribution:vendor, version, release_track:track,
	target:release.DISTRIB_TARGET ?? '', cpu:command('uname',['-m']) || 'unknown', kernel:command('uname',['-r']) || 'unknown',
	declared_arch:release.DISTRIB_ARCH ?? '', package_manager:manager, package_arch:arch,
	modern_luci:!!(fs.stat(root + '/www/luci-static/resources/luci.js') || fs.stat(root + '/www/luci-static/resources/view.js')),
	memory_kib:memory, resource_hint:memory ? (memory < 65536 ? 'low_memory' : 'normal') : 'unknown', validation:'not_device_tested'},
	plugins, cores:filter(['dae','daed','mihomo','clash','xray','sing-box'], n => processes[n]),
	resolvers:filter(['dnsmasq','smartdns','unbound','AdGuardHome'], n => processes[n]),
	dns:{dnsmasq_instances, disabled_instances, inventory_truncated:dnsmasq_instances == 64, proxy_count, active_proxy_count,
		client_path:'unverified', ipv6_path:'unverified', encrypted_dns_bypass:'possible'}}));
