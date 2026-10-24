'use strict';
// Read-only backend verification. Never infer success from init's exit status.
import * as fs from 'fs';
import { cursor } from 'uci';
import { connect } from 'ubus';
import * as rulecache from './rules-cache.uc';
import { limits } from './capacity-lib.uc';

const root = getenv('ADZERO_BACKEND_ROOT') ?? '';
const capacity=limits(root);
const fixture = getenv('ADZERO_BACKEND_SERVICE_FIXTURE');
let action = shift(ARGV);
if (action == '--') action = shift(ARGV);
const outputs = {
	'dnsmasq.servers': '/var/run/adblock-fast/dnsmasq.servers',
	'dnsmasq.addnhosts': '/var/run/adblock-fast/dnsmasq.addnhosts',
	'smartdns.domainset': '/var/run/adblock-fast/smartdns.domainset',
	'unbound.adb_list': '/var/lib/unbound/adb_list.adblock-fast'
};
let result = {state:'unknown', reason:'unavailable', status:'unknown', domains:0, rules_checked:false,
	errors:0, warnings:0, download_errors:0, error_codes:[], resolver_running:false};
const known_errors=['errorDownloadingList','errorDownloadingConfigUpdate','errorDownloadingDnsmasqConfig',
	'errorTooLittleRam','errorSharedMemory','errorDNSReload','errorFailDNSReload','errorParsingList',
	'errorDetectingFileType','errorDataFileFormatting','errorSorting','errorOptimization',
	'errorNoOutputFile','errorOutputFileCreate','errorOutputDirCreate','errorCreatingDirectory',
	'errorCopyingDataFile','errorMovingDataFile','errorConfigValidationFail','errorNothingToDo'];
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
		for (let e in errors){
			if(index(known_errors,e.code)>=0&&index(result.error_codes,e.code)<0)push(result.error_codes,e.code);
			if(index(['errorDownloadingList', 'errorDownloadingConfigUpdate', 'errorDownloadingDnsmasqConfig'],e.code)>=0)result.download_errors++;
		}
	}
	if (type(warnings) == 'array') result.warnings = length(warnings);
	let instances = services[split(mode, '.')[0]]?.instances;
	for (let name in keys(instances ?? {})) if (instances[name].running === true) result.resolver_running = true;
	let file = fs.stat(root + output);
	if (file?.size > capacity.output_bytes) die('oversized_output');
	let stopped = !(file?.size > 0) && (!data || ((!data.status || data.status == 'statusStopped') && !result.errors));
	if (stopped && result.resolver_running) { result.state = 'stopped'; result.reason = 'none'; }
	else if (uci.get('adblock-fast', 'config', 'enabled') == '1' && data?.status == 'statusSuccess' &&
		type(errors) == 'array' && !length(errors) && data.dns == mode && data.outputFile == output &&
		data.force_dns_active === false && int(data.entries) > 0 && file?.size > 0 && result.resolver_running) {
		if(int(data.entries)>capacity.total_domains)die('domain_limit');
		// A page read needs live service/output metadata, not another complete
		// import of the device's full rule set. Keep content validation for
		// ready (mutation preconditions and post-start checks). Never imply that
		// inspect verified the rule contents or the client's DNS path.
		if (action == 'inspect') {
			result.domains = int(data.entries);
		} else {
			result.domains = length(rulecache.load(root + output, mode, root));
			result.rules_checked = true;
		}
		result.state = 'ready'; result.reason = 'none';
	} else {
		result.state = 'unconfirmed';
		result.reason = !result.resolver_running ? 'resolver_not_running' : result.errors ? 'backend_errors' : 'status_or_output_mismatch';
	}
} catch (e) {
	// Only enumerated diagnostics leave this process, no UCI, service commands,
	// file contents or upstream subscription URLs (which may contain secrets).
	let reasons = ['unsupported_resolver', 'ubus_unavailable', 'invalid_service_data', 'oversized_output','domain_limit'];
	let invalid_rules=['Unexpected dnsmasq.servers record','Unexpected hosts record','Unexpected Unbound record',
		'Invalid processed domain','Invalid domain label','Empty processed blocklist','Overlapping allow exceptions require a dedicated adapter policy'];
	result.reason = e.message=='Processed blocklist exceeds domain limit'?'domain_limit':index(invalid_rules,e.message)>=0?'processed_rules_invalid':index(reasons, e.message) >= 0 ? e.message : 'invalid_output_or_state';
}
if(action=='failure'){
	let has=codes=>length(filter(result.error_codes,c=>index(codes,c)>=0))>0,reason='backend';
	if(index(['domain_limit','oversized_output'],result.reason)>=0)reason='source_limit';
	else if(result.download_errors)reason='source_download';
	else if(has(['errorTooLittleRam','errorSharedMemory']))reason='backend_memory';
	else if(has(['errorDNSReload','errorFailDNSReload'])||result.reason=='resolver_not_running')reason='backend_dns';
	else if(result.reason=='processed_rules_invalid'||has(['errorParsingList','errorDetectingFileType','errorDataFileFormatting','errorSorting','errorOptimization']))reason='backend_processing';
	else if(has(['errorNoOutputFile','errorOutputFileCreate','errorOutputDirCreate','errorCreatingDirectory','errorCopyingDataFile','errorMovingDataFile']))reason='backend_files';
	print(reason+'\n');exit(0);
}
print(sprintf('%J\n', result));
if (action == 'status') exit(0);
if (action == 'ready' || action == 'inspect') exit(result.state == 'ready' ? 0 : 1);
if (action == 'stopped') exit(result.state == 'stopped' ? 0 : 1);
if (action == 'download-error') exit(result.download_errors > 0 ? 0 : 1);
exit(2);
