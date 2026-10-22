'use strict';
// Native plugin extension points only. Invoked under ctl's global lock.
import * as fs from 'fs';
import { cursor } from 'uci';
import { connect } from 'ubus';
import * as lib from './adapter-lib.uc';
import * as route from './routing-lib.uc';
import * as progress from './progress-lib.uc';
import * as rulecache from './rules-cache.uc';
import * as proxy from './proxy-state.uc';

const root = getenv('ADZERO_ADAPTER_ROOT') ?? '';
const state_dir = root + '/etc/adzero';
const journal_path = state_dir + '/adapter.json';
const uci = cursor(root + '/etc/config');
const split_enabled = uci.get('adzero','main','routing_enabled') == '1';
const dns_profile=route.profile(json(uci.get('adzero','main','dns_profile')??'null'));
let routing_data = null;
let pending_nikki = null;
let journal = null;
let changed = false;
let transaction_previous = null;
let transaction_saved = false;
let clear_nailink_pending, nailink_completed, rules_signature;
let action = shift(ARGV);
if (action == '--') action = shift(ARGV);
const native_runtime={passwall:proxy.dns_runtime(root,'passwall'),ssrplus:proxy.dns_runtime(root,'ssrplus')};

function quote(s) { return "'" + replace(s, /'/g, "'\\''") + "'"; }
function service_command(plugin,operation){
	let path=root+'/etc/init.d/'+(plugin=='ssrplus'?'shadowsocksr':plugin);
	// /bin/sh init.d/name ignores its rc.common shebang and only defines
	// functions. Explicitly preserve OpenWrt's interpreter argument.
	let header=split(fs.readfile(path,256)??'','\n')[0];
	if(match(header,/^#!\/bin\/sh[[:space:]]+\/etc\/rc.common([[:space:]]|$)/))
		return ['/bin/sh',root+'/etc/rc.common',path,operation];
	return ['/bin/sh',path,operation];
}
function capture(argv) {
	let proc = fs.popen(join(' ', map(argv, quote)) + ' 2>/dev/null', 'r');
	if (!proc) die('Cannot execute adapter prerequisite');
	let data = proc.read('all'), rc = proc.close();
	if (rc != 0) die('Adapter prerequisite failed (private output omitted)');
	return data;
}
function directory(path) {
	if (fs.stat(path)?.type == 'directory') return;
	directory(fs.dirname(path));
	if (!fs.mkdir(path, 0700)) die('Cannot create adapter directory');
}
function atomic(path, data, mode) {
	if (fs.lstat(path)?.type == 'link') die('Refusing to replace an adapter target symlink');
	directory(fs.dirname(path));
	let name = path + '.adzero.' + time();
	let tmp = fs.open(name, 'wx', 0600);
	if (!tmp) die('Cannot create adapter temporary file');
	let written = tmp.write(data), closed = tmp.close(); // close flushes, with a checked return value
	if (written != length(data) || !closed) { fs.unlink(name); die('Short adapter write'); }
	if (!fs.chmod(name, mode ?? 0600) || !fs.rename(name, path)) { fs.unlink(name); die('Cannot commit adapter file'); }
}
function save() {
	if (transaction_previous != null && !transaction_saved) {
		atomic(state_dir + '/adapter.previous.json', transaction_previous);
		transaction_saved = true;
	}
	atomic(journal_path, sprintf('%J', journal));
}
function read_journal() {
	let raw = fs.readfile(journal_path);
	if (raw == null) return null;
	let value = json(raw);
	if (value.schema != 1 || !value.plugin || type(value.files) != 'array') die('Invalid adapter recovery journal');
	return value;
}
function tracked(path, content, kind, mode) {
	let original = fs.readfile(path), entry;
	for (let file in journal.files) if (file.path == path) entry = file;
	if (entry) {
		if ((kind == 'owned' ? b64enc(original) : original) != entry.after) die('Adapter file changed externally; refusing to overwrite');
		if (original == content) return;
	} else {
		if (kind == 'owned' && original != null) die('Reserved AdZero provider file already exists');
		entry = {path, before:original, after:original, kind, mode:(fs.stat(path)?.mode ?? mode ?? 0600) & 0777};
		push(journal.files, entry);
	}
	entry.previous_after = entry.after;
	entry.after = kind == 'owned' ? b64enc(content) : content;
	save(); // durable intent precedes mutation
	atomic(path, content, mode ?? entry.mode);
	changed = true;
}
function same(a, b) { return sprintf('%J', a) == sprintf('%J', b); }
function native_dns_state(){
	return journal?.runtime_supported?native_runtime[journal.plugin](journal.runtime_samples):{state:'unknown',reason:'runtime_unavailable'};
}
function record_dns_runtime(value){
	if(!same(journal.runtime,value)){journal.runtime=value;save();}
	if(value.state=='ready'&&(journal.runtime_retry_after||journal.runtime_retries)){
		delete journal.runtime_retry_after;delete journal.runtime_retries;save();
	}
}
function wait_native_dns(){
	let value=native_dns_state();
	for(let attempt=0;value.state=='missing'&&attempt<4;attempt++){
		progress.stage('confirming_proxy');sleep(1000);value=native_dns_state();
	}
	return value;
}

function setting(config, section, option, value) {
	if (length(uci.changes(config)?.[config] ?? [])) die('配置有其他页面的未提交修改，拒绝一并提交。');
	let entry;
	for (let flag in journal.flags) if (flag.config == config && flag.section == section && flag.option == option) entry = flag;
	let current = uci.get(config, section, option);
	if (entry && !same(current, entry.after)) die('Adapter UCI setting changed externally');
	if (!entry) { entry = {config, section, option, before:current, after:value}; push(journal.flags, entry); save(); }
	if (same(current, value)) return;
	entry.previous_after=entry.after;entry.after=value;save();
	if (!uci.set(config, section, option, value) || !uci.commit(config)) die('Cannot save adapter UCI setting');
	uci.unload(config);uci.load(config); // libuci retains the cursor's committed delta history
	changed = true;
}
function rules() {
	let mode = uci.get('adblock-fast', 'config', 'dns');
	let path = mode == 'unbound.adb_list' ? '/var/lib/unbound/adb_list.adblock-fast' : '/var/run/adblock-fast/' + mode;
	if (index(['dnsmasq.servers','dnsmasq.addnhosts','smartdns.domainset','unbound.adb_list'], mode) < 0) die('Unsupported processed rules mode');
	let data;
	for (let attempt = 0; attempt < 30; attempt++) {
		data = fs.stat(root + path)?.size;
		if (data > 0) break;
		sleep(1000);
	}
	if (!(data > 0)) die('Backend has not produced a non-empty blocklist');
	return rulecache.load(root + path, mode, root);
}
function yaml(path, engine) {
	let text = fs.readfile(path);
	if (!length(trim(text ?? ''))) return {};
	let data;
	if (engine == 'nikki') data = capture(['yq', '-o=json', '.', path]);
	else data = capture(['ruby', '-ryaml', '-rjson', '-e', 'puts JSON.generate(YAML.safe_load(File.read(ARGV[0]), aliases: true))', path]);
	let value = json(data);
	if (value == null) return {};
	if (type(value) != 'object') die('Expected a YAML mapping');
	return value;
}
function graphql(query, variables, readiness) {
	let operation = index(query, 'run(dry:false)') >= 0 ? 'reload' :
		index(query, 'parsedDns') >= 0 ? 'validate_dns' : index(query, 'updateDns') >= 0 ? 'write_dns' :
		index(query, 'parsedRouting') >= 0 ? 'validate_routing' : index(query, 'updateRouting') >= 0 ? 'write_routing' : 'read';
	// Isolated API transaction fixture; unavailable on an unprefixed router.
	let fixture = getenv('ADZERO_NAILINK_API_FIXTURE');
	if (root && fixture) {
		let request = state_dir + '/fixture-request.json';
		atomic(request,sprintf('%J',{query,variables:variables ?? {},readiness:!!readiness}));
		try { let data = json(capture([fixture,request])); fs.unlink(request); return data; }
		catch(e) { fs.unlink(request); die(e); }
	}
	// Use NaiLink's LuCI CGI gateway. No passwords, private JWT keys or SQLite edits.
	let bus = connect(), session, request, output;
	if (!bus) die('NaiLink requires rpcd/ubus');
	try {
		session = bus.call('session', 'create', {timeout:60})?.ubus_rpc_session;
		if (!session || !match(session, /^[a-f0-9]{32}$/)) die('Cannot create local adapter session');
		bus.call('session', 'grant', {ubus_rpc_session:session, scope:'access-group', objects:[['luci-app-daed-router','write']]});
		if (bus.call('session', 'access', {ubus_rpc_session:session, scope:'access-group', object:'luci-app-daed-router', function:'write'})?.access !== true)
			die('NaiLink local LuCI session was not granted access; no API request sent');
		let payload = readiness ? '' : sprintf('%J', {query, variables:variables ?? {}});
		request = state_dir + '/graphql-request.' + session + '.json';
		atomic(request, payload);
		let path = readiness ? '/health/ready' : '/graphql';
		let argv = ['env', 'REQUEST_METHOD=' + (readiness ? 'GET' : 'POST'), 'REQUEST_URI=/cgi-bin/daed-router' + path,
			'SCRIPT_NAME=/cgi-bin/daed-router', 'PATH_INFO=' + path, 'SERVER_PROTOCOL=HTTP/1.1',
			'HTTP_HOST=localhost', 'HTTP_ORIGIN=http://localhost', 'HTTP_COOKIE=daed_luci_session=' + session,
			'CONTENT_TYPE=application/json', 'CONTENT_LENGTH=' + length(payload), root + '/usr/libexec/daed/luci-proxy'];
		output = state_dir + '/graphql-response.' + session;
		atomic(output, '');
		// Bound read-only probes too: a database busy during reload must not
		// turn a completion poll into another 30-second wait per query.
		let rc = system(join(' ', map(argv, quote)) + ' < ' + quote(request) + ' > ' + quote(output) + ' 2>/dev/null', operation == 'read' ? 5000 : 35000);
		let response = fs.readfile(output, 8388609); fs.unlink(output);
		fs.unlink(request);
		if (rc != 0 || !length(response)) die('NaiLink CGI request failed');
		response = replace(response, /\r\n/g, '\n');
		let separator = index(response, '\n\n');
		if (separator < 0) die('NaiLink CGI returned an invalid response (' + operation + ')');
		let status = match(substr(response, 0, separator), /(^|\n)Status: ([0-9]{3})/);
		let code = status ? +status[2] : 200;
		if (code >= 400) {
			let reason = index([401,403],code) >= 0 ? 'local session denied' :
				index([502,504],code) >= 0 ? 'upstream unavailable or timed out; completion unconfirmed' :
				code == 503 ? 'gateway or backend not ready' : code == 413 ? 'request too large' : 'request rejected';
			if (operation == 'reload' && index([502,504],code) >= 0 && journal) {
				journal.nailink_reload_unconfirmed = true; save();
			}
			die('NaiLink CGI HTTP ' + code + ' (' + operation + '): ' + reason + '; private response omitted');
		}
		let result = json(substr(response, separator + 2));
		if (readiness) { bus.call('session','destroy',{ubus_rpc_session:session}); bus.disconnect(); return result; }
		if (length(filter(result.errors ?? [], e => type(e.message) == 'string' && substr(e.message,0,13) == 'access denied'))) {
			progress.failure('nailink_auth');
			die('NaiLink GraphQL authorization denied (' + operation + '); local LuCI session passed; check NaiLink local identity; private response omitted');
		}
		if (length(result.errors ?? []) || !result.data) {
			// A completed GraphQL error is a definite negative acknowledgement,
			// unlike a disconnected transport with no completed response.
			if(operation=='reload')clear_nailink_pending();
			die('NaiLink API rejected ' + operation + ' (private response omitted)');
		}
		bus.call('session', 'destroy', {ubus_rpc_session:session});
		bus.disconnect();
		return result.data;
	} catch (e) {
		if (session) bus.call('session', 'destroy', {ubus_rpc_session:session});
		bus.disconnect();
		if(request)fs.unlink(request);
		if(output)fs.unlink(output);
		die(e);
	}
}
function active_plugin() {
	let inventory = getenv('ADZERO_ADAPTER_INVENTORY');
	let data = inventory ? json(fs.readfile(inventory)) : json(capture(['/bin/sh', root + '/usr/libexec/adzero/probe']));
	if (length(data.dns?.uncertain_proxies ?? [])) die(index(data.dns.uncertain_proxies,'nailink')>=0?'无法确认 NaiLink 内核状态，请检查 NaiLink 后重新检测；尚未修改配置。':'无法确认当前代理内核状态，请检查对应插件后重新检测；尚未修改配置。');
	let active = filter(data.plugins, proxy.active);
	if (length(active) > 1) die('Multiple active proxy plugins require manual DNS review');
	if (!length(active)) return 'none';
	if (index(['nailink','passwall','openclash','nikki','ssrplus'], active[0].id) < 0) die('Active proxy adapter is not supported yet');
	if(active[0].id=='ssrplus'){
		if(split_enabled&&action!='routing-check')die('SSR Plus+ 当前支持广告过滤；请先关闭 AdZero 自动分流，保留 SSR Plus+ 原生分流。');
		let helper=fs.readfile(root+'/usr/share/shadowsocksr/gfw2ipset.sh',1048577)??'';
		if(index(helper,'/etc/ssrplus/deny.list')<0||index(helper,'denylist.conf')<0)die('当前 SSR Plus+ 缺少受支持的原生域名屏蔽接口。');
	}
	// Check the real gateway/backend before ctl enables or restarts filtering.
	// Merely recognizing a running process does not prove API authorization.
	let nailink_runtime = active[0].id == 'nailink' ? graphql('{general{dae{running}}}').general?.dae : null;
	if (active[0].id == 'nailink' && type(nailink_runtime?.running) != 'bool') die('NaiLink returned invalid runtime state');
	if (split_enabled && active[0].id!='ssrplus') {
		if (active[0].id == 'nailink') {
			if (nailink_runtime?.running !== true) return 'none';
		} else if (active[0].runtime == 'stopped') return 'none';
		else if (active[0].runtime != 'running') {
			let expected=active[0].id=='passwall'?['xray','sing-box']:['mihomo','clash'];
			if (!length(filter(data.cores??[],c=>index(expected,c)>=0))) die('无法确认当前代理内核状态，请检查代理服务。');
		}
	}
	return active[0].id;
}
function selected_dns() {
	let values = graphql('{dnss(selected:true){id dns{string}}}').dnss;
	if (length(values) != 1 || type(values[0].dns.string) != 'string') die('Expected one selected NaiLink DNS profile');
	return values[0];
}
function update_dns(id, text) {
	graphql('query($raw:String!){parsedDns(raw:$raw){string}}', {raw:text});
	graphql('mutation($id:ID!,$dns:String!){updateDns(id:$id,dns:$dns){id}}', {id, dns:text});
}
function selected_traffic() {
	let data=graphql('{routings(selected:true){id routing{string fallback{... on Plaintext{val}}}} groups{name}}');
	if(length(data.routings??[])!=1)die('需要唯一选中的 NaiLink 流量路由。');
	let current=data.routings[0],target=current.routing?.fallback?.val;
	if(index(map(data.groups??[],g=>g.name),target)<0)die('无法确认 NaiLink 默认代理策略，请检查当前路由。');
	return {id:current.id,text:current.routing.string,target};
}
function update_traffic(id,text) {
	graphql('query($raw:String!){parsedRouting(raw:$raw){string}}',{raw:text});
	graphql('mutation($id:ID!,$routing:String!){updateRouting(id:$id,routing:$routing){id}}',{id,routing:text});
}
function nailink_identity() {
	let bus = connect();
	if (!bus) return null;
	let services;
	try { services = bus.call('service','list',{name:'daed'}); } catch(e) { bus.disconnect(); return null; }
	bus.disconnect();
	let instances = filter(values(services?.daed?.instances ?? {}), i => i.running === true && type(i.pid) == 'int');
	if (length(instances) != 1) return null;
	let pid = instances[0].pid;
	if (pid <= 1) return null;
	let stat = match(fs.readfile('/proc/' + pid + '/stat') ?? '', /^[0-9]+ \(.*\) (.*)$/);
	let fields = stat ? split(stat[1], /[ \t]+/) : [];
	let boot = trim(fs.readfile('/proc/sys/kernel/random/boot_id') ?? '');
	if (!length(boot) || !match(fields[19] ?? '', /^[0-9]+$/)) return null;
	return {boot,pid,start:fields[19]};
}
function confirm_nailink_recovery() {
	if (!journal?.nailink_reload_unconfirmed) return;
	if (nailink_completed()) { clear_nailink_pending(); return; }
	let identity = nailink_identity();
	if (!identity || !journal.nailink_run_identity || same(identity,journal.nailink_run_identity)) {
		progress.failure('nailink_gateway');
		die('NaiLink reload completion is unconfirmed; no second mutation submitted. Restart the native NaiLink service before recovery; journal retained');
	}
	// A different procd process plus a responsive authorized API proves the
	// previous daemon's request cannot still commit after this restoration.
	graphql('{general{dae{running}}}');
	delete journal.nailink_reload_unconfirmed; save();
}
clear_nailink_pending = function() {
	delete journal.nailink_reload_unconfirmed;
	delete journal.nailink_run_identity;
	delete journal.nailink_completion;
	save();
};
nailink_completed = function() {
	let proof = journal?.nailink_completion;
	if (proof?.schema != 1 || !proof.barrier) return false;
	try {
		let runtime = graphql('{general{dae{running modified}}}').general?.dae;
		if (runtime?.running !== true || runtime?.modified !== false) return false;
		let health = graphql('', null, true);
		if (health?.ready !== true || health.configured !== true || health.listening !== true ||
			health.initialized !== true || health.dns_ready !== true || health.routing_ready !== true) return false;
		let dns = selected_dns();
		if (dns.id != proof.dns.id || dns.dns.string != proof.dns.text) return false;
		if (proof.traffic) { let traffic=selected_traffic(); if (traffic.id != proof.traffic.id || traffic.text != proof.traffic.text) return false; }
		for (let file in journal.files) {
			let current=fs.readfile(file.path);
			if ((file.kind=='owned'?b64enc(current):current) != file.after) return false;
		}
		if (!proof.input || !same(proof.input,rules_signature('nailink'))) return false;
		return true;
	} catch(e) { return false; }
};
function prepare_nailink_completion() {
	if(!journal.dns){
		journal.nailink_completion=null;journal.nailink_run_identity=nailink_identity();
		journal.nailink_reload_unconfirmed=true;save();return;
	}
	let dns=selected_dns(), runtime=graphql('{general{dae{running modified}}}').general?.dae;
	// Updating only the DAT file leaves modified=false for both the old and
	// new core. The native updateDns API increments the profile version even
	// for identical text. Establish a version barrier before submitting run.
	if (journal.stage=='restarting' && runtime?.running === true && runtime.modified === false) {
		update_dns(dns.id,dns.dns.string);
		runtime=graphql('{general{dae{running modified}}}').general?.dae;
	}
	let traffic=journal.traffic?selected_traffic():null;
	journal.nailink_completion={schema:1,forward:journal.stage=='restarting',
		barrier:runtime?.running===false || runtime?.running===true && runtime.modified===true,
		dns:{id:dns.id,text:dns.dns.string},traffic:traffic?{id:traffic.id,text:traffic.text}:null,
		input:rules_signature('nailink')};
	journal.nailink_run_identity=nailink_identity();
	journal.nailink_reload_unconfirmed=true; save(); // intent before dispatch
}
function settle_nailink() {
	if (!journal?.nailink_reload_unconfirmed || !journal.nailink_completion?.forward || !nailink_completed())
		die('NaiLink reload is still unconfirmed; no second mutation submitted; journal retained');
	journal.stage='configured_unverified';
	if(journal.nailink_completion.input)journal.rules_source=journal.nailink_completion.input;
	clear_nailink_pending();
	fs.unlink(state_dir+'/adapter.previous.json');
}
function restart(plugin) {
	progress.stage('restarting');
	if (plugin == 'none') {
		if (journal?.split && system(service_command('dnsmasq','restart'),30000)!=0)die('国内 DNS 配置未能重新加载。');
		return;
	}
	if (plugin == 'nailink') {
		if(graphql('{general{dae{running}}}').general?.dae?.running !== true){
			if(journal.stage=='restarting')die('NaiLink 内核在应用期间已停止。');
			return; // restoring profiles must not start a core the user stopped
		}
		prepare_nailink_completion();
		try { graphql('mutation{run(dry:false)}'); }
		catch(e) {
			if(!journal.nailink_reload_unconfirmed)die(e);
			progress.stage('confirming_proxy');
			let started=time();
			for(let attempt=0;journal.nailink_completion?.barrier && attempt<30 && time()-started<60;attempt++) {
				if (nailink_completed()) { clear_nailink_pending(); return; }
				if(root && getenv('ADZERO_NAILINK_API_FIXTURE'))break;
				sleep(2000);
			}
			progress.failure('nailink_gateway');
			die(e.message+'; completion pending, no second mutation submitted');
		}
		clear_nailink_pending(); return;
	}
	{
		let inventory=getenv('ADZERO_ADAPTER_INVENTORY');
		let data=inventory?json(fs.readfile(inventory)):json(capture(['/bin/sh',root+'/usr/libexec/adzero/probe']));
		let state=filter(data.plugins??[],p=>p.id==plugin)[0];
		if(state && !proxy.active(state) && (state.runtime=='stopped' || state.enabled===false)){
			if(journal.stage=='restarting')die('代理内核在应用期间已停止。');
			return; // restore persisted settings without starting a stopped proxy
		}
	}
	if (plugin == 'openclash' && journal?.stage == 'restarting') fs.unlink(state_dir + '/openclash-hook.json');
	if (system(service_command(plugin,'restart'), 120000) != 0) die('Proxy restart failed');
	if(native_runtime[plugin]&&journal?.stage=='restarting'){
		let value=wait_native_dns();
		// Native PassWall returns zero when another start/restart holds its
		// lock. Permit one retry, then keep an operable pending state instead
		// of rolling back valid rules or restarting again every minute.
		if(value.state=='missing'){
			if(system(service_command(plugin,'restart'),120000)!=0)die('Proxy restart failed');
			value=wait_native_dns();
		}
		record_dns_runtime(value);
		if(value.state=='missing'){journal.runtime_retry_after=time()+300;journal.runtime_retries=(journal.runtime_retries??0)+1;}
	}
	if (plugin == 'openclash' && journal?.stage == 'restarting') {
		let ready = false;
		for (let attempt = 0; attempt < 45; attempt++) {
			if (fs.readfile(state_dir + '/openclash-hook.json') == '' + journal.generation) { ready = true; break; }
			sleep(1000);
		}
		if (!ready) die('OpenClash did not confirm its generated DNS configuration');
	}
	if (plugin == 'nikki' && journal?.stage == 'restarting') {
		let actual = yaml(root + '/etc/nikki/run/config.yaml', 'nikki');
		if (actual.dns?.enable != true || !actual['rule-providers']?.['adzero-dns'] ||
			!actual.dns?.['nameserver-policy']?.['rule-set:adzero-dns'] ||
			index(actual.dns?.['fake-ip-filter'] ?? [], journal.filter_rule) < 0)
			die('Nikki generated configuration did not retain the DNS adapter');
		if(journal.split && (actual.mode!='rule' || index(actual.rules??[],'RULE-SET,adzero-cn-domain,DIRECT')<0 || actual.dns?.nameserver?.[0]!='tcp://'+route.endpoint(dns_profile.foreign.active)+'#'+journal.split.target))die('Nikki 最终配置未保留分流策略。');
	}
}
function apply_plugin(plugin, list) {
	if(plugin=='ssrplus'){
		let candidates=[];
		for(let file in ['black.list','white.list','netflix.list','gfw_list.conf','gfw_base.conf','oversea_list.conf']){
			let raw=fs.readfile(root+'/etc/ssrplus/'+file,5000001)??'';if(length(raw)>5000000)die('SSR Plus+ 域名列表超过安全限制。');
			for(let line in split(raw,'\n')){
				line=trim(line);let forward=match(line,/^server=\/([a-z0-9.-]+)\//);if(forward)line=forward[1];
				if(match(line,/^[a-z0-9][a-z0-9.-]*[a-z0-9]$/))push(candidates,line);
			}
		}
		list=route.expand_blockers(list,candidates);
		let path=root+'/etc/ssrplus/deny.list',base=lib.strip_block(fs.readfile(path)??'');
		tracked(path,base+(substr(base,-1)=='\n'||!length(base)?'':'\n')+lib.block(join('\n',list)),'block',0644);
	} else if (plugin == 'passwall') {
		let section;
		uci.foreach('passwall', 'global', s => { if (!section) section = s['.name']; });
		if (!section) die('Missing PassWall global section');
		let path = root + '/etc/passwall/rules/block_host';
		{
			let candidates=[];
			// dnsmasq's more-specific server rule can override a blocked parent.
			// Add equivalent child blockers; retain the user's native lists.
			for(let file in ['/usr/share/passwall/rules/chnlist','/usr/share/passwall/rules/gfwlist','/etc/passwall/rules/direct_host','/etc/passwall/rules/proxy_host']){
				let raw=fs.readfile(root+file,5000001)??'';if(length(raw)>5000000)die('PassWall 域名列表超过安全限制。');
				for(let line in split(raw,'\n')){line=trim(line);if(match(line,/^[a-z0-9][a-z0-9.-]*[a-z0-9]$/))push(candidates,line);}
			}
			list=route.expand_blockers(list,candidates);
		}
		let base = lib.strip_block(fs.readfile(path) ?? '');
		tracked(path, base + (substr(base, -1) == '\n' || !length(base) ? '' : '\n') + lib.block(join('\n', list)), 'block', 0644);
		setting('passwall', section, 'use_block_list', '1');
	} else if (plugin == 'openclash' || plugin == 'nikki') {
		let provider = plugin == 'nikki' ? '/etc/nikki/run/providers/rule/adzero.txt' : '/etc/openclash/rule_provider/adzero.txt';
		tracked(root + provider, join('\n', map(list, s => '+.' + s)) + '\n', 'owned', 0644);
		if (plugin == 'openclash') {
			let path = root + '/etc/openclash/custom/openclash_custom_overwrite.sh';
			let text = lib.strip_block(fs.readfile(path) ?? '#!/bin/sh\n');
			let pos = index(text, '\n') + 1;
			if (substr(text, 0, 2) != '#!') pos = 0;
			let hook = lib.block('/usr/libexec/adzero/adapter hook-openclash "$1" || exit 1');
			tracked(path, substr(text, 0, pos) + hook + substr(text, pos), 'block', 0755);
		} else {
			if (uci.get('nikki','config','core_only') == '1') die('Nikki core_only bypasses native mixins');
			let path = root + '/etc/nikki/mixin.yaml', config = yaml(path, 'nikki');
			if (uci.get('nikki','mixin','mixin_file_content') != '1' && length(keys(config))) die('Enabling an existing disabled Nikki mixin needs manual review');
			let effective = yaml(root + '/etc/nikki/run/config.yaml', 'nikki');
			config.dns ??= {};
			config.dns['fake-ip-filter-mode'] = uci.get('nikki','mixin','fake_ip_filter_mode') ?? config.dns['fake-ip-filter-mode'] ?? effective.dns?.['fake-ip-filter-mode'] ?? 'blacklist';
			config.dns['fake-ip-filter'] ??= effective.dns?.['fake-ip-filter'] ?? [];
			if (!length(journal.files) || !filter(journal.files, f => f.path == path)[0]) {
				if (config['rule-providers']?.['adzero-dns'] || config.dns?.['nameserver-policy']?.['rule-set:adzero-dns']) die('Reserved Mihomo names already exist');
			}
			// Nikki prepends nikki-rules; setting .rules would replace subscription rules.
			let original_rules = config.rules;
			config.rules = config['nikki-rules'] ?? [];
			config = lib.mihomo(config, provider, false);
			journal.filter_rule = config.dns['fake-ip-filter'][0];
			config['nikki-rules'] = config.rules;
			if (original_rules == null) delete config.rules; else config.rules = original_rules;
			if(split_enabled)pending_nikki={path,config,effective};
			else tracked(path, sprintf('%J', config) + '\n', 'nikki', 0600);
			setting('nikki', 'mixin', 'mixin_file_content', '1');
			// UCI-generated mixins are merged last and can replace YAML filter arrays.
			if (!split_enabled && uci.get('nikki','mixin','fake_ip_filter') == '1') {
				let filters = uci.get('nikki','mixin','fake_ip_filters') ?? [];
				if (type(filters) != 'array') filters = [filters];
				let own = config.dns['fake-ip-filter'][0];
				setting('nikki','mixin','fake_ip_filters',[own, ...filter(filters, s => s != own)]);
			}
		}
	} else if (plugin == 'nailink') {
		tracked(root + '/etc/daed/adzero-geosite.dat', lib.geosite(list), 'owned', 0644);
		let current = selected_dns();
		if (journal.dns && (current.id != journal.dns.id || current.dns.string != journal.dns.after)) die('NaiLink DNS profile changed externally');
		let after = lib.dae_dns(current.dns.string);
		journal.dns ??= {id:current.id, before:current.dns.string};
		if (after != current.dns.string) { journal.dns.after = after; save(); }
		if (selected_dns().dns.string != current.dns.string) die('NaiLink DNS changed while adapting');
		if (after != current.dns.string) { update_dns(current.id, after); changed = true; }
	}
}
function country_cached(plugin) {
	if(!same(journal?.country_sources,route.sources))return false;
	let suffixes=plugin=='nailink'?['adzero-cn-geosite.dat','adzero-cn-geoip.dat']:['adzero-cn-domains.txt','adzero-cn-ips.txt'];
	for(let suffix in suffixes){
		let entries=filter(journal.files,f=>substr(f.path,-length(suffix)-1)=='/'+suffix);
		if(length(entries)!=1||entries[0].kind!='owned'||b64enc(fs.readfile(entries[0].path))!=entries[0].after)return false;
	}
	return true;
}
function country_files(plugin) {
	let prefix=plugin=='nailink'?'/etc/daed/':plugin=='nikki'?'/etc/nikki/run/providers/rule/':'/etc/openclash/rule_provider/';
	if(country_cached(plugin))return {domains:prefix+'adzero-cn-domains.txt',ips:prefix+'adzero-cn-ips.txt'};
	if(plugin=='nailink'){
		tracked(root+prefix+'adzero-cn-geosite.dat',lib.geosite(routing_data.domains),'owned',0644);
		tracked(root+prefix+'adzero-cn-geoip.dat',route.geoip(routing_data.cidrs),'owned',0644);
	}else{
		tracked(root+prefix+'adzero-cn-domains.txt',join('\n',map(routing_data.domains,d=>'+.'+d))+'\n','owned',0644);
		tracked(root+prefix+'adzero-cn-ips.txt',join('\n',routing_data.cidrs)+'\n','owned',0644);
	}
	journal.country_sources=route.sources;save();
	return {domains:prefix+'adzero-cn-domains.txt',ips:prefix+'adzero-cn-ips.txt'};
}
function apply_split(plugin) {
	if(!split_enabled)return;
	journal.split ??= {mode:plugin=='none'?'direct':'proxy',target:null,traffic_verified:false};
	if(plugin=='none'){
		let instances=[];uci.foreach('dhcp','dnsmasq',s=>push(instances,s));
		if(length(instances)!=1 || instances[0].port=='0' || index(['dnsmasq.servers','dnsmasq.addnhosts'],uci.get('adblock-fast','config','dns'))<0)die('无代理自动模式需要一个启用的 dnsmasq 实例。');
		let s=instances[0],servers=s.server??[];if(type(servers)!='array')servers=[servers];
		setting('dhcp',s['.name'],'server',[dns_profile.domestic.active,...filter(servers,v=>substr(v,0,1)=='/')]);
		setting('dhcp',s['.name'],'noresolv','1');
		return;
	}
	if(plugin=='nailink'){
		country_files(plugin);
		let current=selected_dns();
		if(current.id!=journal.dns.id || current.dns.string!=journal.dns.after)die('NaiLink DNS 已变化，拒绝覆盖。');
		let after=route.dae_dns(current.dns.string,dns_profile);
		if(after!=current.dns.string){journal.dns.after=after;save();update_dns(current.id,after);changed=true;}
		let traffic=selected_traffic();
		if(journal.traffic && (traffic.id!=journal.traffic.id || traffic.text!=journal.traffic.after))die('NaiLink 流量路由已被外部修改。');
		after=route.dae_routing(traffic.text,traffic.target,dns_profile);
		journal.traffic ??= {id:traffic.id,before:traffic.text,after:traffic.text};
		journal.split.target=traffic.target;
		if(after!=traffic.text){journal.traffic.after=after;save();if(selected_traffic().text!=traffic.text)die('NaiLink 流量路由存在并发修改。');update_traffic(traffic.id,after);changed=true;}
		return;
	}
	if(plugin=='passwall'){
		let section;uci.foreach('passwall','global',s=>{section??=s['.name'];});
		let app=fs.readfile(root+'/usr/share/passwall/app.sh')??'',node=uci.get('passwall',section,'node');
		if(!node || !uci.get('passwall',node) || index(app,'direct_dns_mode')<0 || index(app,'USE_DEFAULT_DNS')<0)die('当前 PassWall 版本或默认节点不支持自动适配。');
		for(let name in ['chnlist','chnroute'])if(!length(trim(fs.readfile(root+'/usr/share/passwall/rules/'+name)??'')))die('PassWall 国内分类库未就绪。');
		let mode=uci.get('passwall',section,'dns_mode')??'tcp';
		if(index(['xray','sing-box','dns2socks','tcp'],mode)<0)die('当前 PassWall DNS 模式需先确认代理传输能力。');
		if(mode=='tcp'&&!fs.access(root+'/usr/bin/chinadns-ng','x'))die('当前 PassWall 缺少其原生 TCP DNS 转发组件。');
		for(let entry in [['dns_shunt','dnsmasq'],['chn_list','direct'],['use_default_dns','remote'],['direct_dns_mode','udp'],['direct_dns',route.endpoint(dns_profile.domestic.active)],['remote_dns',route.endpoint(dns_profile.foreign.active)],['v2ray_dns_mode','tcp']])setting('passwall',section,entry[0],entry[1]);
		journal.split.target='current-node';return;
	}
	let files=country_files(plugin);
	if(plugin=='nikki'){
		let path=pending_nikki.path,config=pending_nikki.config,effective=pending_nikki.effective;
		// Capture effective DNS arrays before disabling later UCI array overrides.
		let own_dns=config.dns??{},own_groups=config['proxy-groups'];
		config.dns={...(effective.dns??{}),...own_dns};
		config.dns['nameserver-policy']={...(effective.dns?.['nameserver-policy']??{}),...(own_dns['nameserver-policy']??{})};
		config['proxy-groups']??=effective['proxy-groups'];
		let own=config['nikki-rules']??[],original=config.rules;
		config.rules=effective.rules??[];
		let result=route.mihomo(config,files.domains,files.ips,dns_profile);config=result.config;journal.split.target=result.target;
		// Only prepend owned additions. The subscription's original rules remain.
		config['nikki-rules']=[...own,...filter(config.rules,r=>index(effective.rules??[],r)<0 && index(own,r)<0)];
		if(original==null)delete config.rules;else config.rules=original;
		if(own_groups==null)delete config['proxy-groups'];
		tracked(path,sprintf('%J',config)+'\n','nikki',0600);
		for(let key in ['dns_nameserver','dns_nameserver_policy'])if(uci.get('nikki','mixin',key)=='1')setting('nikki','mixin',key,'0');
		if(uci.get('nikki','mixin','mode')!=null)setting('nikki','mixin','mode','rule');
		if(uci.get('nikki','mixin','fake_ip_filter')=='1')setting('nikki','mixin','fake_ip_filters',config.dns['fake-ip-filter']);
	}
}
function restore() {
	if (!journal) return;
	confirm_nailink_recovery();
	progress.stage('restoring');
	journal.stage = 'restoring'; save();
	// Restore configuration first, restart, then remove provider files.
	for (let file in journal.files) {
		if (file.kind == 'owned') continue;
		let current = fs.readfile(file.path), restored = file.before;
		if (current != file.after && current != file.before && current != file.previous_after) {
			if (file.kind == 'block') restored = lib.strip_block(current ?? '');
			else die('Mixin was edited externally; recovery journal retained for review');
		}
		if (restored == null) fs.unlink(file.path); else atomic(file.path, restored, file.mode);
	}
	for (let flag in journal.flags) {
		if(length(uci.changes(flag.config)?.[flag.config]??[]))die('恢复配置有未提交的外部修改。');
		let current = uci.get(flag.config, flag.section, flag.option);
		if (!same(current, flag.after)) continue; // retain a later manual choice
		if (flag.before == null) uci.delete(flag.config, flag.section, flag.option);
		else uci.set(flag.config, flag.section, flag.option, flag.before);
		if (!uci.commit(flag.config)) die('Cannot restore adapter flag');
		uci.unload(flag.config);uci.load(flag.config);
	}
	if (journal.dns) {
		let current = selected_dns();
		if (current.id != journal.dns.id) die('NaiLink selected profile changed; recovery required');
		if(journal.split && current.dns.string!=journal.dns.after && current.dns.string!=journal.dns.before)die('NaiLink DNS 已修改，分流恢复记录保留。');
		let restored = current.dns.string == journal.dns.after ? journal.dns.before : lib.strip_block(current.dns.string);
		if (current.dns.string != restored) update_dns(current.id, restored);
	}
	if(journal.traffic){let current=selected_traffic();if(current.id!=journal.traffic.id || current.text!=journal.traffic.after && current.text!=journal.traffic.before)die('NaiLink 流量路由已修改，恢复记录保留。');if(current.text!=journal.traffic.before)update_traffic(current.id,journal.traffic.before);}
	restart(journal.plugin);
	for (let file in journal.files) if (file.kind == 'owned') {
		let current = fs.readfile(file.path);
		if (current != null && b64enc(current) != file.after && b64enc(current) != file.previous_after) die('Provider edited externally; journal retained');
		if (current != null && !fs.unlink(file.path)) die('Cannot remove owned provider');
	}
	if (!fs.unlink(journal_path)) die('Cannot clear adapter journal');
	fs.unlink(state_dir + '/adapter.previous.json');
	journal = null;
}
function rollback_update(previous) {
	confirm_nailink_recovery();
	progress.stage('restoring');
	let old = json(previous);
	journal.stage='rolling_back';
	for (let file in journal.files) {
		let saved = filter(old.files, f => f.path == file.path)[0];
		let value = saved ? (saved.kind == 'owned' ? b64dec(saved.after) : saved.after) : file.before;
		let current = fs.readfile(file.path);
		let encoded = file.kind == 'owned' ? b64enc(current) : current;
		if (current != value && encoded != file.after && encoded != file.previous_after) die('Concurrent edit prevents update rollback');
		if (value == null) fs.unlink(file.path); else atomic(file.path, value, file.mode);
	}
	for (let flag in journal.flags) {
		let saved = filter(old.flags, f => f.config == flag.config && f.section == flag.section && f.option == flag.option)[0];
		let value = saved ? saved.after : flag.before;
		let current = uci.get(flag.config, flag.section, flag.option);
		if (!same(current, value) && !same(current, flag.after)) die('Concurrent UCI change prevents rollback');
		if (value == null) uci.delete(flag.config, flag.section, flag.option); else uci.set(flag.config, flag.section, flag.option, value);
		if (!uci.commit(flag.config)) die('Cannot restore update UCI');
	}
	if (journal.dns) {
		let current = selected_dns(), value = old.dns?.after ?? journal.dns.before;
		if (current.id != journal.dns.id || (current.dns.string != journal.dns.after && current.dns.string != value)) die('Concurrent NaiLink DNS change prevents rollback');
		if (current.dns.string != value) update_dns(current.id, value);
	}
	if(journal.traffic){let current=selected_traffic(),value=old.traffic?.after??journal.traffic.before;if(current.id!=journal.traffic.id || current.text!=journal.traffic.after && current.text!=value)die('Concurrent routing change prevents rollback');if(current.text!=value)update_traffic(current.id,value);}
	restart(journal.plugin);
	atomic(journal_path, previous);
	fs.unlink(state_dir + '/adapter.previous.json');
	journal = old;
}

function routing_check(wanted) {
	if(index(['0','1'],wanted)<0)die('自动分流目标无效。');
	let plugin=active_plugin();
	if(plugin=='ssrplus'&&wanted=='1')die('SSR Plus+ 当前仅支持广告过滤，请使用其原生分流设置。');
	if(plugin!='nailink'||journal?.plugin!='nailink'||journal.stage!='configured_unverified')return 'full';
	let dns=selected_dns();
	if(dns.id!=journal.dns?.id||dns.dns.string!=journal.dns.after)die('NaiLink DNS profile changed externally');
	// Check syntax and selected target before any restore, download or reload.
	if(wanted=='1'){
		route.dae_dns(lib.dae_dns(journal.dns.before),dns_profile);
		let traffic=selected_traffic();
		if(journal.traffic&&(traffic.id!=journal.traffic.id||traffic.text!=journal.traffic.after))die('NaiLink 流量路由已被外部修改。');
		route.dae_routing(journal.traffic?.before??traffic.text,traffic.target,dns_profile);
	}
	return 'nailink';
}
rules_signature = function(plugin) {
	let mode=uci.get('adblock-fast','config','dns');
	let path=mode=='unbound.adb_list'?'/var/lib/unbound/adb_list.adblock-fast':'/var/run/adblock-fast/'+mode;
	let sha256=rulecache.fingerprint(root+path);if(!sha256)return null;
	let configs=['adzero','adblock-fast',plugin=='nailink'?'daed':plugin=='none'?'dhcp':plugin=='ssrplus'?'shadowsocksr':plugin];
	let dependencies={};
	let paths=map(filter(configs,c=>c!='adblock-fast'),c=>'/etc/config/'+c);
	if(plugin=='passwall')paths=[...paths,'/usr/share/passwall/app.sh','/usr/share/passwall/rules/chnlist','/usr/share/passwall/rules/chnroute','/usr/share/passwall/rules/gfwlist','/etc/passwall/rules/direct_host','/etc/passwall/rules/proxy_host'];
	if(plugin=='ssrplus')paths=[...paths,'/usr/share/shadowsocksr/gfw2ipset.sh',...map(['black.list','white.list','netflix.list','gfw_list.conf','gfw_base.conf','oversea_list.conf'],f=>'/etc/ssrplus/'+f)];
	if(plugin=='nikki')push(paths,'/etc/nikki/run/config.yaml');
	for(let c in configs)for(let delta in uci.changes(c)?.[c]??[]){
		if(c=='adblock-fast'&&delta[0]=='set'&&delta[2]=='size'&&match(''+delta[3],/^[0-9]+$/)&&uci.get(c,delta[1])=='file_url')continue;
		return null;
	}
	// Names, validation timestamps/counts and native download sizes do not
	// alter the rules. The exact processed output hash above still gates reuse.
	let backend_options=[];
	uci.foreach('adblock-fast',null,s=>{
		if(s['.type']=='file_url'&&s.enabled=='0')return;
		let values={};for(let k in sort(keys(s)))if(substr(k,0,1)!='.'&&!(s['.type']=='file_url'&&(k=='name'||k=='size'||substr(k,0,7)=='adzero_')))values[k]=s[k];
		push(backend_options,{id:s['.type']=='file_url'?null:s['.name'],type:s['.type'],values});
	});
	dependencies['/etc/config/adblock-fast']=backend_options;
	for(let name in paths){
		let stat=fs.lstat(root+name);
		if(!stat){dependencies[name]='missing';continue;}
		if(stat.type!='file')return null;
		if(name=='/etc/config/adzero'){
			let options=[];
			uci.foreach('adzero',null,s=>{
				let values={};for(let k in sort(keys(s)))if(substr(k,0,1)!='.'&&k!='dns_profile')values[k]=s[k];
				if(s['.name']=='main'&&split_enabled)values.dns_profile={domestic:dns_profile.domestic.active,foreign:dns_profile.foreign.active};
				push(options,{id:s['.name'],type:s['.type'],values});
			});
			dependencies[name]=options;continue;
		}
		if(!stat.size){dependencies[name]='empty';continue;}
		let hash=rulecache.fingerprint(root+name);if(!hash)return null;dependencies[name]=hash;
	}
	return {schema:4,mode,sha256,dependencies};
};
function reconfigure_nailink(with_rules) {
	if(routing_check(split_enabled?'1':'0')!='nailink')die('快速切换仅适用于当前 NaiLink 接入。');
	if(split_enabled&&!country_cached('nailink'))routing_data=json(capture(['/bin/sh',getenv('ADZERO_ROUTING_DATA_PROGRAM')??'/usr/libexec/adzero/routing-data','prepare']));
	let previous=sprintf('%J',journal);transaction_previous=previous;
	try{
		progress.stage('adapting');
		if(with_rules){let list=rules();tracked(root+'/etc/daed/adzero-geosite.dat',lib.geosite(list),'owned',0644);journal.count=length(list);}
		let dns=selected_dns(),after=lib.dae_dns(journal.dns.before),traffic=null,next=null;
		if(split_enabled){
			country_files('nailink');after=route.dae_dns(after,dns_profile);traffic=selected_traffic();
			journal.traffic??={id:traffic.id,before:traffic.text,after:traffic.text};
			next=route.dae_routing(journal.traffic.before,traffic.target,dns_profile);
			journal.split={mode:'proxy',target:traffic.target,traffic_verified:false};
		}else{
			delete journal.split;
			if(journal.traffic){traffic=selected_traffic();next=journal.traffic.before;}
		}
		if(traffic&&(traffic.id!=journal.traffic.id||traffic.text!=journal.traffic.after))die('NaiLink 流量路由存在并发修改。');
		if(selected_dns().dns.string!=dns.dns.string)die('NaiLink DNS 存在并发修改。');
		journal.dns.after=after;if(traffic)journal.traffic.after=next;
		journal.stage='preparing';save(); // one durable intent covers both profiles
		if(dns.dns.string!=after)update_dns(dns.id,after);
		if(traffic&&traffic.text!=next)update_traffic(traffic.id,next);
		journal.stage='restarting';save();restart('nailink');
		journal.stage='configured_unverified';
		let source=rules_signature('nailink');
		if(source&&(with_rules||source.sha256==journal.rules_source?.sha256))journal.rules_source=source;else delete journal.rules_source;
		save();fs.unlink(state_dir+'/adapter.previous.json');
	}catch(e){
		if(journal?.nailink_reload_unconfirmed)die(e);
		progress.failure('adapter');
		try{rollback_update(previous);}catch(recovery){journal.stage='recovery_required';save();die('快速切换恢复未完成，请保留恢复记录。');}
		die(e);
	}
}

function unchanged(plugin,signature) {
	if(!journal||journal.stage!='configured_unverified'||journal.plugin!=plugin||!signature||!same(journal.rules_source,signature)||!!journal.split!=split_enabled)return false;
	if(split_enabled&&index(['nailink','nikki','openclash'],plugin)>=0&&!country_cached(plugin))return false;
	for(let f in journal.files){let raw=fs.readfile(f.path);if((f.kind=='owned'?b64enc(raw):raw)!=f.after)return false;}
	for(let f in journal.flags)if(length(uci.changes(f.config)?.[f.config]??[])||!same(uci.get(f.config,f.section,f.option),f.after))return false;
	if(journal.dns){let current=selected_dns();if(current.id!=journal.dns.id||current.dns.string!=journal.dns.after)return false;}
	if(journal.traffic){let current=selected_traffic();if(current.id!=journal.traffic.id||current.text!=journal.traffic.after)return false;}
	return true;
}

try {
	journal = read_journal();
	if (action == 'status') {
		print(sprintf('%J\n', {plugin:journal?.plugin ?? 'none', stage:journal?.stage ?? 'inactive', domains:journal?.count ?? 0,
			client_dns_verified:false, router_dns_verified:false,reload_pending:!!journal?.nailink_reload_unconfirmed,
			runtime:native_runtime[journal?.plugin]?native_dns_state():null,
			runtime_retry_exhausted:(journal?.runtime_retries??0)>=3,
			routing:{enabled:split_enabled,mode:journal?.split?.mode??'inactive',traffic_verified:false}}));
	} else if (action == 'nailink-status') {
		let state = graphql('{general{dae{running modified}}}').general?.dae;
		if (type(state?.running) != 'bool') die('NaiLink returned invalid runtime state');
		print(sprintf('%J\n', {authorized:true,running:state.running,modified:type(state.modified) == 'bool' ? state.modified : null}));
	} else if (action == 'pending') { if(journal?.nailink_reload_unconfirmed){print('nailink\n');exit(0);}exit(1); }
	else if (action == 'settle') settle_nailink();
	else if (action == 'remove') restore();
	else if(action=='routing-check')print(routing_check(shift(ARGV))+'\n');
	else if(action=='reconfigure-nailink')reconfigure_nailink();
	else if(action=='reconfigure-nailink-rules')reconfigure_nailink(true);
	else if (action == 'check') { print(active_plugin() + '\n'); }
	else if (action == 'hook-openclash') {
		let path = shift(ARGV);
		if (!journal || journal.plugin != 'openclash' || !path || substr(path, 0, 15) != '/etc/openclash/' || index(path, '..') >= 0) die('Unexpected OpenClash hook target');
		let config = yaml(root + path, 'openclash');
		if (config.dns?.enable != true) die('OpenClash DNS is disabled; automatic adapter is unavailable');
		if (config['rule-providers']?.['adzero-dns'] && config['rule-providers']['adzero-dns'].path != '/etc/openclash/rule_provider/adzero.txt') die('Reserved OpenClash rule provider already exists');
		config = lib.mihomo(config, '/etc/openclash/rule_provider/adzero.txt', false);
		if(journal.split){let result=route.mihomo(config,'/etc/openclash/rule_provider/adzero-cn-domains.txt','/etc/openclash/rule_provider/adzero-cn-ips.txt',dns_profile);config=result.config;}
		let core = root + '/etc/openclash/core/clash_meta';
		if (!fs.access(core, 'x')) die('OpenClash requires its Mihomo/Meta core');
		let temporary = root + path + '.adzero-check';
		atomic(temporary, sprintf('%J', config) + '\n');
		let command = join(' ', map([core, '-t', '-d', root + '/etc/openclash', '-f', temporary], quote));
		let rc = system(command + ' >/dev/null 2>&1', 30000);
		if (rc != 0) { fs.unlink(temporary); die('OpenClash core rejected the adapted configuration'); }
		if (!fs.rename(temporary, root + path)) die('Cannot commit generated OpenClash configuration');
		atomic(state_dir + '/openclash-hook.json', '' + journal.generation);
	} else if (action == 'apply') {
		progress.stage('adapting');
		if (journal && journal.stage != 'configured_unverified') die('Adapter recovery is pending; disable protection first');
		let plugin = active_plugin(), signature=rules_signature(plugin);
		let runtime=native_runtime[plugin]&&journal?.plugin==plugin?native_dns_state():null;
		if(unchanged(plugin,signature)&&!(native_runtime[plugin]&&!journal.runtime_samples)){
			if(runtime)record_dns_runtime(runtime);
			if(runtime?.state!='missing'||((journal.runtime_retry_after??0)>time()||(journal.runtime_retries??0)>=3)&&getenv('ADZERO_ADAPTER_REFRESH')!='1'){
				fs.unlink(state_dir+'/adapter.previous.json');exit(0);
			}
		}
		let list = rules();
		if (journal && journal.plugin != plugin) restore();
		if (plugin == 'none' && !split_enabled) exit(0);
		if(split_enabled && plugin!='none' && plugin!='passwall'&&!country_cached(plugin))routing_data=json(capture(['/bin/sh',getenv('ADZERO_ROUTING_DATA_PROGRAM')??'/usr/libexec/adzero/routing-data','prepare']));
		let previous = journal ? sprintf('%J', journal) : null;
		transaction_previous = previous;
		journal ??= {schema:1, plugin, files:[], flags:[], stage:'preparing'};
		try {
			if(journal.split && !split_enabled)die('分流设置变化，请先关闭并恢复。');
			if(split_enabled)journal.split??={mode:plugin=='none'?'direct':'proxy',traffic_verified:false};
			apply_plugin(plugin, list);
			apply_split(plugin);
			if(native_runtime[plugin]){
				let section;uci.foreach('passwall','global',s=>{section??=s['.name'];});
				journal.runtime_supported=plugin=='ssrplus'||(uci.get('passwall',section,'dns_shunt')??'dnsmasq')=='dnsmasq'&&(uci.get('passwall',section,'dns_redirect')??'1')=='1';
				journal.runtime_samples=uniq([list[0],list[int(length(list)/2)],list[length(list)-1]]);
				runtime=native_dns_state();record_dns_runtime(runtime);
			}
			let signature_after=rules_signature(plugin);
			if(signature&&signature_after&&signature.sha256==signature_after.sha256&&signature.mode==signature_after.mode)journal.rules_source=signature_after;else delete journal.rules_source;
			if (!changed && journal.stage == 'configured_unverified' && runtime?.state!='missing') { journal.count=length(list);save();fs.unlink(state_dir + '/adapter.previous.json'); exit(0); }
			if(changed||getenv('ADZERO_ADAPTER_REFRESH')=='1')delete journal.runtime_retries;
			journal.count = length(list); journal.stage = 'restarting'; journal.generation = time(); save();
			restart(plugin);
			journal.stage = 'configured_unverified';
			signature_after=rules_signature(plugin);
			if(signature&&signature_after&&signature.sha256==signature_after.sha256&&signature.mode==signature_after.mode)journal.rules_source=signature_after;else delete journal.rules_source;
			save();
			fs.unlink(state_dir + '/adapter.previous.json');
		} catch (e) {
			if(journal?.nailink_reload_unconfirmed)die(e);
			if (previous == null) {
				try { restore(); } catch (recovery) { die(e.message + '; recovery: ' + recovery.message + '. Journal retained in /etc/adzero/adapter.json'); }
			} else {
				try { rollback_update(previous); } catch (recovery) { journal.stage = 'recovery_required'; save(); die('Update rollback incomplete; recovery journal retained'); }
			}
			die(e);
		}
	} else die('Usage: adapter {check|apply|remove|status|hook-openclash PATH}');
} catch (e) {
	progress.failure('adapter');
	if (action == 'hook-openclash' && journal) { journal.stage = 'recovery_required'; save(); }
	fs.stderr.write('AdZero DNS adapter: ' + e.message + '\n');
	exit(1);
}
