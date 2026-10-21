'use strict';
import { hostname } from './policy-lib.uc';

export const catalog = [
	{id:'hagezi-light',name:'HaGeZi Light',group:'综合过滤',format:'domains',description:'轻量广告与跟踪过滤；同系列通常选择一项即可。',home:'https://github.com/hagezi/dns-blocklists',url:'https://raw.githubusercontent.com/hagezi/dns-blocklists/main/wildcard/light-onlydomains.txt'},
	{id:'hagezi-normal',name:'HaGeZi Normal',group:'综合过滤',format:'domains',description:'比 Light 覆盖更多域名，内存占用和误拦截概率也会增加。',home:'https://github.com/hagezi/dns-blocklists',url:'https://raw.githubusercontent.com/hagezi/dns-blocklists/main/wildcard/multi-onlydomains.txt'},
	{id:'hagezi-pro',name:'HaGeZi Pro',group:'综合过滤',format:'domains',description:'更广的广告与跟踪覆盖；适合愿意管理放行名单的用户。',home:'https://github.com/hagezi/dns-blocklists',url:'https://raw.githubusercontent.com/hagezi/dns-blocklists/main/wildcard/pro-onlydomains.txt'},
	{id:'anti-ad',name:'anti-AD',group:'中文与通用',format:'domains',description:'面向中文使用场景的广告与隐私域名列表。',home:'https://github.com/privacy-protection-tools/anti-AD',url:'https://raw.githubusercontent.com/privacy-protection-tools/anti-AD/master/anti-ad-domains.txt'},
	{id:'adaway',name:'AdAway',group:'轻量过滤',format:'hosts',description:'移动广告及部分统计服务的 hosts 列表。',home:'https://github.com/AdAway/adaway.github.io',url:'https://raw.githubusercontent.com/AdAway/adaway.github.io/master/hosts.txt'}
];
export function url(value) {
	if (type(value) == 'string' && match(value,/^https:\/\/[A-Za-z0-9.-]+(:443)?$/)) value += '/';
	if (type(value) != 'string' || length(value) > 2048 || !match(value,/^https:\/\/[A-Za-z0-9.-]+(:443)?\/[!-~]*$/) || (index(value,"\\") >= 0 || index(value,"#") >= 0)) die('请使用有效的 HTTPS 订阅地址，不支持账号密码、片段或非 443 端口。');
	hostname(replace(split(substr(value,8),'/')[0],/:443$/,''));
	return value;
};
export function title(value) {
	if (type(value) != 'string' || !length(trim(value)) || length(value) > 100 || match(value,/[[:cntrl:]]/)) die('规则名称应为 1–100 个字符。');
	return trim(value);
};
export function format(value) {
	if (index(['domains','hosts','adblock'],value) < 0) die('请选择域名、Hosts 或基础 DNS Adblock 格式。');
	return value;
};
export function parse(raw, kind) {
	format(kind);
	if (type(raw) != 'string' || length(raw) > 25000000) die('规则文件为空或超过 25 MB。');
	let names = {}, count=0;
	for (let line in split(raw,'\n')) {
		line = trim(replace(line,/^\xef\xbb\xbf/,''));
		if (!length(line) || substr(line,0,1) == '#' || substr(line,0,1) == '!' || match(line,/^\[Adblock( Plus)?( [0-9.]+)?\]$/)) continue;
		line = trim(replace(line,/[[:space:]]+#.*$/,''));
		if (kind == 'hosts') {
			let system=match(line,/^(\S+)\s+(localhost|localhost\.localdomain|local|broadcasthost|ip6-[a-z-]+|localhost6|localhost6\.localdomain6|0\.0\.0\.0)$/);
			if (system && index(['127.0.0.1','0.0.0.0','::1','255.255.255.255','fe80::1%lo0','ff00::0','ff02::1','ff02::2','ff02::3'],system[1]) >= 0) continue;
			let entry = match(line,/^(0\.0\.0\.0|127\.0\.0\.1|::|::1)[[:space:]]+([^[:space:]]+)$/);
			if (!entry) die('Hosts 需要每行一个 0.0.0.0 或回环地址与域名；不支持复杂别名。');
			line = entry[2];
			if (index(['localhost','localhost.localdomain','localhost6','localhost6.localdomain6','ip6-localhost','ip6-loopback'],line) >= 0) continue;
		} else if (kind == 'adblock') {
			let entry = match(line,/^\|\|([a-zA-Z0-9.-]+)\^$/);
			if (!entry) die('仅支持 ||domain^ 基础 DNS 规则；例外、修饰符、正则和网页元素规则不能导入。');
			line = entry[1];
		}
		let name;
		try { name = hostname(line); } catch(e) { die('规则包含不支持的内容，请检查所选格式。'); }
		if (!names[name]) { names[name]=true;count++; }
		if (count > 500000) die('单个列表超过 50 万个域名。');
	}
	let result = sort(keys(names));
	if (!length(result)) die('规则文件没有有效域名。');
	return result;
};
