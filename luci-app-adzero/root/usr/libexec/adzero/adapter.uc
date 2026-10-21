'use strict';
// Native plugin extension points only. Invoked under ctl's global lock.
import * as fs from 'fs';
import { cursor } from 'uci';
import { connect } from 'ubus';
import * as lib from './adapter-lib.uc';
import * as route from './routing-lib.uc';

const root = getenv('ADZERO_ADAPTER_ROOT') ?? '';
const state_dir = root + '/etc/adzero';
const journal_path = state_dir + '/adapter.json';
const uci = cursor(root + '/etc/config');
const split_enabled = uci.get('adzero','main','routing_enabled') == '1';
let routing_data = null;
let pending_nikki = null;
let journal = null;
let changed = false;
let transaction_previous = null;
let transaction_saved = false;
let action = shift(ARGV);
if (action == '--') action = shift(ARGV);

function quote(s) { return "'" + replace(s, /'/g, "'\\''") + "'"; }
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
		data = fs.readfile(root + path, 25000001);
		if (length(data)) break;
		sleep(1000);
	}
	if (!length(data)) die('Backend has not produced a non-empty blocklist');
	return lib.domains(data, mode);
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
function graphql(query, variables) {
	// Isolated API transaction fixture; unavailable on an unprefixed router.
	let fixture = getenv('ADZERO_NAILINK_API_FIXTURE');
	if (root && fixture) {
		let request = state_dir + '/fixture-request.json';
		atomic(request,sprintf('%J',{query,variables:variables ?? {}}));
		try { let data = json(capture([fixture,request])); fs.unlink(request); return data; }
		catch(e) { fs.unlink(request); die(e); }
	}
	// Use NaiLink's LuCI CGI gateway. No passwords, private JWT keys or SQLite edits.
	let bus = connect(), session;
	if (!bus) die('NaiLink requires rpcd/ubus');
	try {
		session = bus.call('session', 'create', {timeout:60})?.ubus_rpc_session;
		if (!session || !match(session, /^[a-f0-9]{32}$/)) die('Cannot create local adapter session');
		bus.call('session', 'grant', {ubus_rpc_session:session, scope:'access-group', objects:[['luci-app-daed-router','write']]});
		let payload = sprintf('%J', {query, variables:variables ?? {}});
		let request = state_dir + '/graphql-request.json';
		atomic(request, payload);
		let argv = ['env', 'REQUEST_METHOD=POST', 'REQUEST_URI=/cgi-bin/daed-router/graphql',
			'SCRIPT_NAME=/cgi-bin/daed-router', 'PATH_INFO=/graphql', 'SERVER_PROTOCOL=HTTP/1.1',
			'HTTP_HOST=localhost', 'HTTP_ORIGIN=http://localhost', 'HTTP_COOKIE=daed_luci_session=' + session,
			'CONTENT_TYPE=application/json', 'CONTENT_LENGTH=' + length(payload), root + '/usr/libexec/daed/luci-proxy'];
		let proc = fs.popen(join(' ', map(argv, quote)) + ' < ' + quote(request) + ' 2>/dev/null', 'r');
		let response = proc?.read('all'), rc = proc?.close();
		fs.unlink(request);
		if (rc != 0 || !length(response)) die('NaiLink CGI request failed');
		response = replace(response, /\r\n/g, '\n');
		let separator = index(response, '\n\n');
		if (separator < 0 || match(substr(response, 0, separator), /Status: [45]/)) die('NaiLink CGI rejected local access');
		let result = json(substr(response, separator + 2));
		if (length(result.errors ?? []) || !result.data) die('NaiLink API rejected DNS changes (private response omitted)');
		bus.call('session', 'destroy', {ubus_rpc_session:session});
		bus.disconnect();
		return result.data;
	} catch (e) {
		if (session) bus.call('session', 'destroy', {ubus_rpc_session:session});
		bus.disconnect();
		fs.unlink(state_dir + '/graphql-request.json');
		die(e);
	}
}
function active_plugin() {
	let inventory = getenv('ADZERO_ADAPTER_INVENTORY');
	let data = inventory ? json(fs.readfile(inventory)) : json(capture(['/bin/sh', root + '/usr/libexec/adzero/probe']));
	let active = filter(data.plugins, p => p.installed && (p.enabled == true || p.runtime == 'running'));
	if (length(active) > 1) die('Multiple active proxy plugins require manual DNS review');
	if (!length(active)) return 'none';
	if (index(['nailink','passwall','openclash','nikki'], active[0].id) < 0) die('Active proxy adapter is not supported yet');
	if (split_enabled) {
		if (active[0].id == 'nailink') {
			if (graphql('{general{dae{running}}}').general?.dae?.running !== true) return 'none';
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
function restart(plugin) {
	if (plugin == 'none') {
		if (journal?.split && system(['/bin/sh',root+'/etc/init.d/dnsmasq','restart'],30000)!=0)die('国内 DNS 配置未能重新加载。');
		return;
	}
	if (plugin == 'nailink') {
		if(journal?.split && graphql('{general{dae{running}}}').general?.dae?.running !== true){
			if(journal.stage=='restarting')die('NaiLink 内核在应用期间已停止。');
			return; // restoring profiles must not start a core the user stopped
		}
		graphql('mutation{run(dry:false)}'); return;
	}
	let service = root + '/etc/init.d/' + plugin;
	if(journal?.split){
		let inventory=getenv('ADZERO_ADAPTER_INVENTORY');
		let data=inventory?json(fs.readfile(inventory)):json(capture(['/bin/sh',root+'/usr/libexec/adzero/probe']));
		let state=filter(data.plugins??[],p=>p.id==plugin)[0];
		if(state?.runtime=='stopped'){
			if(journal.stage=='restarting')die('代理内核在应用期间已停止。');
			return; // restore persisted settings without starting a stopped proxy
		}
	}
	if (plugin == 'openclash' && journal?.stage == 'restarting') fs.unlink(state_dir + '/openclash-hook.json');
	if (system(['/bin/sh', service, 'restart'], 120000) != 0) die('Proxy restart failed');
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
		if(journal.split && (actual.mode!='rule' || index(actual.rules??[],'RULE-SET,adzero-cn-domain,DIRECT')<0 || actual.dns?.nameserver?.[0]!='tcp://'+route.foreign+':53#'+journal.split.target))die('Nikki 最终配置未保留分流策略。');
	}
}
function apply_plugin(plugin, list) {
	if (plugin == 'passwall') {
		let section;
		uci.foreach('passwall', 'global', s => { if (!section) section = s['.name']; });
		if (!section) die('Missing PassWall global section');
		let path = root + '/etc/passwall/rules/block_host';
		if(split_enabled){
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
function country_files(plugin) {
	let prefix=plugin=='nailink'?'/etc/daed/':plugin=='nikki'?'/etc/nikki/run/providers/rule/':'/etc/openclash/rule_provider/';
	if(plugin=='nailink'){
		tracked(root+prefix+'adzero-cn-geosite.dat',lib.geosite(routing_data.domains),'owned',0644);
		tracked(root+prefix+'adzero-cn-geoip.dat',route.geoip(routing_data.cidrs),'owned',0644);
	}else{
		tracked(root+prefix+'adzero-cn-domains.txt',join('\n',map(routing_data.domains,d=>'+.'+d))+'\n','owned',0644);
		tracked(root+prefix+'adzero-cn-ips.txt',join('\n',routing_data.cidrs)+'\n','owned',0644);
	}
	return {domains:prefix+'adzero-cn-domains.txt',ips:prefix+'adzero-cn-ips.txt'};
}
function apply_split(plugin) {
	if(!split_enabled)return;
	journal.split ??= {mode:plugin=='none'?'direct':'proxy',target:null,traffic_verified:false};
	if(plugin=='none'){
		let instances=[];uci.foreach('dhcp','dnsmasq',s=>push(instances,s));
		if(length(instances)!=1 || instances[0].port=='0' || index(['dnsmasq.servers','dnsmasq.addnhosts'],uci.get('adblock-fast','config','dns'))<0)die('无代理自动模式需要一个启用的 dnsmasq 实例。');
		let s=instances[0],servers=s.server??[];if(type(servers)!='array')servers=[servers];
		setting('dhcp',s['.name'],'server',[...route.domestic,...filter(servers,v=>substr(v,0,1)=='/')]);
		setting('dhcp',s['.name'],'noresolv','1');
		return;
	}
	if(plugin=='nailink'){
		country_files(plugin);
		let current=selected_dns();
		if(current.id!=journal.dns.id || current.dns.string!=journal.dns.after)die('NaiLink DNS 已变化，拒绝覆盖。');
		let after=route.dae_dns(current.dns.string);
		if(after!=current.dns.string){journal.dns.after=after;save();update_dns(current.id,after);changed=true;}
		let traffic=selected_traffic();
		if(journal.traffic && (traffic.id!=journal.traffic.id || traffic.text!=journal.traffic.after))die('NaiLink 流量路由已被外部修改。');
		after=route.dae_routing(traffic.text,traffic.target);
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
		for(let entry in [['dns_shunt','dnsmasq'],['chn_list','direct'],['use_default_dns','remote'],['direct_dns_mode','udp'],['direct_dns',route.domestic[0]+':53'],['remote_dns',route.foreign+':53'],['v2ray_dns_mode','tcp']])setting('passwall',section,entry[0],entry[1]);
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
		let result=route.mihomo(config,files.domains,files.ips);config=result.config;journal.split.target=result.target;
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
		update_dns(current.id, restored);
	}
	if(journal.traffic){let current=selected_traffic();if(current.id!=journal.traffic.id || current.text!=journal.traffic.after && current.text!=journal.traffic.before)die('NaiLink 流量路由已修改，恢复记录保留。');update_traffic(current.id,journal.traffic.before);}
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
		update_dns(current.id, value);
	}
	if(journal.traffic){let current=selected_traffic(),value=old.traffic?.after??journal.traffic.before;if(current.id!=journal.traffic.id || current.text!=journal.traffic.after && current.text!=value)die('Concurrent routing change prevents rollback');update_traffic(current.id,value);}
	restart(journal.plugin);
	atomic(journal_path, previous);
	fs.unlink(state_dir + '/adapter.previous.json');
	journal = old;
}

try {
	journal = read_journal();
	if (action == 'status') {
		print(sprintf('%J\n', {plugin:journal?.plugin ?? 'none', stage:journal?.stage ?? 'inactive', domains:journal?.count ?? 0,
			client_dns_verified:false, router_dns_verified:false,routing:{enabled:split_enabled,mode:journal?.split?.mode??'inactive',traffic_verified:false}}));
	} else if (action == 'remove') restore();
	else if (action == 'check') { print(active_plugin() + '\n'); }
	else if (action == 'hook-openclash') {
		let path = shift(ARGV);
		if (!journal || journal.plugin != 'openclash' || !path || substr(path, 0, 15) != '/etc/openclash/' || index(path, '..') >= 0) die('Unexpected OpenClash hook target');
		let config = yaml(root + path, 'openclash');
		if (config.dns?.enable != true) die('OpenClash DNS is disabled; automatic adapter is unavailable');
		if (config['rule-providers']?.['adzero-dns'] && config['rule-providers']['adzero-dns'].path != '/etc/openclash/rule_provider/adzero.txt') die('Reserved OpenClash rule provider already exists');
		config = lib.mihomo(config, '/etc/openclash/rule_provider/adzero.txt', false);
		if(journal.split){let result=route.mihomo(config,'/etc/openclash/rule_provider/adzero-cn-domains.txt','/etc/openclash/rule_provider/adzero-cn-ips.txt');config=result.config;}
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
		if (journal && journal.stage != 'configured_unverified') die('Adapter recovery is pending; disable protection first');
		let plugin = active_plugin(), list = rules();
		if (journal && journal.plugin != plugin) restore();
		if (plugin == 'none' && !split_enabled) exit(0);
		if(split_enabled && plugin!='none' && plugin!='passwall')routing_data=json(capture(['/bin/sh',getenv('ADZERO_ROUTING_DATA_PROGRAM')??'/usr/libexec/adzero/routing-data','prepare']));
		let previous = journal ? sprintf('%J', journal) : null;
		transaction_previous = previous;
		journal ??= {schema:1, plugin, files:[], flags:[], stage:'preparing'};
		try {
			if(journal.split && !split_enabled)die('分流设置变化，请先关闭并恢复。');
			if(split_enabled)journal.split??={mode:plugin=='none'?'direct':'proxy',traffic_verified:false};
			apply_plugin(plugin, list);
			apply_split(plugin);
			if (!changed && journal.stage == 'configured_unverified') { fs.unlink(state_dir + '/adapter.previous.json'); exit(0); }
			journal.count = length(list); journal.stage = 'restarting'; journal.generation = time(); save();
			restart(plugin);
			journal.stage = 'configured_unverified'; save();
			fs.unlink(state_dir + '/adapter.previous.json');
		} catch (e) {
			if (previous == null) {
				try { restore(); } catch (recovery) { die(e.message + '; recovery: ' + recovery.message + '. Journal retained in /etc/adzero/adapter.json'); }
			} else {
				try { rollback_update(previous); } catch (recovery) { journal.stage = 'recovery_required'; save(); die('Update rollback incomplete; recovery journal retained'); }
			}
			die(e);
		}
	} else die('Usage: adapter {check|apply|remove|status|hook-openclash PATH}');
} catch (e) {
	if (action == 'hook-openclash' && journal) { journal.stage = 'recovery_required'; save(); }
	fs.stderr.write('AdZero DNS adapter: ' + e.message + '\n');
	exit(1);
}
