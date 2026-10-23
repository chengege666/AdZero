'use strict';

const http_re = /^https?:\/\//, path_re = /[\/?#]/, port_re = /:[0-9]+$/, dot_re = /\.$/;
const numeric_re = /^[0-9.]+$/, domain_re = /^[a-z0-9][a-z0-9.-]*[a-z0-9]$/;

// Input is data. Never resolve or fetch a user-supplied URL.
export function hostname(value) {
	if (type(value) != 'string' || length(value) > 2048) die('请输入域名或 HTTP/HTTPS 网址。');
	let name = lc(trim(value));
	if (match(name, http_re)) {
		name = split(substr(name, index(name, '://') + 3), path_re)[0];
		name = replace(name, port_re, '');
	}
	name = replace(name, dot_re, '');
	if (length(name) > 253 || index(name, '.') < 1 || match(name, numeric_re) ||
		!match(name, domain_re) || index(name, '..') >= 0)
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
export function controls(raw) {
	if(type(raw)!='string'||length(raw)>100000)die('访问控制内容无效或过大。');
	let p;try{p=json(raw);}catch(e){die('访问控制内容不是有效 JSON。');}
	for(let part in ['before','after']){
		if(type(p?.[part])!='object'||type(p[part].allowed)!='array'||type(p[part].blocked)!='array')die('访问控制名单不完整。');
		p[part]={allowed:list(p[part].allowed),blocked:list(p[part].blocked)};
	}
	for(let a in p.after.allowed)for(let b in p.after.blocked)if(covers(a,b)||covers(b,a))die('放行与拦截的域名范围重叠，请先移除冲突规则。');
	return {before:p.before,after:p.after};
};
export function lookup(domain, rules, allowed, suffix, ordered) {
	domain = hostname(domain);
	for (let item in allowed) if (covers(item, domain)) return {domain, match:'allowed', rule:item, scope:item};
	let found = null;
	if(ordered){
		// Processed-rule imports are sorted by adapter-lib.domains(). Search
		// only the exact name and its actual ancestors, without another map.
		for(let candidate=domain;index(candidate,'.')>=0;candidate=substr(candidate,index(candidate,'.')+1)){
			let low=0,high=length(rules)-1;
			while(low<=high){let mid=int((low+high)/2),value=rules[mid];if(value==candidate){found=candidate;break;}if(value<candidate)low=mid+1;else high=mid-1;}
			if(!suffix)break;
		}
	}else for (let item in rules) if (item == domain || (suffix && covers(item, domain))) {
		// Choose the outermost *actual* blocker. Never guess a registrable domain.
		if (!found || length(item) < length(found)) found = item;
	}
	return {domain, match:found ? (found == domain ? 'exact' : 'parent') : 'none', rule:found, scope:found};
};
