'use strict';
import * as net from 'socket';
import * as wire from './dns-enhance-lib.uc';
import * as http from './dns-alias-http.uc';
import { now } from './dns-io.uc';
import { same_lan } from './dns-handoff-lib.uc';
// One outstanding request per TCP stream; bounded clients, queries and buffers.
export function relay(context,settings,rules,allowed,count){
	let address=context.lan.address,port=context.listen_port??5354,udp=null,tcp=null,clients=[],requests=[];
	let inspection={checked:0,failed:0};
	function unverified(){inspection.failed++;inspection.last_failure=now();}
	function close(){for(let r in requests){r.socket?.close();r.lookup?.close();}requests=[];for(let c in clients){c.upstream?.close();c.socket.close();}clients=[];udp?.close();tcp?.close();}
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
	function connect(r,socket){
		r.opened=socket?r.client.upstream_started:now();
		r.socket=socket??net.create(net.AF_INET,(r.client?net.SOCK_STREAM:net.SOCK_DGRAM)|net.SOCK_NONBLOCK);
		if(!r.socket)die('dns_socket');
		let connected=socket!=null||r.socket.connect({address:context.upstream_address??address,port:context.port});
		if(!connected&&r.socket.error(true)!=115)die('dns_connect');
		r.stage=connected?'send':'connect';r.buffer='';r.output=r.client?wire.word(length(r.query))+r.query:r.query;
	}
	function fail(r){
		// An idle native connection may close just after it was selected. Retry
		// that reused stream once, within the original three-second deadline.
		// Never retry a malformed/mismatched DNS response or a fresh stream.
		if(r.reused){r.reused=false;r.socket?.close();r.socket=null;try{connect(r,null);return;}catch(e){}}
		deliver(r,wire.reply(r.query,2));r.dead=true;
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
			// Reuse only this client's native TCP connection. Native DNS keeps
			// control of resolution and caching; no answers cross client streams.
			let reused=client?.upstream;
			if(reused&&(now()-client.upstream_started>=30||client.upstream_uses>=32)){reused.close();reused=null;client.upstream=null;}
			if(reused){client.upstream=null;let events=net.poll(0,[reused,net.POLLIN])??[];if(length(filter(events,e=>e[1]!=0))){reused.close();reused=null;}}
			r.reused=!!reused;connect(r,reused);
			if(settings.cname&&context.inspector){try{r.lookup=http.lookup(context,raw);if(!q.api_safe)unverified();}catch(e){unverified();}}
			push(requests,r);
		}catch(e){r.socket?.close();if(client){client.dead=true;}else try{deliver(r,wire.reply(raw,2));}catch(ignore){}}
	}
	function finish(r,raw,keep){
		try{
			let q=wire.message(r.query),response=wire.message(raw);
			if(!response.response||response.id!=q.id||response.name!=q.name||response.kind!=q.kind)die('dns_mismatch');
			// Keep native bytes (including Fake-IP and DNSSEC) for clean replies.
			// The supplemental API uses that core's real resolver and cache.
			r.native=raw;r.keep=keep;r.stage='inspection';
			if(r.lookup)return;
			let d=wire.decision(r.query,r.alias??raw,rules,allowed,device(r.peer.address),settings.cname);
			if(d.blocked){count(d);raw=wire.reply(r.query,0);}deliver(r,raw);
			if(r.client&&keep&&!r.client.dead){r.client.upstream=r.socket;r.client.upstream_started=r.opened;r.client.upstream_uses=(r.reused?r.client.upstream_uses:0)+1;r.socket=null;}
		}catch(e){deliver(r,wire.reply(r.query,2));}
		r.dead=true;
	}
	function step(timeout){
		let watches=[[udp,net.POLLIN,'udp'],[tcp,net.POLLIN,'tcp']];
		for(let c in clients)push(watches,[c.socket,length(c.output)?net.POLLOUT:c.waiting?0:net.POLLIN,'client',c]);
		for(let c in clients)if(c.upstream)push(watches,[c.upstream,net.POLLIN,'idle',c]);
		for(let r in requests){
			if(r.stage!='inspection')push(watches,[r.socket,r.stage=='read'?net.POLLIN:net.POLLOUT,'request',r]);
			if(r.lookup)push(watches,[r.lookup.socket,r.lookup.events(),'alias',r]);
		}
		for(let ev in net.poll(timeout??100,...watches)??[]){
			let s=ev[0],flags=ev[1],kind=ev[2],v=ev[3];
			if(!flags)continue; // ucode poll includes quiet descriptors with flags=0.
			if(kind=='udp'){let peer={},raw=s.recv(65535,net.MSG_DONTWAIT,peer);if(raw)begin(raw,peer,null);}
			else if(kind=='tcp'){let peer={},socket=s.accept(peer,net.SOCK_NONBLOCK);if(socket){if(length(clients)>=64)socket.close();else push(clients,{socket,peer,buffer:'',output:'',at:now(),waiting:false,upstream:null});}}
			else if(kind=='idle'){if(v.upstream==s){s.close();v.upstream=null;}}
			else if(kind=='alias'){
				if(v.dead)continue;
				try{let result=v.lookup.step(flags);if(result!=null){v.alias=result;inspection.checked++;v.lookup.close();v.lookup=null;}}
				catch(e){unverified();v.lookup.close();v.lookup=null;}
				if(!v.lookup&&v.native)finish(v,v.native,v.keep);
			}
			else if(kind=='client'){
				if(flags&net.POLLOUT){let n=s.send(v.output,net.MSG_DONTWAIT|net.MSG_NOSIGNAL);if(n>0){v.output=substr(v.output,n);v.at=now();}else if(n!=null)v.dead=true;}
				if(flags&net.POLLIN){let part=s.recv(65537-length(v.buffer),net.MSG_DONTWAIT);if(part==null){if(s.error(true)!=11)v.dead=true;}else if(!length(part))v.dead=true;else{v.buffer+=part;v.at=now();}}
				if(flags&(net.POLLERR|net.POLLHUP))v.dead=true;
			}else{
				if(v.stage=='connect'){if(s.getopt(net.SOL_SOCKET,net.SO_ERROR)!=0){fail(v);continue;}v.stage='send';}
				if(v.stage=='send'&&(flags&net.POLLOUT)){let n=s.send(v.output,net.MSG_DONTWAIT|net.MSG_NOSIGNAL);if(n>0){v.output=substr(v.output,n);if(!length(v.output))v.stage='read';}else if(n!=null||s.error(true)!=11){fail(v);continue;}}
				// A peer may close immediately after writing its final answer.
				// Drain readable bytes before treating HUP as a transport failure.
				if(v.stage=='read'&&(flags&(net.POLLIN|net.POLLHUP))){
					let part=s.recv(65537-length(v.buffer),net.MSG_DONTWAIT);
					if(part==null){if(s.error(true)!=11||flags&(net.POLLERR|net.POLLHUP))fail(v);continue;}if(!length(part)){fail(v);continue;}
					v.buffer+=part;
					if(!v.client)finish(v,v.buffer,false);
					else if(length(v.buffer)>=2&&length(v.buffer)>=wire.u16(v.buffer,0)+2)finish(v,substr(v.buffer,2,wire.u16(v.buffer,0)),!(flags&(net.POLLERR|net.POLLHUP))&&length(v.buffer)==wire.u16(v.buffer,0)+2);
				}
				if(!v.dead&&flags&(net.POLLERR|net.POLLHUP))fail(v);
			}
		}
		for(let c in clients)if(!c.dead&&!c.waiting&&!length(c.output)&&length(c.buffer)>=2){let size=wire.u16(c.buffer,0);if(size<12)c.dead=true;else if(length(c.buffer)>=size+2){let raw=substr(c.buffer,2,size);c.buffer=substr(c.buffer,size+2);begin(raw,c.peer,c);}}
		for(let r in requests)if(!r.dead&&r.lookup&&now()-r.at>1.5){unverified();r.lookup.close();r.lookup=null;if(r.native)finish(r,r.native,r.keep);}
		for(let r in requests)if(!r.dead&&(now()-r.at>3||r.client?.dead)){if(!r.client?.dead)deliver(r,wire.reply(r.query,2));r.dead=true;}
		for(let r in requests)if(r.dead){r.socket?.close();r.lookup?.close();}requests=filter(requests,r=>!r.dead);
		for(let c in clients)if(c.dead||now()-c.at>10){c.dead=true;c.upstream?.close();c.socket.close();}clients=filter(clients,c=>!c.dead);
	}
	return {step,close,inspection:()=>({...inspection,degraded:inspection.failed>0&&now()-inspection.last_failure<30}),configure:(s,r,a)=>{
		// A persistent native TCP worker must not keep a superseded rule
		// generation alive after native DNS reloads its data in place.
		if(r!==rules)for(let c in clients){c.upstream?.close();c.upstream=null;}
		settings=s;rules=r;allowed=a;
	}};
};
