'use strict';
import * as fs from 'fs';
import { cursor } from 'uci';
import * as dns from './routing-lib.uc';
import { pool } from './dns-pool-lib.uc';
import { now } from './dns-io.uc';
import * as state from './dns-pool-state.uc';
let server=null,signature=null,last=0,error=null,effective=null;
try{while(true){
	if(now()-last>=1){last=now();let c=cursor(),profile=dns.profile(json(c.get('adzero','main','dns_profile')??'null')),file=fs.stat('/etc/daed/adzero-cn-domains.txt');effective=sprintf('%J',dns.effective(profile));let next=sprintf('%J',[effective,file?.inode,file?.mtime,file?.size]);
		if(c.get('adzero','main','enabled')!='1'||c.get('adzero','main','routing_enabled')!='1')break;
		if(next!=signature){server?.close();server=null;let domains={};for(let name in split(fs.readfile('/etc/daed/adzero-cn-domains.txt')??'','\n'))if(length(trim(name)))domains[trim(name)]=true;
			server=pool({domestic:dns.addresses(profile,'domestic'),foreign:dns.addresses(profile,'foreign')},null,{proxy_port:profile.proxy_port??0,domains});signature=next;}
		if(!state.publish(effective,'ready'))die('pool_status');
	}server.step(100);
}}catch(e){error=e;}server?.close();
if(error){let reason=error.message=='pool_bind'?'dns_pool_bind_failed':'dns_pool_runtime_failed';state.publish(effective,'error',reason);die(reason);}
let path='/tmp/adzero-dns-pool.json';try{if(json(fs.readfile(path))?.pid==fs.readlink('/proc/self'))fs.unlink(path);}catch(e){}
