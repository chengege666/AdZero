'use strict';
// Bounded DNS wire reader and policy. Pure functions, also used by native tests.
import { hostname, list, covers } from './policy-lib.uc';
export function u16(s,n){if(n<0||n+2>length(s))die('short_dns');return ord(s,n)*256+ord(s,n+1);};
export function word(n){return chr(int(n/256))+chr(n%256);};
export function name(s,start){
	let p=start,end=null,parts=[],seen={};
	for(let i=0;i<128;i++){
		if(p>=length(s)||seen[p])die('dns_name');seen[p]=true;let n=ord(s,p++);
		if(!n){let value=lc(join('.',parts));if(length(value)>253)die('dns_name');return {value,end:end??p};}
		if((n&192)==192){if(p>=length(s))die('dns_pointer');end??=p+1;p=((n&63)*256)+ord(s,p);continue;}
		if(n>63||p+n>length(s))die('dns_label');let label=substr(s,p,n);if(!match(label,/^[A-Za-z0-9_-]+$/))die('dns_label');push(parts,label);p+=n;
	}die('dns_depth');
};
export function message(raw){
	if(type(raw)!='string'||length(raw)<12||length(raw)>65535||u16(raw,4)!=1)die('dns_message');
	let q=name(raw,12),end=q.end+4,flags=u16(raw,2),kind=u16(raw,q.end),cls=u16(raw,q.end+2),records=[],p=end;
	if(flags&0x7800||cls!=1||!q.value)die('dns_question');
	let answer=u16(raw,6),count=answer+u16(raw,8)+u16(raw,10);if(count>512)die('dns_records');
	for(let i=0;i<count;i++){
		let owner=name(raw,p);p=owner.end;let type=u16(raw,p),class_=u16(raw,p+2),size=u16(raw,p+8);p+=10;
		if(p+size>length(raw))die('dns_record');
		if(i<answer&&class_==1&&type==5){let target=name(raw,p);if(target.end!=p+size)die('dns_cname');push(records,{owner:owner.value,target:target.value});}
		p+=size;
	}
	if(p!=length(raw))die('dns_trailing');
	return {id:u16(raw,0),name:q.value,kind,flags,end,response:!!(flags&0x8000),records};
};
export function reply(query,rcode){
	let q=message(query),flags=0x8080|(q.flags&0x0110)|(rcode??0);
	// Synthetic answers are not authenticated, authoritative, or cacheable.
	return substr(query,0,2)+word(flags)+'\x00\x01\x00\x00\x00\x00\x00\x00'+substr(query,12,q.end-12);
};
export function question(domain,id){
	let wire='';for(let label in split(hostname(domain),'.'))wire+=chr(length(label))+label;
	return word(id??1)+'\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00'+wire+'\x00\x00\x01\x00\x01';
};
export function config(value){
	value??={};if(type(value)!='object')die('DNS 增强设置无效。');
	for(let k in ['enabled','cname','failover'])if(value[k]!=null&&type(value[k])!='bool')die('增强开关需要明确的开关值。');
	let devices=[],seen={};
	if(value.devices!=null&&type(value.devices)!='array'||length(value.devices??[])>32)die('最多设置 32 个设备。');
	for(let d in value.devices??[]){
		if(type(d)!='object'||d.enabled!=null&&type(d.enabled)!='bool')die('设备开关无效。');
		if(type(d.ip)!='string'||!match(d.ip,/^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)/))die('设备使用明确的局域网 IPv4 地址。');
		let parts=split(d.ip,'.');if(length(parts)!=4||length(filter(parts,p=>!match(p,/^(0|[1-9][0-9]{0,2})$/)||int(p)>255)))die('设备 IP 无效。');
		if(seen[d.ip])die('设备 IP 不能重复。');seen[d.ip]=true;
		if(type(d.name??'')!='string'||length(d.name??'')>40)die('设备名称最多 40 字符。');
		let allowed=list(d.allowed),blocked=list(d.blocked);if(length(allowed)>32||length(blocked)>32)die('每个设备每类最多 32 项。');
		push(devices,{ip:d.ip,name:d.name??'',enabled:d.enabled!==false,allowed,blocked});
	}
	let proxy=value.proxy_port??0;if(type(proxy)!='int'||proxy!=0&&(proxy<1024||proxy>65535))die('SOCKS 端口需为 1024–65535；留空停用国外探测。');
	return {enabled:value.enabled===true,cname:value.cname!==false,failover:value.failover===true,proxy_port:proxy,devices};
};
function scope(rows,domain){for(let n in rows??[])if(covers(n,domain))return n;return null;}
export function decision(query,response,rules,allowed,device,cname){
	let q=message(query);if(q.response)die('dns_response_as_query');
	// An upstream/global block cannot be undone by a device exception.
	let exempt=scope(allowed,q.name)||device?.enabled&&scope(device.allowed,q.name);
	if(!exempt&&device?.enabled){let rule=scope(device.blocked,q.name);if(rule)return {blocked:true,kind:'device',rule};}
	if(!response||!cname||exempt)return {blocked:false};
	let r=message(response);if(!r.response||r.id!=q.id||r.name!=q.name||r.kind!=q.kind)die('dns_mismatch');
	if(r.flags&0x0200||(r.flags&15)!=0)return {blocked:false};
	let reachable={[q.name]:true};
	for(let i=0;i<32;i++){
		let changed=false;
		for(let rr in r.records)if(reachable[rr.owner]&&!reachable[rr.target]){
			changed=true;reachable[rr.target]=true;
			for(let n=rr.target;index(n,'.')>=0;n=substr(n,index(n,'.')+1))
				if(rules[n]&&!scope(allowed,rr.target)&&!scope(device?.enabled?device.allowed:[],rr.target))return {blocked:true,kind:'cname',rule:n,alias:rr.target};
		}
		if(!changed)break;
	}
	return {blocked:false};
};
// Consecutive failures + hysteresis. Selection stays strictly within its group.
export function fallback(previous,group,results,now){
	let state=previous??{failures:0,last_switch:0};
	let current=filter(results,r=>r.address==group.active)[0];
	if(!current||current.skipped)return {...state,failures:0,next:null};
	let failures=current.ok?0:(state.failures??0)+1;
	let next=failures>=3&&(!state.last_switch||now-state.last_switch>=300)?filter(results,r=>r.ok&&index(group.servers,r.address)>=0&&r.address!=group.active)[0]?.address:null;
	return {failures:next?0:failures,last_switch:next?now:(state.last_switch??0),next};
};
