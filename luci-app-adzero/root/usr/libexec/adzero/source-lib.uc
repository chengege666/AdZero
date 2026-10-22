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
// Whole-page desired configuration. Revision checks remain server-side under
// ctl's lock; this validator is also used at the typed RPC boundary.
export function plan(raw) {
	if (type(raw) != 'string' || length(raw) > 100000) die('待应用内容无效或过大。');
	let p;
	try { p=json(raw); } catch(e) { die('待应用内容不是有效 JSON。'); }
	if (type(p) != 'object' || type(p.revision)!='string' || !match(p.revision,/^[a-f0-9]{64}$/) || type(p.routing_before) != 'bool' || type(p.routing_enabled) != 'bool' || type(p.items) != 'array' || length(p.items)>30) die('待应用配置无效，请重新读取。');
	let ids={},urls={},items=[];
	for(let item in p.items){
		if(type(item)!='object'||type(item.enabled)!='bool'||(item.id!=null&&(type(item.id)!='string'||!match(item.id,/^[A-Za-z0-9_]{1,80}$/))))die('待应用规则无效。');
		let id=item.id??null,name=title(item.name),address=item.url,kind=item.format;
		if(type(address)!='string'||length(address)>2048||!length(address)||match(address,/[[:cntrl:]]/))die('规则地址无效。');
		if(!id||item.enabled)address=url(address);
		if(kind!='unknown'||!id)format(kind);
		if((id&&ids[id])||urls[address])die('待应用规则中存在重复项。');
		if(id)ids[id]=true;urls[address]=true;
		push(items,{id,name,url:address,format:kind,enabled:item.enabled});
	}
	return {revision:p.revision,routing_before:p.routing_before,routing_enabled:p.routing_enabled,items};
};
export function parse(raw, kind) {
	format(kind);
	if (type(raw) != 'string' || length(raw) > 25000000) die('规则文件为空或超过 25 MB。');
	let names = {}, count=0;
	let bom_re=/^\xef\xbb\xbf/, header_re=/^\[Adblock( Plus)?( [0-9.]+)?\]$/, comment_re=/[[:space:]]+#.*$/;
	let system_re=/^(\S+)\s+(localhost|localhost\.localdomain|local|broadcasthost|ip6-[a-z-]+|localhost6|localhost6\.localdomain6|0\.0\.0\.0)$/;
	let hosts_re=/^(0\.0\.0\.0|127\.0\.0\.1|::|::1)[[:space:]]+([^[:space:]]+)$/, adblock_re=/^\|\|([a-zA-Z0-9.-]+)\^$/;
	for (let line in split(raw,'\n')) {
		line = trim(replace(line,bom_re,''));
		if (!length(line) || substr(line,0,1) == '#' || substr(line,0,1) == '!' || match(line,header_re)) continue;
		line = trim(replace(line,comment_re,''));
		if (kind == 'hosts') {
			let system=match(line,system_re);
			if (system && index(['127.0.0.1','0.0.0.0','::1','255.255.255.255','fe80::1%lo0','ff00::0','ff02::1','ff02::2','ff02::3'],system[1]) >= 0) continue;
			let entry = match(line,hosts_re);
			if (!entry) die('Hosts 需要每行一个 0.0.0.0 或回环地址与域名；不支持复杂别名。');
			line = entry[2];
			if (index(['localhost','localhost.localdomain','localhost6','localhost6.localdomain6','ip6-localhost','ip6-loopback'],line) >= 0) continue;
		} else if (kind == 'adblock') {
			let entry = match(line,adblock_re);
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
// Legacy backend subscriptions have no AdZero format field. Detect only our
// three strict formats; other native formats remain explicitly backend-only.
export function detect(raw) {
	if(type(raw)!='string'||length(raw)>25000000)die('规则文件为空或超过 25 MB。');
	for(let kind in ['domains','hosts','adblock']){
		try{return {format:kind,names:parse(raw,kind)};}
		catch(e){if(e.message=='单个列表超过 50 万个域名。')die(e);}
	}
	return null;
};
