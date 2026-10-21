'use strict';

// Input is data. Never resolve or fetch a user-supplied URL.
export function hostname(value) {
	if (type(value) != 'string' || length(value) > 2048) die('请输入域名或 HTTP/HTTPS 网址。');
	let name = lc(trim(value));
	if (match(name, /^https?:\/\//)) {
		name = split(substr(name, index(name, '://') + 3), /[\/?#]/)[0];
		name = replace(name, /:[0-9]+$/, '');
	}
	name = replace(name, /\.$/, '');
	if (length(name) > 253 || index(name, '.') < 1 || match(name, /^[0-9.]+$/) ||
		!match(name, /^[a-z0-9][a-z0-9.-]*[a-z0-9]$/) || index(name, '..') >= 0)
		die('请输入有效域名；不支持 IP、通配符或带账号密码的网址。');
	for (let label in split(name, '.')) if (length(label) > 63 || substr(label, 0, 1) == '-' || substr(label, -1) == '-')
		die('域名标签无效。');
	return name;
};
export function covers(parent, name) { return name == parent || substr(name, -length(parent)-1) == '.' + parent; };
export function list(value) {
	if (value == null) return [];
	if (type(value) == 'string') value = [value];
	if (type(value) != 'array' || length(value) > 100) die('个人放行名单无效或超过 100 项。');
	let result = [];
	for (let item in value) { item = hostname(item); if (index(result, item) < 0) push(result, item); }
	return sort(result);
};
export function lookup(domain, rules, allowed, suffix) {
	domain = hostname(domain);
	for (let item in allowed) if (covers(item, domain)) return {domain, match:'allowed', rule:item, scope:item};
	let found = null;
	for (let item in rules) if (item == domain || (suffix && covers(item, domain))) {
		// Choose the outermost *actual* blocker. Never guess a registrable domain.
		if (!found || length(item) < length(found)) found = item;
	}
	return {domain, match:found ? (found == domain ? 'exact' : 'parent') : 'none', rule:found, scope:found};
};
