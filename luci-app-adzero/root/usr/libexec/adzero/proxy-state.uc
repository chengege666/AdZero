'use strict';
// Shared selection rules. A stopped core overrides a saved enable flag.
import * as fs from 'fs';
import { connect } from 'ubus';

export function active(p) {
	if (!p?.installed) return false;
	if (type(p.active) == 'bool') return p.active;
	if (p.runtime == 'stopped') return false;
	if (p.core_checked === false) return false;
	return p.runtime == 'running' || p.enabled === true;
};

// Shell-managed services often have no useful procd instance. Attribute a
// shared binary to its configuration directory, never to its name alone.
// Only public states leave this function; full argv may contain credentials.
export function core_states(root) {
	root ??= '';
	let kinds={passwall:['xray','v2ray','sing-box','singbox','ss-redir','ssr-redir','sslocal','ss-local','trojan','naive','hysteria','hysteria2','tuic-client','shadow-tls','ipt2socks'],passwall2:['xray','sing-box','singbox'],
		openclash:['mihomo','clash','clash_meta','clash_tun','clash_game','clash_dev'],nikki:['mihomo','clash','clash_meta'],homeproxy:['sing-box','singbox']};
	let found={},unknown={},readable=false;
	for(let path in fs.glob(root+'/proc/[0-9]*/cmdline')??[]){
		let raw=fs.readfile(path,8193);if(raw==null||!length(raw))continue;
		let args=split(raw,'\x00'),binary=fs.basename(args[0]??'');
		readable=true;
		if(!length(filter(keys(kinds),id=>index(kinds[id],binary)>=0)))continue;
		// Config checks and version probes are short-lived, not proxy workers.
		if(length(filter(args,a=>index(['-t','-test','--test','-v','--version','--help','-h','version','check','test','format'],a)>=0)))continue;
		let paths=map(args,a=>replace(a,/^(--?config|--?file|-[cdf])=/,'')),owner=null;
		if(length(raw)<=8192)for(let id in ['passwall','passwall2','openclash','nikki']){
			if(index(kinds[id],binary)<0)continue;
			let prefixes=id=='passwall'||id=='passwall2'?['/tmp/etc/'+id,'/var/etc/'+id]:['/etc/'+id,'/tmp/etc/'+id,'/var/etc/'+id];
			if(length(filter(paths,p=>length(filter(prefixes,d=>p==d||index(p,d+'/')==0))))){owner=id;break;}
		}
		if(!owner&&index(kinds.homeproxy,binary)>=0&&length(filter(paths,p=>match(p,/^\/(var\/run|tmp\/run)\/homeproxy\/sing-box-c[.]json$/))))owner='homeproxy';
		if(owner)found[owner]=true;
		else for(let id in keys(kinds))if(index(kinds[id],binary)>=0)unknown[id]=true;
	}
	let states={};
	for(let id in keys(kinds))states[id]=found[id]?{available:true,running:true}:!readable||unknown[id]?{available:readable,running:null}:{available:true,running:false};
	return states;
};

// Structural evidence from PassWall's running default DNS, never an init exit
// code. Cache decoded fragments by inode/stat: the observer calls this each
// second, but unchanged multi-megabyte address lists must only be read once.
export function dns_runtime(root,plugin,reader) {
	root ??= '';
	reader??=fs.readfile;
	let cached_key=null,cached=null;
	function identity(path){let s=fs.stat(path);return join('|',[path,s?.inode??0,s?.mtime??0,s?.ctime??0,s?.size??0]);}
	return function(samples,engine){
		engine??='dnsmasq';
		if(!length(samples??[])||fs.stat(root+'/proc')?.type!='directory')return {state:'unknown',reason:'runtime_unavailable'};
		let conf=plugin=='passwall'?'/tmp/etc/passwall/acl/default/dnsmasq.conf':null,pid=null,processes={};
		for(let entry in fs.glob(root+'/proc/[0-9]*/comm')??[]){
			if(index(trim(fs.readfile(entry)??''),'dnsmasq')!=0)continue;
			let args=split(fs.readfile(fs.dirname(entry)+'/cmdline',8192)??'','\x00'),at=index(args,'-C');
			if(at<0)continue;
			if(plugin=='passwall'?args[0]=='/tmp/etc/passwall/bin/dnsmasq_default'&&args[at+1]==conf:
				match(args[0]??'',/\/dnsmasq$/)&&match(args[at+1]??'',/^\/(var|tmp)\/etc\/dnsmasq.conf[.][a-zA-Z0-9_]+$/)){
				conf=args[at+1];let id=fs.basename(fs.dirname(entry));
				let stat=fs.readfile(root+'/proc/'+id+'/stat',8192)??'',fields=split(substr(stat,index(stat,')')+2),' ');
				processes[id]={parent:fields[1]};
			}
		}
		let parents=filter(keys(processes),id=>!processes[processes[id].parent]);
		if(length(parents)==1)pid=parents[0];
		if(!pid)return {state:'missing',reason:'dns_process_missing'};
		let status=fs.readfile(root+'/proc/'+pid+'/status',16384)??'',mask=match(status,/(^|\n)SigBlk:[\t ]*([a-fA-F0-9]+)(\n|$)/);
		if(mask&&(int(substr(mask[2],-8),16)&0x10000))return {state:'degraded',reason:'dns_sigchld_blocked'};
		let path=root+conf,raw=fs.readfile(path,1048577);
		if(raw==null||length(raw)>1048576)return {state:'missing',reason:'dns_config_missing'};
		if(plugin=='passwall'&&engine=='chinadns-ng'){
			let native='/tmp/etc/passwall/acl/default/chinadns_ng.conf',child=null;
			for(let entry in fs.glob(root+'/proc/[0-9]*/cmdline')??[]){
				let args=split(fs.readfile(entry,8192)??'','\x00'),at=index(args,'-C');
				if(args[0]=='/tmp/etc/passwall/bin/chinadns-ng'&&at>=0&&args[at+1]==native){child=fs.basename(fs.dirname(entry));break;}
			}
			if(!child)return {state:'missing',reason:'chinadns_process_missing'};
			let data=fs.readfile(root+native,1048577)??'',port=match(data,/(^|\n)bind-port[\t ]+([0-9]+)(\n|$)/);
			if(length(data)>1048576||!port||index('\n'+raw+'\n','\nserver=127.0.0.1#'+port[2]+'\n')<0)return {state:'missing',reason:'chinadns_not_included'};
			let file='/tmp/etc/passwall_tmp/user_rules/block_host',included=false,in_null=false;
			for(let line in split(data,'\n')){
				line=trim(line);if(substr(line,0,6)=='group ')in_null=line=='group null';
				if(in_null&&line=='group-dnl '+file)included=true;
			}
			if(!included)return {state:'missing',reason:'rules_not_included'};
			let key=join('|',[engine,pid,child,identity(root+'/proc/'+pid+'/stat'),identity(root+'/proc/'+child+'/stat'),identity(path),identity(root+native),identity(root+file),join(',',samples)]);
			if(key==cached_key)return cached;
			let list=reader(root+file,33554433),found={};
			if(list!=null&&length(list)<=33554432)for(let line in split(list,'\n'))if(index(samples,trim(line))>=0)found[trim(line)]=true;
			cached_key=key;cached=length(keys(found))==length(samples)?{state:'ready',reason:null}:{state:'missing',reason:'rules_stale'};
			return cached;
		}
		let folder='/tmp/etc/passwall/acl/default/dnsmasq.d',carrier=null;
		if(plugin=='ssrplus'){
			folder=null;
			for(let line in split(raw,'\n')){
				let dir=match(trim(split(line,',')[0]),/^conf-dir=(\/(tmp|etc)\/[a-zA-Z0-9_./-]+)$/);
				if(!dir||index(dir[1],'..')>=0)continue;
				let candidate=root+dir[1]+'/dnsmasq-ssrplus.conf',data=fs.readfile(candidate,65536)??'';
				let nested=match(data,/(^|\n)conf-dir=(\/tmp\/[a-zA-Z0-9_./-]*dnsmasq-ssrplus[.]d)(\n|$)/);
				if(nested&&index(nested[2],'..')<0){folder=nested[2];carrier=candidate;break;}
			}
			if(!folder)return {state:'missing',reason:'rules_not_included'};
		}
		let included=plugin=='ssrplus';
		for(let line in split(raw,'\n'))if(trim(split(line,',')[0])=='conf-dir='+folder)included=true;
		if(!included)return {state:'missing',reason:'rules_not_included'};
		let files=fs.glob(root+folder+'/*.conf')??[];
		if(!length(files)||length(files)>128)return {state:'missing',reason:'rules_missing'};
		let key=join('|',[pid,identity(root+'/proc/'+pid+'/stat'),identity(path),carrier?identity(carrier):'',...map(files,identity),join(',',samples)]);
		if(key==cached_key)return cached;
		let found={};
		for(let file in files){
			// Generated native files only; never follow arbitrary config includes.
			let data=reader(file,33554433);if(data==null||length(data)>33554432)continue;
			data='\n'+data;
			for(let name in samples)for(let prefix in ['address=/.'+name+'/','address=/'+name+'/']){
				for(let value in ['', '0.0.0.0','::'])if(index(data,'\n'+prefix+value+'\n')>=0)found[name]=true;
			}
		}
		cached_key=key;cached=length(keys(found))==length(samples)?{state:'ready',reason:null}:{state:'missing',reason:'rules_stale'};
		return cached;
	};
};
function quote(s) { return "'" + replace(s, /'/g, "'\\''") + "'"; }
export function nailink(root) {
	// Query the core, not the always-on management process. No config or JWT
	// is read; use a short-lived, scoped local session and always destroy it.
	let fixture = getenv('ADZERO_PROBE_NAILINK_FIXTURE');
	if (root && fixture) {
		try { let data = json(fs.readfile(fixture)); return type(data?.running) == 'bool' ? data.running : null; }
		catch(e) { return null; }
	}
	let bus, session, input, output, created = [], result = null;
	try {
		bus = connect();
		if (!bus) return null;
		session = bus.call('session','create',{timeout:10})?.ubus_rpc_session;
		if (!match(session ?? '', /^[a-f0-9]{32}$/)) die('session unavailable');
		bus.call('session','grant',{ubus_rpc_session:session,scope:'access-group',objects:[['luci-app-daed-router','write']]});
		if (bus.call('session','access',{ubus_rpc_session:session,scope:'access-group',object:'luci-app-daed-router',function:'write'})?.access !== true) die('access unavailable');
		let payload = '{"query":"{general{dae{running}}}"}';
		input = (root ?? '') + '/tmp/adzero-proxy-' + session + '.in';
		output = (root ?? '') + '/tmp/adzero-proxy-' + session + '.out';
		for (let path in [input,output]) {
			let file = fs.open(path,'wx',0600);
			if (!file) die('temporary file unavailable');
			push(created,path);
			let data = path == input ? payload : '';
			let written = file.write(data), closed = file.close();
			if (written != length(data) || !closed) die('short write');
		}
		let argv = ['env','REQUEST_METHOD=POST','REQUEST_URI=/cgi-bin/daed-router/graphql',
			'SCRIPT_NAME=/cgi-bin/daed-router','PATH_INFO=/graphql','SERVER_PROTOCOL=HTTP/1.1',
			'HTTP_HOST=localhost','HTTP_ORIGIN=http://localhost','HTTP_COOKIE=daed_luci_session='+session,
			'CONTENT_TYPE=application/json','CONTENT_LENGTH='+length(payload),(root ?? '')+'/usr/libexec/daed/luci-proxy'];
		let rc = system(join(' ',map(argv,quote))+' < '+quote(input)+' > '+quote(output)+' 2>/dev/null',1500);
		let file = fs.open(output,'r'), raw = file ? file.read(65537) : null;
		if (file) file.close();
		if (rc != 0 || length(raw ?? '') > 65536) die('probe unavailable');
		raw = replace(raw ?? '',/\r\n/g,'\n');
		let split_at = index(raw,'\n\n');
		if (split_at < 0) die('invalid response');
		let status = match(substr(raw,0,split_at),/(^|\n)Status: ([0-9]{3})/);
		if (status && status[2] != '200') die('request rejected');
		let data = json(substr(raw,split_at+2));
		if (!length(data?.errors ?? []) && type(data?.data?.general?.dae?.running) == 'bool') result = data.data.general.dae.running;
	} catch(e) { /* Unknown is distinct from stopped. Never emit private responses. */ }
	for (let path in created) fs.unlink(path);
	if (bus) {
		if (session) try { bus.call('session','destroy',{ubus_rpc_session:session}); } catch(e) {}
		bus.disconnect();
	}
	return result;
};
