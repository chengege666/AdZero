'use strict';
// Read-only backend verification. Never infer success from init's exit status.
import * as fs from 'fs';
import { cursor } from 'uci';
import { connect } from 'ubus';
import { domains } from './adapter-lib.uc';

const root = getenv('ADZERO_BACKEND_ROOT') ?? '';
const fixture = getenv('ADZERO_BACKEND_SERVICE_FIXTURE');
let action = shift(ARGV);
if (action == '--') action = shift(ARGV);
const outputs = {
	'dnsmasq.servers': '/var/run/adblock-fast/dnsmasq.servers',
	'dnsmasq.addnhosts': '/var/run/adblock-fast/dnsmasq.addnhosts',
	'smartdns.domainset': '/var/run/adblock-fast/smartdns.domainset',
	'unbound.adb_list': '/var/lib/unbound/adb_list.adblock-fast'
};
let result = {state:'unknown', reason:'unavailable', status:'unknown', domains:0,
	errors:0, warnings:0, download_errors:0, resolver_running:false};
try {
	let uci = cursor(root + '/etc/config');
	let mode = uci.get('adblock-fast', 'config', 'dns');
	let output = outputs[mode];
	if (!output) die('unsupported_resolver');
	let services;
	if (fixture && root) services = json(fs.readfile(fixture));
	else {
		let bus = connect();
		if (!bus) die('ubus_unavailable');
		let backend = bus.call('service', 'list', {name:'adblock-fast'});
		let resolver = split(mode, '.')[0];
		let dns = bus.call('service', 'list', {name:resolver});
		bus.disconnect();
		if (backend == null || dns == null) die('ubus_unavailable');
		services = {...backend, ...dns};
	}
	if (type(services) != 'object') die('invalid_service_data');
	let data = services['adblock-fast']?.data;
	let statuses = ['statusSuccess', 'statusStopped', 'statusFail', 'statusStarting', 'statusProcessing', 'statusDownloading'];
	if (index(statuses, data?.status) >= 0) result.status = data.status;
	let errors = data?.errors, warnings = data?.warnings;
	if (type(errors) == 'array') {
		result.errors = length(errors);
		for (let e in errors) if (index(['errorDownloadingList', 'errorDownloadingConfigUpdate', 'errorDownloadingDnsmasqConfig'], e.code) >= 0) result.download_errors++;
	}
	if (type(warnings) == 'array') result.warnings = length(warnings);
	let instances = services[split(mode, '.')[0]]?.instances;
	for (let name in keys(instances ?? {})) if (instances[name].running === true) result.resolver_running = true;
	let file = fs.stat(root + output);
	if (file?.size > 25000000) die('oversized_output');
	let stopped = !(file?.size > 0) && (!data || ((!data.status || data.status == 'statusStopped') && !result.errors));
	if (stopped && result.resolver_running) { result.state = 'stopped'; result.reason = 'none'; }
	else if (uci.get('adblock-fast', 'config', 'enabled') == '1' && data?.status == 'statusSuccess' &&
		type(errors) == 'array' && !length(errors) && data.dns == mode && data.outputFile == output &&
		data.force_dns_active === false && int(data.entries) > 0 && file?.size > 0 && result.resolver_running) {
		result.domains = length(domains(fs.readfile(root + output), mode));
		result.state = 'ready'; result.reason = 'none';
	} else {
		result.state = 'unconfirmed';
		result.reason = !result.resolver_running ? 'resolver_not_running' : result.errors ? 'backend_errors' : 'status_or_output_mismatch';
	}
} catch (e) {
	// Only enumerated diagnostics leave this process, no UCI, service commands,
	// file contents or upstream subscription URLs (which may contain secrets).
	let reasons = ['unsupported_resolver', 'ubus_unavailable', 'invalid_service_data', 'oversized_output'];
	result.reason = index(reasons, e.message) >= 0 ? e.message : 'invalid_output_or_state';
}
print(sprintf('%J\n', result));
if (action == 'status') exit(0);
if (action == 'ready') exit(result.state == 'ready' ? 0 : 1);
if (action == 'stopped') exit(result.state == 'stopped' ? 0 : 1);
if (action == 'download-error') exit(result.download_errors > 0 ? 0 : 1);
exit(2);
