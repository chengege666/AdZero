'use strict';
// Shared selection rules. A stopped core overrides a saved enable flag.
import * as fs from 'fs';
import { connect } from 'ubus';

export function active(p) {
	if (!p?.installed) return false;
	if (type(p.active) == 'bool') return p.active;
	if (p.runtime == 'stopped') return false;
	if (index(['nailink','ssrplus'],p.id)>=0 && p.core_checked === false) return false;
	return p.runtime == 'running' || p.enabled === true;
};

// Structural evidence from PassWall's running default DNS, never an init exit
// code. Cache decoded fragments by inode/stat: the observer calls this each
// second, but unchanged multi-megabyte address lists must only be read once.
export function dns_runtime(root,plugin,reader) {
	root ??= '';
	reader??=fs.readfile;
	let cached_key=null,cached=null;
	function identity(path){let s=fs.stat(path);return join('|',[path,s?.inode??0,s?.mtime??0,s?.ctime??0,s?.size??0]);}
	return function(samples){
		if(!length(samples??[])||fs.stat(root+'/proc')?.type!='directory')return {state:'unknown',reason:'runtime_unavailable'};
		let conf=plugin=='passwall'?'/tmp/etc/passwall/acl/default/dnsmasq.conf':null,pid=null;
		for(let entry in fs.glob(root+'/proc/[0-9]*/comm')??[]){
			if(index(trim(fs.readfile(entry)??''),'dnsmasq')!=0)continue;
			let args=split(fs.readfile(fs.dirname(entry)+'/cmdline',8192)??'','\x00'),at=index(args,'-C');
			if(at<0)continue;
			if(plugin=='passwall'?args[0]=='/tmp/etc/passwall/bin/dnsmasq_default'&&args[at+1]==conf:
				match(args[0]??'',/\/dnsmasq$/)&&match(args[at+1]??'',/^\/(var|tmp)\/etc\/dnsmasq.conf[.][a-zA-Z0-9_]+$/)){
				conf=args[at+1];pid=fs.basename(fs.dirname(entry));break;
			}
		}
		if(!pid)return {state:'missing',reason:'dns_process_missing'};
		let path=root+conf,raw=fs.readfile(path,1048577);
		if(raw==null||length(raw)>1048576)return {state:'missing',reason:'dns_config_missing'};
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
