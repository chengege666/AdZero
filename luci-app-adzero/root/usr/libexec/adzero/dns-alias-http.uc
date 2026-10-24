'use strict';
// Bounded, asynchronous access to the existing local Mihomo resolver API.
// Credentials stay in memory/private context; no subprocess argv or query log.
import * as net from 'socket';
import * as native from './dns-native-lib.uc';
import * as wire from './dns-enhance-lib.uc';
export function lookup(context,query){
	let c=context.inspector,q=wire.message(query),types={'1':'A','28':'AAAA','64':'SVCB','65':'HTTPS'};
	if(!c||!q.api_safe||!types[q.kind]||!match(q.name,/^[a-z0-9_.-]+$/))return null;
	let socket=net.create(net.AF_INET,net.SOCK_STREAM|net.SOCK_NONBLOCK);if(!socket)die('alias_socket');
	let opened=socket.connect({address:c.address,port:c.port});
	if(!opened&&socket.error(true)!=115){socket.close();die('alias_connect');}
	let stage=opened?'send':'connect',buffer='',body=null,header=null,closed=false;
	let output='GET /dns/query?name='+q.name+'&type='+types[q.kind]+' HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n'+(length(c.secret)?'Authorization: Bearer '+c.secret+'\r\n':'')+'\r\n';
	function close(){if(!closed){closed=true;socket.close();}}
	function complete(eof){
		let cut=index(buffer,'\r\n\r\n');if(cut<0){if(length(buffer)>8192||eof)die('alias_header');return null;}
		if(!header){
			header=lc(substr(buffer,0,cut));
			if(!match(header,/^http\/1[.][01] 200[ \r\n]/))die('alias_status');
		}
		let data=substr(buffer,cut+4),size=match(header,/\r\ncontent-length:[ \t]*([0-9]+)/);
		if(index(header,'\r\ntransfer-encoding: chunked')>=0){
			body='';let p=0;
			while(true){let tail=index(substr(data,p),'\r\n');if(tail<0){if(eof)die('alias_chunk');return null;}
				let line=substr(data,p,tail);if(!match(line,/^[0-9a-fA-F]{1,6}$/))die('alias_chunk');
				let n=int(line,16);p+=tail+2;if(n>131072||length(body)+n>131072)die('alias_size');
				if(!n){if(substr(data,p,2)!='\r\n'){if(eof)die('alias_chunk');return null;}break;}
				if(length(data)<p+n+2){if(eof)die('alias_chunk');return null;}
				if(substr(data,p+n,2)!='\r\n')die('alias_chunk');body+=substr(data,p,n);p+=n+2;
			}
		}else if(size){let n=int(size[1]);if(n>131072)die('alias_size');if(length(data)<n){if(eof)die('alias_short');return null;}body=substr(data,0,n);}
		else {if(!eof)return null;body=data;}
		return native.api_answer(query,json(body));
	}
	function step(flags){
		if(stage=='connect'){if(socket.getopt(net.SOL_SOCKET,net.SO_ERROR)!=0)die('alias_connect');stage='send';}
		if(stage=='send'&&(flags&net.POLLOUT)){
			let n=socket.send(output,net.MSG_DONTWAIT|net.MSG_NOSIGNAL);if(n>0){output=substr(output,n);if(!length(output))stage='read';}else if(n!=null||socket.error(true)!=11)die('alias_send');
		}
		if(stage=='read'&&(flags&(net.POLLIN|net.POLLHUP))){
			let part=socket.recv(16384,net.MSG_DONTWAIT),eof=part=='';
			if(part==null){if(socket.error(true)!=11)die('alias_read');return null;}
			buffer+=part;if(length(buffer)>139264)die('alias_size');let result=complete(eof);if(result!=null)return result;
			if(eof)die('alias_short');
		}
		if(flags&(net.POLLERR|net.POLLHUP))die('alias_closed');return null;
	}
	return {socket,events:()=>stage=='read'?net.POLLIN:net.POLLOUT,step,close};
};
