'use strict';
import * as fs from 'fs';
import { now, exchange } from './dns-io.uc';
import * as wire from './dns-enhance-lib.uc';
import * as route from './routing-lib.uc';
const errors=['dns_pool_bind_failed','dns_pool_runtime_failed'];
export function paths(p,plugin,mode,enabled){if(enabled===false)return {domestic:false,foreign:false};return {
	domestic:plugin=='nailink'?(p.strict===true||p.domestic.mode=='parallel'):plugin=='passwall'&&p.domestic.mode=='parallel',
	foreign:plugin=='nailink'?(p.strict===true||p.foreign.mode=='parallel'):plugin=='passwall'&&(p.foreign.mode=='parallel'||p.strict===true&&mode=='tcp')
};};
function responsive(raw){return raw!=null&&!(wire.u16(raw,2)&0x0200)&&(wire.u16(raw,2)&15)==0&&wire.u16(raw,6)>0;}
// Public names avoid a local synthetic .invalid NXDOMAIN masquerading as
// a working upstream. This checks reachability, not DNSSEC or pollution.
function question(group){return wire.question(group=='domestic'?'www.baidu.com':'www.google.com',int(now()*1000)%65536);}
export function preflight(profile,plugin,mode,ask){
	let p=route.profile(profile),used=paths(p,plugin,mode);ask??=exchange;
	if(plugin=='passwall'&&p.foreign.mode=='parallel'&&mode!='tcp')return {ready:false,reason:'dns_passwall_mode'};
	if(used.foreign&&!p.proxy_port)return {ready:false,reason:'dns_socks_required'};
	for(let group in ['domestic','foreign'])if(used[group]){
		let ok=false;
		for(let address in route.addresses(p,group)){
			let raw=ask(address,53,question(group),true,group=='foreign'?p.proxy_port:0);
			if(responsive(raw)){ok=true;break;}
		}
		if(!ok)return {ready:false,reason:'dns_pool_'+group+'_failed'};
	}
	return {ready:true};
};
export function probe(profile,plugin,mode,ports,ask){
	let used=paths(profile,plugin,mode);ask??=exchange;
	for(let group in ['domestic','foreign'])if(used[group]){
		let raw=ask('127.0.0.1',ports?.[group]??(group=='domestic'?5356:5357),question(group),true,0);
		if(!responsive(raw))return {ready:false,reason:'dns_pool_'+group+'_failed'};
	}
	return {ready:true};
};
export function inspect(root,expected,at){
	let path=(root??'')+'/tmp/adzero-dns-pool.json',s=fs.lstat(path),value;
	if(!s)return {ready:false,reason:'dns_pool_not_ready'};
	if(s.type!='file'||s.uid!=fs.stat('/proc/self')?.uid||(s.mode&0077)||s.size>10000)return {ready:false,reason:'dns_pool_state_invalid'};
	try{
		let raw=fs.readfile(path,10001),after=fs.lstat(path);
		if(raw==null||length(raw)>10000||after?.type!='file'||after.inode!=s.inode||after.uid!=s.uid||after.mode!=s.mode||after.size!=s.size)return {ready:false,reason:'dns_pool_state_invalid'};
		value=json(raw);
	}catch(e){return {ready:false,reason:'dns_pool_state_invalid'};}
	if(type(value)!='object'||index(['double','int'],type(value.updated))<0)return {ready:false,reason:'dns_pool_state_invalid'};
	if(value.profile!=expected)return {ready:false,reason:'dns_pool_profile_mismatch'};
	let age=(at??now())-value.updated;
	if(age<0||age>=3)return {ready:false,reason:'dns_pool_stale'};
	if(value.state=='error')return {ready:false,reason:index(errors,value.reason)>=0?value.reason:'dns_pool_runtime_failed',updated:value.updated,fatal:true};
	if(value.state!=null&&value.state!='ready')return {ready:false,reason:'dns_pool_state_invalid'};
	if(value.pid!=null){
		if(!match(value.pid,/^[1-9][0-9]*$/)||index(split(fs.readfile('/proc/'+value.pid+'/cmdline')??'','\x00'),'/usr/libexec/adzero/dns-pool.uc')<0)
			return {ready:false,reason:'dns_pool_process_exited'};
	}
	return {ready:true,updated:value.updated};
};
export function wait_ready(root,expected,requested,budget){
	let until=now()+(budget??3000)/1000.0,value;
	while(true){
		value=inspect(root,expected);
		// Include a last deadline check, but never accept a receipt produced
		// after that deadline or a previous attempt's short-lived error.
		if(value.ready&&value.updated<=until)return value;
		if(value.fatal&&value.updated>=requested)return value;
		let left=until-now();if(left<=0)break;
		// ucode sleep uses milliseconds; BusyBox fractional sleep is optional.
		sleep(min(100,max(1,int(left*1000)+1)));
	}
	return {ready:false,reason:value.ready?'dns_pool_not_ready':value.reason};
};
export function publish(profile,state,reason){
	let pid=fs.readlink('/proc/self'),path='/tmp/adzero-dns-pool.json',tmp=path+'.'+pid;
	if(!match(pid??'',/^[1-9][0-9]*$/))return false;
	let f=fs.open(tmp,'wx',0600),raw=sprintf('%J',{profile,updated:now(),state,pid,...(state=='error'?{reason:index(errors,reason)>=0?reason:'dns_pool_runtime_failed'}:{})});
	if(!f)return false;
	let written=f.write(raw),closed=f.close();
	if(written!=length(raw)||!closed||!fs.rename(tmp,path)){fs.unlink(tmp);return false;}return true;
};
