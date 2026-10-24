'use strict';
// Native DNS bridges. Never choose a new upstream or disable Fake-IP.
import { lan_valid } from './dns-handoff-lib.uc';
import * as wire from './dns-enhance-lib.uc';
const start='# ADZERO ALIAS BRIDGE BEGIN v1',end='# ADZERO ALIAS BRIDGE END v1';
export function strip_dns(text,prior){
	if(!prior)return text;let prefix='bind: "tcp+udp://'+prior.lan.address+':5355"\n';
	if(substr(text,0,length(prefix))!=prefix)die('native_bind_changed');return substr(text,length(prefix));
};
export function strip_routing(text,prior){
	if(!prior)return text;let position=index(text,end+'\n');
	if(substr(text,0,length(start))!=start||position<0)die('native_routing_changed');return substr(text,position+length(end)+1);
};
export function nai_dns(text,lan){
	if(!lan_valid(lan)||type(text)!='string')die('native_lan');
	// An existing listener belongs to the user. Do not replace or reinterpret it.
	if(match(text,/(^|\n)[ \t]*bind[ \t]*:/))die('native_bind_owned');
	return 'bind: "tcp+udp://'+lan.address+':5355"\n'+text;
};
export function nai_routing(text,lan){
	if(!lan_valid(lan)||type(text)!='string'||index(text,start)>=0||index(text,end)>=0)die('native_routing');
	// must_direct is required: dae otherwise diverts UDP/53 before nft NAT.
	// Only DNS addressed to this LAN router leaves the native eBPF path.
	return start+'\nsip('+lan.address+'/'+lan.mask+') && dip('+lan.address+') && dport(53) -> must_direct\n'+end+'\n'+text;
};
export function mihomo(config,lan){
	if(!lan_valid(lan)||config?.dns?.enable!==true||config.tun?.enable===true)die('native_mihomo_path');
	let listen=match(config.dns.listen??'',/^(127[.]0[.]0[.]1|0[.]0[.]0[.]0|\*|192[.]168[.][0-9.]+|10[.][0-9.]+|172[.][0-9.]+)?:([0-9]+)$/);
	if(!listen||int(listen[2])<1024||int(listen[2])>65535||index([5354,5355],int(listen[2]))>=0)die('native_mihomo_listener');
	let host=listen[1]??'0.0.0.0';if(host!='127.0.0.1'&&host!='0.0.0.0'&&host!='*'&&host!=lan.address)die('native_mihomo_address');
	let result={plugin:'openclash',lan,port:int(listen[2]),upstream_address:host=='127.0.0.1'?host:lan.address};
	if(config.dns['enhanced-mode']=='fake-ip'){
		let control=match(config['external-controller']??'',/^(127[.]0[.]0[.]1|0[.]0[.]0[.]0|\*|192[.]168[.][0-9.]+|10[.][0-9.]+|172[.][0-9.]+)?:([0-9]+)$/);
		if(!control||int(control[2])<1024||int(control[2])>65535)die('native_mihomo_controller');
		let address=control[1]??'0.0.0.0';if(address!='127.0.0.1'&&address!='0.0.0.0'&&address!='*'&&address!=lan.address)die('native_mihomo_controller');
		let secret=config.secret??'';if(type(secret)!='string'||length(secret)>512)die('native_mihomo_secret');
		for(let i=0;i<length(secret);i++)if(ord(secret,i)<32||ord(secret,i)==127)die('native_mihomo_secret');
		result.inspector={address:address=='0.0.0.0'||address=='*'?'127.0.0.1':address,port:int(control[2]),secret};
	}
	return result;
};
function domain(raw){
	if(type(raw)!='string')die('native_alias_name');
	let n=lc(replace(raw,/[.]$/,'')),parts=split(n,'.');if(!length(n)||length(n)>253)die('native_alias_name');
	for(let p in parts)if(!length(p)||length(p)>63||!match(p,/^[a-z0-9_-]+$/))die('native_alias_name');
	return n;
}
function encode(n){let raw='';for(let p in split(n,'.'))raw+=chr(length(p))+p;return raw+'\x00';}
export function api_answer(query,value){
	let q=wire.message(query),question=value?.Question;
	if(type(value)!='object'||length(question??[])!=1||domain(question[0].Name)!=q.name||question[0].Qtype!=q.kind||question[0].Qclass!=1||type(value.Status)!='int'||value.Status<0||value.Status>15||type(value.TC)!='bool')die('native_alias_question');
	let records=[];
	if(type(value.Answer??[])!='array'||length(value.Answer??[])>512)die('native_alias_records');
	for(let rr in value.Answer??[]){
		let target=null,kind=rr.type;
		if(kind==5)target=domain(trim(rr.data??''));
		else if(kind==q.kind&&index([64,65],kind)>=0){
			let parts=split(trim(rr.data??''),/[ \t]+/);if(parts[0]=='0'&&parts[1]!='.')target=domain(parts[1]);
		}
		if(target){let data=(kind==5?'':'\x00\x00')+encode(target);push(records,encode(domain(rr.name))+wire.word(kind)+'\x00\x01\x00\x00\x00\x00'+wire.word(length(data))+data);}
	}
	return substr(query,0,2)+wire.word(0x8180|(value.TC?0x0200:0)|value.Status)+'\x00\x01'+wire.word(length(records))+'\x00\x00\x00\x00'+substr(query,12,q.end-12)+join('',records);
};
