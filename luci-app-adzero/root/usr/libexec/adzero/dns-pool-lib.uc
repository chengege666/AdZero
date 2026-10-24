'use strict';
import * as net from 'socket';
import * as wire from './dns-enhance-lib.uc';
import { now } from './dns-io.uc';
// Loopback only, no cache. Native proxy DNS retains domain mapping and TTLs.
// TCP upstreams avoid a transparent proxy's UDP DNS interception loop.
export function pool(groups,ports,options){
	options??={};
	let listeners=[],clients=[],requests=[];
	function close(){for(let l in listeners){l.udp.close();l.tcp.close();}for(let c in clients)c.socket.close();for(let r in requests)for(let a in r.attempts)a.socket?.close();listeners=[];clients=[];requests=[];}
	try{for(let group in options.domains?['domestic','foreign','split']:['domestic','foreign']){
		let port=ports?.[group]??(group=='domestic'?5356:group=='foreign'?5357:5358),udp=net.create(net.AF_INET,net.SOCK_DGRAM|net.SOCK_NONBLOCK),tcp=net.create(net.AF_INET,net.SOCK_STREAM|net.SOCK_NONBLOCK);
		tcp?.setopt(net.SOL_SOCKET,net.SO_REUSEADDR,1);
		if(!udp||!tcp||!udp.bind({address:'127.0.0.1',port})||!tcp.bind({address:'127.0.0.1',port})||!tcp.listen(32)){udp?.close();tcp?.close();die('pool_bind');}
		push(listeners,{group,udp,tcp});
	}}catch(e){close();die(e);}
	function deliver(r,raw){if(r.client){r.client.output+=wire.word(length(raw))+raw;r.client.waiting=false;r.client.at=now();}else r.listener.udp.send(raw,net.MSG_DONTWAIT|net.MSG_NOSIGNAL,r.peer);r.dead=true;}
	function begin(raw,listener,peer,client){
		let r={raw,listener,peer,client,at:now(),attempts:[]};
		try{let q=wire.message(raw);if(q.response||q.flags&0x0200)die('pool_query');if(client)client.waiting=true;
			if(length(requests)>=128){deliver(r,wire.reply(raw,2));return;}
			let group=listener.group;
			if(group=='split'){group='foreign';for(let name=q.name;length(name);){if(options.domains[name]){group='domestic';break;}let dot=index(name,'.');if(dot<0)break;name=substr(name,dot+1);}}
			for(let endpoint in groups[group]??[]){
				if(length(r.attempts)>=3)break;
				let address=type(endpoint)=='string'?endpoint:endpoint.address,port=type(endpoint)=='string'?53:endpoint.port;
				let proxy_port=group=='foreign'?options.proxy_port:0,s=net.create(proxy_port||index(address,':')<0?net.AF_INET:net.AF_INET6,net.SOCK_STREAM|net.SOCK_NONBLOCK);if(!s)continue;
				let connected=s.connect({address:proxy_port?'127.0.0.1':address,port:proxy_port||port});if(!connected&&s.error(true)!=115){s.close();continue;}
				push(r.attempts,{socket:s,stage:connected?(proxy_port?'hello-send':'send'):'connect',proxy_port,address,port,output:proxy_port?'\x05\x01\x00':wire.word(length(raw))+raw,buffer:'',dead:false});
			}if(!length(r.attempts))deliver(r,wire.reply(raw,2));else push(requests,r);
		}catch(e){for(let a in r.attempts)a.socket?.close();if(client)client.dead=true;}
	}
	function attempt(r,a,flags){let s=a.socket;
		if(a.stage=='connect'){if(s.getopt(net.SOL_SOCKET,net.SO_ERROR)!=0){a.dead=true;return;}a.stage=a.proxy_port?'hello-send':'send';}
		if(index(['hello-send','socks-send'],a.stage)>=0&&(flags&net.POLLOUT)){let n=s.send(a.output,net.MSG_DONTWAIT|net.MSG_NOSIGNAL);if(n>0){a.output=substr(a.output,n);if(!length(a.output)){a.stage=a.stage=='hello-send'?'hello-read':'socks-read';a.buffer='';}}else if(n!=null||s.error(true)!=11)a.dead=true;return;}
		if(index(['hello-read','socks-read'],a.stage)>=0&&(flags&(net.POLLIN|net.POLLHUP))){let p=s.recv(512,net.MSG_DONTWAIT);if(p==null){if(s.error(true)!=11)a.dead=true;return;}if(!length(p)){a.dead=true;return;}a.buffer+=p;
			if(a.stage=='hello-read'&&length(a.buffer)>=2){if(a.buffer!='\x05\x00'){a.dead=true;return;}let v6=index(a.address,':')>=0,bytes='';for(let v in iptoarr(a.address))bytes+=v6?wire.word(v):chr(v);a.output='\x05\x01\x00'+chr(v6?4:1)+bytes+wire.word(a.port);a.buffer='';a.stage='socks-send';}
			else if(a.stage=='socks-read'&&length(a.buffer)>=4){if(substr(a.buffer,0,3)!='\x05\x00\x00'){a.dead=true;return;}let type=ord(a.buffer,3);if(type==3&&length(a.buffer)<5)return;let size=type==1?10:type==4?22:type==3?7+ord(a.buffer,4):0;if(!size||length(a.buffer)>size){a.dead=true;return;}if(length(a.buffer)==size){a.output=wire.word(length(r.raw))+r.raw;a.buffer='';a.stage='send';}}
			return;
		}
		if(a.stage=='send'&&(flags&net.POLLOUT)){let n=s.send(a.output,net.MSG_DONTWAIT|net.MSG_NOSIGNAL);if(n>0){a.output=substr(a.output,n);if(!length(a.output))a.stage='read';}else if(n!=null||s.error(true)!=11)a.dead=true;}
		if(!a.dead&&a.stage=='read'&&(flags&(net.POLLIN|net.POLLHUP))){
			let part=s.recv(65537-length(a.buffer),net.MSG_DONTWAIT);if(part==null){if(s.error(true)!=11||flags&(net.POLLERR|net.POLLHUP))a.dead=true;}else if(!length(part))a.dead=true;else{
				a.buffer+=part;if(length(a.buffer)>=2&&length(a.buffer)>=wire.u16(a.buffer,0)+2){a.dead=true;
					try{let raw=substr(a.buffer,2,wire.u16(a.buffer,0)),q=wire.message(r.raw),v=wire.message(raw);
						if(!v.response||v.id!=q.id||v.name!=q.name||v.kind!=q.kind||v.flags&0x0200||index([0,3],v.flags&15)<0)die('pool_response');
						deliver(r,raw);
					}catch(e){} // A broken/failed peer never wins the race.
				}
			}
		}if(flags&(net.POLLERR|net.POLLHUP))a.dead=true;
	}
	function step(timeout){
		let watches=[];for(let l in listeners){push(watches,[l.udp,net.POLLIN,'udp',l]);push(watches,[l.tcp,net.POLLIN,'tcp',l]);}
		for(let c in clients)push(watches,[c.socket,length(c.output)?net.POLLOUT:c.waiting?0:net.POLLIN,'client',c]);
		for(let r in requests)for(let a in r.attempts)if(!a.dead)push(watches,[a.socket,index(['read','hello-read','socks-read'],a.stage)>=0?net.POLLIN:net.POLLOUT,'upstream',{r,a}]);
		for(let e in net.poll(timeout??100,...watches)??[]){let s=e[0],flags=e[1],kind=e[2],v=e[3];if(!flags)continue;
			if(kind=='udp'){let peer={},raw=s.recv(65535,net.MSG_DONTWAIT,peer);if(raw)begin(raw,v,peer,null);}
			else if(kind=='tcp'){let peer={},socket=s.accept(peer,net.SOCK_NONBLOCK);if(socket){if(length(clients)>=64)socket.close();else push(clients,{socket,peer,listener:v,buffer:'',output:'',at:now(),waiting:false});}}
			else if(kind=='client'){
				if(flags&net.POLLOUT){let n=s.send(v.output,net.MSG_DONTWAIT|net.MSG_NOSIGNAL);if(n>0){v.output=substr(v.output,n);v.at=now();}else if(n!=null)v.dead=true;}
				if(flags&net.POLLIN){let p=s.recv(65537-length(v.buffer),net.MSG_DONTWAIT);if(!length(p))v.dead=true;else{v.buffer+=p;v.at=now();}}
				if(flags&(net.POLLERR|net.POLLHUP))v.dead=true;
			}else if(!v.r.dead)attempt(v.r,v.a,flags);
		}
		for(let c in clients)if(!c.dead&&!c.waiting&&!length(c.output)&&length(c.buffer)>=2){let size=wire.u16(c.buffer,0);if(size<12)c.dead=true;else if(length(c.buffer)>=size+2){let q=substr(c.buffer,2,size);c.buffer=substr(c.buffer,size+2);begin(q,c.listener,c.peer,c);}}
		for(let r in requests){if(!r.dead&&(now()-r.at>=2||r.client?.dead||!length(filter(r.attempts,a=>!a.dead)))){if(!r.client?.dead)deliver(r,wire.reply(r.raw,2));r.dead=true;}if(r.dead)for(let a in r.attempts)a.socket?.close();}
		requests=filter(requests,r=>!r.dead);for(let c in clients)if(c.dead||now()-c.at>10){c.dead=true;c.socket.close();}clients=filter(clients,c=>!c.dead);
	}
	return {step,close};
};
