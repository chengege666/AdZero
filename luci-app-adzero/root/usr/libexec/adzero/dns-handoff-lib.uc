'use strict';
// Conservative DNS-only conntrack planner. No shell commands or writes here.
function ipv4(value) {
	if(type(value)!='string')return null;
	let parts=split(value,'.');if(length(parts)!=4)return null;
	let n=0;
	for(let p in parts){if(!match(p,/^(0|[1-9][0-9]{0,2})$/)||int(p)>255)return null;n=n*256+int(p);}
	return n;
}
export function lan_valid(lan) {
	return type(lan)=='object'&&ipv4(lan.address)!=null&&type(lan.mask)=='int'&&lan.mask>=8&&lan.mask<=30&&
		type(lan.device)=='string'&&!!match(lan.device,/^[a-zA-Z0-9_.:-]{1,32}$/);
};
export function same_lan(address,lan) {
	let a=ipv4(address),router=ipv4(lan.address);if(a==null||router==null)return false;
	let size=2**(32-lan.mask),network=int(router/size)*size;
	return a>network&&a<network+size-1&&a!=router;
};
export function target(data, port) {
	if(type(port)!='int'||port<1024||port>65535||type(data?.nftables)!='array')return false;
	let rules=[],chain=false;
	for(let item in data.nftables){
		if(item.metainfo)continue;
		if(item.chain){let c=item.chain;if(c.family!='inet'||c.table!='passwall'||c.name!='PSW_DNS')return false;chain=true;continue;}
		if(!item.rule)return false;
		let r=item.rule;if(r.family!='inet'||r.table!='passwall'||r.chain!='PSW_DNS')return false;
		push(rules,r);
	}
	// ACL-specific, bypass or unknown expressions require native-plugin review.
	if(!chain||length(rules)!=2)return false;
	let protocols={};
	for(let r in rules){
		let protocol=null,redirect=false,dport=false;
		for(let e in r.expr??[]){
			if(e.counter)continue;
			if(e.match){let m=e.match,p=m.left?.payload;
				if(p&&p.field=='dport'&&index(['udp','tcp'],p.protocol)>=0&&m.op=='=='&&m.right==53){if(dport||protocol&&protocol!=p.protocol)return false;protocol=p.protocol;dport=true;continue;}
				if(m.left?.meta?.key=='l4proto'&&m.op=='=='&&index(['udp','tcp'],m.right)>=0){if(protocol&&protocol!=m.right)return false;protocol=m.right;continue;}
				return false;
			}
			if(e.redirect&&e.redirect.port==port&&length(keys(e.redirect))==1&&!redirect){redirect=true;continue;}
			return false;
		}
		if(!protocol||!dport||!redirect||protocols[protocol])return false;
		protocols[protocol]=true;
	}
	return protocols.udp===true&&protocols.tcp===true;
};
export function dispatch(data) {
	// Require the native prerouting jump, not merely an orphaned PSW_DNS.
	let chain=false;
	for(let item in data?.nftables??[]){
		if(item.metainfo)continue;
		if(item.chain){let c=item.chain;chain=c.family=='inet'&&c.table=='passwall'&&c.name=='dstnat'&&c.type=='nat'&&c.hook=='prerouting';if(!chain)return false;continue;}
		let r=item.rule;if(!chain||r?.family!='inet'||r.table!='passwall'||r.chain!='dstnat')return false;
		let source=false,local=false,jump=false,v6=false;
		for(let e in r.expr??[]){
			if(e.counter)continue;
			let m=e.match,p=m?.left?.payload;
			if(m?.op=='=='&&p?.protocol=='ip6'){v6=true;continue;}
			if(m?.op=='=='&&p?.protocol=='ip'&&p.field=='saddr'&&m.right=='@psw_lan'&&!source){source=true;continue;}
			if(m?.op=='=='&&p?.protocol=='ip'&&p.field=='daddr'&&m.right=='@psw_local'&&!local){local=true;continue;}
			if(e.jump?.target=='PSW_DNS'&&!jump){jump=true;continue;}
			return false;
		}
		if(v6&&!source)continue;
		if(source&&jump)return true;
		return false;
	}
	return false;
};
export function parse(line) {
	if(type(line)!='string'||length(line)>4096||!match(line,/(^|[[:space:]])udp[[:space:]]+17[[:space:]]/))return null;
	let tokens=split(trim(line),/[[:space:]]+/),fields={src:[],dst:[],sport:[],dport:[]},zone='0',id=null,zone_seen=false;
	for(let token in tokens){let p=split(token,'=');if(length(p)!=2)continue;
		if(fields[p[0]]!=null)push(fields[p[0]],p[1]);
		else if(p[0]=='zone'){if(zone_seen||!match(p[1],/^[0-9]+$/))return null;zone=p[1];zone_seen=true;}
		else if(p[0]=='id'){if(id!=null||!match(p[1],/^[0-9]+$/))return null;id=p[1];}
	}
	if(zone!='0'||!id)return null;
	for(let k in keys(fields))if(length(fields[k])!=2)return null;
	for(let key in ['src','dst'])for(let v in fields[key])if(ipv4(v)==null)return null;
	for(let key in ['sport','dport'])for(let v in fields[key])if(!match(v,/^[1-9][0-9]{0,4}$/)||int(v)>65535)return null;
	return {src:fields.src[0],dst:fields.dst[0],sport:fields.sport[0],dport:fields.dport[0],
		reply_src:fields.src[1],reply_dst:fields.dst[1],reply_sport:fields.sport[1],reply_dport:fields.dport[1],id};
};
export function plan(raw,lan,port) {
	if(!lan_valid(lan)||type(raw)!='string'||length(raw)>1048576)return null;
	let lines=split(trim(raw),'\n');if(length(lines)>4096)return null;
	let result=[];
	for(let line in lines){let c=parse(line);if(!c)continue;
		if(c.dst!=lan.address||!same_lan(c.src,lan)||c.dport!='53'||c.reply_src!=lan.address||c.reply_dst!=c.src||
			c.reply_dport!=c.sport||int(c.reply_sport)==port)continue;
		push(result,c);if(length(result)>128)return null;
	}
	return result;
};
export function deletion(c) {
	// BOTH directions and zone protect a newly correct NAT replacement.
	// Do not pass --id: conntrack-tools 1.4.8 crashes on this delete filter.
	return ['-D','-f','ipv4','-p','udp','--orig-src',c.src,'--orig-dst',c.dst,'--sport',c.sport,'--dport','53',
		'--reply-src',c.reply_src,'--reply-dst',c.reply_dst,'--reply-port-src',c.reply_sport,'--reply-port-dst',c.reply_dport,'--zone','0'];
};
