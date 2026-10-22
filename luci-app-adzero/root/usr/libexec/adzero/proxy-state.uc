'use strict';
// Shared selection rules. A stopped core overrides a saved enable flag.
import * as fs from 'fs';
import { connect } from 'ubus';

export function active(p) {
	if (!p?.installed) return false;
	if (type(p.active) == 'bool') return p.active;
	if (p.runtime == 'stopped') return false;
	if (p.id == 'nailink' && p.core_checked === false) return false;
	return p.runtime == 'running' || p.enabled === true;
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
