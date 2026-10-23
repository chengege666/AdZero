'use strict';
import * as fs from 'fs';
import * as net from 'socket';
import * as wire from './dns-enhance-lib.uc';
export function now(){let t=clock(true);if(!t)die('monotonic_clock_unavailable');return t[0]+t[1]/1000000000.0;};
let idle=null;
export function wait(milliseconds){
	// OpenWrt 24.10's socket module has no pair(). Poll a quiet loopback
	// socket with no requested events, without blocking any DNS socket.
	if(!idle){idle=net.create(net.AF_INET,net.SOCK_DGRAM|net.SOCK_NONBLOCK);if(!idle||!idle.bind({address:'127.0.0.1',port:0}))die('dns_timer');}
	net.poll(milliseconds,[idle,0]);
};
function ready(s,flags,until){let ms=int((until-now())*1000);return ms>0&&length(filter(net.poll(ms,[s,flags])??[],e=>e[1]!=0))>0;}
function send(s,data,until){while(length(data)){if(!ready(s,net.POLLOUT,until))die('dns_timeout');let n=s.send(data,net.MSG_DONTWAIT|net.MSG_NOSIGNAL);if(n==null||n<=0)die('dns_send');data=substr(data,n);}}
function read(s,size,until){let data='';while(length(data)<size){if(!ready(s,net.POLLIN,until))die('dns_timeout');let part=s.recv(size-length(data),net.MSG_DONTWAIT);if(!length(part))die('dns_read');data+=part;}return data;}
// Numeric endpoints only: no dependency on the DNS path being tested.
export function exchange(address,port,query,tcp,proxy_port){
	let until=now()+2,s=null;
	try{
		s=net.connect({address:proxy_port?'127.0.0.1':address,port:proxy_port||port},null,{socktype:tcp?net.SOCK_STREAM:net.SOCK_DGRAM},500);
		if(!s)die('dns_connect');
		if(proxy_port){
			send(s,'\x05\x01\x00',until);if(read(s,2,until)!='\x05\x00')die('socks_auth');
			let ip=net.sockaddr({address,port});if(!ip)die('dns_address');
			let octets=iptoarr(address),v6=index(address,':')>=0,bytes='';
			for(let v in octets)bytes+=v6?wire.word(v):chr(v);
			send(s,'\x05\x01\x00'+chr(v6?4:1)+bytes+wire.word(port),until);
			let h=read(s,4,until);if(substr(h,0,3)!='\x05\x00\x00')die('socks_connect');
			let n=ord(h,3)==1?4:ord(h,3)==4?16:ord(h,3)==3?ord(read(s,1,until)):0;if(!n)die('socks_address');read(s,n+2,until);
		}
		send(s,tcp?wire.word(length(query))+query:query,until);
		let response=tcp?read(s,wire.u16(read(s,2,until),0),until):ready(s,net.POLLIN,until)?s.recv(65535,net.MSG_DONTWAIT):null;
		let q=wire.message(query),r=wire.message(response);
		if(!r.response||r.id!=q.id||r.name!=q.name||r.kind!=q.kind)die('dns_mismatch');
		s.close();return response;
	}catch(e){if(s)s.close();return null;}
};
export function test(address,foreign,proxy_port){
	if(foreign&&!proxy_port)return {address,ok:false,skipped:true,reason:'proxy_endpoint_required',ms:null};
	let start=now(),r=exchange(address,53,wire.question(foreign?'www.google.com':'www.baidu.com',int(start*100)%65536),foreign,foreign?proxy_port:0);
	let ok=r!=null&&(wire.u16(r,2)&15)==0&&wire.u16(r,6)>0;
	return {address,ok,ms:ok?int((now()-start)*10000)/10.0:null,path:foreign?'socks5_tcp':'direct_udp'};
};
