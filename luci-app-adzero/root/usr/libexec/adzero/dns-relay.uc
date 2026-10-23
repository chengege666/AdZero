'use strict';
import * as net from 'socket';
import * as wire from './dns-enhance-lib.uc';
import { now } from './dns-io.uc';
import { same_lan } from './dns-handoff-lib.uc';
// One outstanding request per TCP stream; bounded clients, queries and buffers.
export function relay(context,settings,rules,allowed,count){
	let address=context.lan.address,port=context.listen_port??5354,udp=null,tcp=null,clients=[],requests=[];
	function close(){for(let r in requests)r.socket.close();requests=[];for(let c in clients)c.socket.close();clients=[];udp?.close();tcp?.close();}
	try{
		udp=net.create(net.AF_INET,net.SOCK_DGRAM|net.SOCK_NONBLOCK);tcp=net.create(net.AF_INET,net.SOCK_STREAM|net.SOCK_NONBLOCK);
		if(!udp||!tcp||!udp.bind({address,port})||!tcp.bind({address,port})||!tcp.listen(64))die('dns_bind');
	}
	catch(e){close();die('DNS 增强入口监听失败。');}
	function device(ip){return filter(settings.devices,d=>d.ip==ip&&d.enabled)[0];}
	function deliver(req,raw){
		if(req.client){req.client.output+=wire.word(length(raw))+raw;req.client.waiting=false;req.client.at=now();}
		else udp.send(raw,net.MSG_DONTWAIT|net.MSG_NOSIGNAL,req.peer);
	}
	function begin(raw,peer,client){
		if(context.lan.mask!=null&&!same_lan(peer.address,context.lan)){if(client)client.dead=true;return;}
		let r={query:raw,peer,client,at:now(),buffer:'',output:'',stage:'connect',socket:null};
		try{
			let q=wire.message(raw);if(q.response)die('dns_not_query');
			if(client)client.waiting=true;
			let d=wire.decision(raw,null,rules,allowed,device(peer.address),settings.cname);
			if(d.blocked){count(d);deliver(r,wire.reply(raw,0));return;}
			if(length(requests)>=256){deliver(r,wire.reply(raw,2));return;}
			// The native DNS instance still chooses domestic/foreign resolution.
			r.socket=net.create(net.AF_INET,(client?net.SOCK_STREAM:net.SOCK_DGRAM)|net.SOCK_NONBLOCK);
			if(!r.socket)die('dns_socket');
			let connected=r.socket.connect({address:context.upstream_address??address,port:context.port});
			if(!connected&&r.socket.error(true)!=115)die('dns_connect');
			r.stage=connected?'send':'connect';r.output=client?wire.word(length(raw))+raw:raw;push(requests,r);
		}catch(e){r.socket?.close();if(client){client.dead=true;}else try{deliver(r,wire.reply(raw,2));}catch(ignore){}}
	}
	function finish(r,raw){
		try{
			let q=wire.message(r.query),response=wire.message(raw);
			if(!response.response||response.id!=q.id||response.name!=q.name||response.kind!=q.kind)die('dns_mismatch');
			let d=wire.decision(r.query,raw,rules,allowed,device(r.peer.address),settings.cname);
			if(d.blocked){count(d);raw=wire.reply(r.query,0);}deliver(r,raw);
		}catch(e){deliver(r,wire.reply(r.query,2));}
		r.dead=true;
	}
	function step(timeout){
		let watches=[[udp,net.POLLIN,'udp'],[tcp,net.POLLIN,'tcp']];
		for(let c in clients)push(watches,[c.socket,length(c.output)?net.POLLOUT:c.waiting?0:net.POLLIN,'client',c]);
		for(let r in requests)push(watches,[r.socket,r.stage=='read'?net.POLLIN:net.POLLOUT,'request',r]);
		for(let ev in net.poll(timeout??100,...watches)??[]){
			let s=ev[0],flags=ev[1],kind=ev[2],v=ev[3];
			if(kind=='udp'){let peer={},raw=s.recv(65535,net.MSG_DONTWAIT,peer);if(raw)begin(raw,peer,null);}
			else if(kind=='tcp'){let peer={},socket=s.accept(peer,net.SOCK_NONBLOCK);if(socket){if(length(clients)>=64)socket.close();else push(clients,{socket,peer,buffer:'',output:'',at:now(),waiting:false});}}
			else if(kind=='client'){
				if(flags&net.POLLOUT){let n=s.send(v.output,net.MSG_DONTWAIT|net.MSG_NOSIGNAL);if(n>0){v.output=substr(v.output,n);v.at=now();}else if(n!=null)v.dead=true;}
				if(flags&net.POLLIN){let part=s.recv(65537-length(v.buffer),net.MSG_DONTWAIT);if(!length(part))v.dead=true;else{v.buffer+=part;v.at=now();}}
				if(flags&(net.POLLERR|net.POLLHUP))v.dead=true;
			}else{
				if(flags&(net.POLLERR|net.POLLHUP)){finish(v,wire.reply(v.query,2));continue;}
				if(v.stage=='connect'){if(s.getopt(net.SOL_SOCKET,net.SO_ERROR)!=0){finish(v,wire.reply(v.query,2));continue;}v.stage='send';}
				if(v.stage=='send'&&(flags&net.POLLOUT)){let n=s.send(v.output,net.MSG_DONTWAIT|net.MSG_NOSIGNAL);if(n>0){v.output=substr(v.output,n);if(!length(v.output))v.stage='read';}}
				if(v.stage=='read'&&(flags&net.POLLIN)){
					let part=s.recv(65537-length(v.buffer),net.MSG_DONTWAIT);
					if(part==null)continue;if(!length(part)){finish(v,wire.reply(v.query,2));continue;}
					v.buffer+=part;
					if(!v.client)finish(v,v.buffer);
					else if(length(v.buffer)>=2&&length(v.buffer)>=wire.u16(v.buffer,0)+2)finish(v,substr(v.buffer,2,wire.u16(v.buffer,0)));
				}
			}
		}
		for(let c in clients)if(!c.dead&&!c.waiting&&!length(c.output)&&length(c.buffer)>=2){let size=wire.u16(c.buffer,0);if(size<12)c.dead=true;else if(length(c.buffer)>=size+2){let raw=substr(c.buffer,2,size);c.buffer=substr(c.buffer,size+2);begin(raw,c.peer,c);}}
		for(let r in requests)if(!r.dead&&(now()-r.at>3||r.client?.dead)){if(!r.client?.dead)deliver(r,wire.reply(r.query,2));r.dead=true;}
		for(let r in requests)if(r.dead)r.socket.close();requests=filter(requests,r=>!r.dead);
		for(let c in clients)if(c.dead||now()-c.at>10){c.dead=true;c.socket.close();}clients=filter(clients,c=>!c.dead);
	}
	return {step,close,configure:(s,r,a)=>{settings=s;rules=r;allowed=a;}};
};
