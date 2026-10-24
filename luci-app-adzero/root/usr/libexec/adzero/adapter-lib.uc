'use strict';

export function domains(raw, mode) {
	if (length(raw) > 25000000) die('Processed blocklist exceeds the adapter size limit');
	let values = {}, allowed = [];
	// ucode compiles a regex literal when its expression executes. Compile
	// once per import, rather than several times for every domain/label.
	let server_re = /^server=\/([^/]+)\/(#?)$/, hosts_re = /^(127\.0\.0\.1|0\.0\.0\.0|::)[[:space:]]+([^ ]+)$/;
	let unbound_re = /^local-zone:[[:space:]]*"([^"]+)\."[[:space:]]+always_nxdomain$/, domain_re = /^[a-z0-9][a-z0-9.-]*[a-z0-9]$/;
	for (let line in split(raw, '\n')) {
		line = trim(line);
		if (!length(line) || substr(line, 0, 1) == '#') continue;
		let m;
		if (mode == 'dnsmasq.servers') {
			m = match(line, server_re);
			if (!m) die('Unexpected dnsmasq.servers record');
			if (m[2] == '#') { push(allowed, lc(m[1])); continue; }
			line = m[1];
		} else if (mode == 'dnsmasq.addnhosts') {
			m = match(line, hosts_re);
			if (!m) die('Unexpected hosts record');
			line = m[2];
		} else if (mode == 'unbound.adb_list') {
			m = match(line, unbound_re);
			if (!m) die('Unexpected Unbound record');
			line = m[1];
		} else if (mode != 'smartdns.domainset') die('Unsupported rule export mode');
		line = lc(line);
		if (length(line) > 253 || !match(line, domain_re) || index(line, '.') < 1 || index(line, '..') >= 0)
			die('Invalid processed domain');
		for (let label in split(line, '.')) if (length(label) > 63 || substr(label, 0, 1) == '-' || substr(label, -1) == '-') die('Invalid domain label');
		values[line] = true;
	}
	let result = sort(keys(values));
	if(!length(result))die('Empty processed blocklist');
	if(length(result)>500000)die('Processed blocklist exceeds domain limit');
	for (let allow in allowed) {
		let parent = allow;
		while (index(parent, '.') >= 0) {
			if (values[parent]) die('Overlapping allow exceptions require a dedicated adapter policy');
			parent = substr(parent, index(parent, '.') + 1);
		}
	}
	return result;
};

function varint(number) {
	let output = '';
	while (true) { let byte = number % 128; number = int(number / 128); output += chr(byte + (number ? 128 : 0)); if (!number) break; }
	return output;
}
function field(number, value) { return chr(number * 8 + 2) + varint(length(value)) + value; }
export function geosite(list) {
	let parts = [field(1, 'ADZERO')];
	for (let domain in list) push(parts, field(2, chr(8) + chr(2) + field(2, domain)));
	return field(1, join('', parts));
};

export const begin = '# ADZERO MANAGED BEGIN v1';
export const end = '# ADZERO MANAGED END v1';
export function strip_block(text) {
	let start = index(text, begin), finish = index(text, end);
	if (start < 0 && finish < 0) return text;
	if (start < 0 || finish < start || index(substr(text, start + length(begin)), begin) >= 0) die('Managed block is damaged or duplicated');
	finish += length(end);
	if (substr(text, finish, 1) == '\n') finish++;
	return substr(text, 0, start) + substr(text, finish);
};
export function block(text) { return begin + '\n' + text + '\n' + end + '\n'; };

export function dae_dns(raw) {
	if (index(raw, begin) >= 0) {
		strip_block(raw); // validate both markers before accepting an existing rule
		if (index(raw, block('qname(ext:"adzero-geosite.dat:adzero") -> reject')) < 0) die('Managed NaiLink DNS block was edited');
		return raw;
	}
	let text = strip_block(raw), tokens = [], quote = '', comment = false, stack = [], word = '';
	for (let i = 0; i < length(text); i++) {
		let c = substr(text, i, 1);
		if (comment) { if (c == '\n') comment = false; continue; }
		if (quote) { if (c == '\\') { i++; continue; } if (c == quote) quote = ''; continue; }
		if (c == '#') { comment = true; continue; }
		if (c == '"' || c == "'") { quote = c; continue; }
		if (match(c, /[a-zA-Z_]/)) { word += c; continue; }
		if (c == '{') {
			push(stack, word);
			if (word == 'request' && length(stack) >= 2 && stack[length(stack)-2] == 'routing') push(tokens, i + 1);
		} else if (c == '}') pop(stack);
		if (!match(c, /[[:space:]]/)) word = ''; else if (word != 'request' && word != 'routing') word = '';
	}
	if (length(tokens) != 1) die('Expected one DNS routing.request block');
	let position = tokens[0];
	return substr(text, 0, position) + '\n' + block('qname(ext:"adzero-geosite.dat:adzero") -> reject') + substr(text, position);
};

export function mihomo(config, provider_path, remove) {
	let provider = 'adzero-dns', policy = 'rule-set:' + provider;
	config['rule-providers'] ??= {};
	config.dns ??= {};
	config.dns['nameserver-policy'] ??= {};
	config.rules ??= [];
	let rule = 'RULE-SET,' + provider + ',REJECT';
	let filter_rule = (config.dns['fake-ip-filter-mode'] == 'rule') ? 'RULE-SET,' + provider + ',real-ip' : 'rule-set:' + provider;
	if (remove) {
		delete config['rule-providers'][provider];
		delete config.dns['nameserver-policy'][policy];
		config.rules = filter(config.rules, value => value != rule);
		if (type(config.dns['fake-ip-filter']) == 'array')
			config.dns['fake-ip-filter'] = filter(config.dns['fake-ip-filter'], value => value != filter_rule);
	} else {
		if (config.dns['fake-ip-filter-mode'] && config.dns['fake-ip-filter-mode'] != 'blacklist' && config.dns['fake-ip-filter-mode'] != 'rule')
			die('Unsupported Fake-IP whitelist mode; refusing to change its meaning');
		config.dns['fake-ip-filter'] ??= [];
		config.dns['fake-ip-filter'] = [filter_rule, ...filter(config.dns['fake-ip-filter'], value => value != filter_rule)];
		config['rule-providers'][provider] = {type:'file', behavior:'domain', format:'text', path:provider_path};
		config.dns['nameserver-policy'][policy] = ['rcode://name_error'];
		config.rules = [rule, ...filter(config.rules, value => value != rule)];
	}
	return config;
};
