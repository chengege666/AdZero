'use strict';
import * as fs from 'fs';
import { cursor } from 'uci';
import * as dns from './routing-lib.uc';
import { pool } from './dns-pool-lib.uc';
import { now } from './dns-io.uc';
let server=null,signature=null,last=0,error=null;
try{while(true){
	if(now()-last>=1){last=now();let c=cursor(),profile=dns.profile(json(c.get('adzero','main','dns_profile')??'null')),file=fs.stat('/etc/daed/adzero-cn-domains.txt'),effective=sprintf('%J',dns.effective(profile)),next=sprintf('%J',[effective,file?.inode,file?.mtime,file?.size]);
		if(c.get('adzero','main','enabled')!='1'||c.get('adzero','main','routing_enabled')!='1')break;
		if(next!=signature){server?.close();server=null;let domains={};for(let name in split(fs.readfile('/etc/daed/adzero-cn-domains.txt')??'','\n'))if(length(trim(name)))domains[trim(name)]=true;
			server=pool({domestic:dns.addresses(profile,'domestic'),foreign:dns.addresses(profile,'foreign')},null,{proxy_port:profile.proxy_port??0,domains});signature=next;}
		let path='/tmp/adzero-dns-pool.json.'+fs.readlink('/proc/self'),f=fs.open(path,'wx',0600),raw=sprintf('%J',{profile:effective,updated:now()});if(!f)die('pool_status');let ok=f.write(raw)==length(raw),closed=f.close();if(!ok||!closed||!fs.rename(path,'/tmp/adzero-dns-pool.json')){fs.unlink(path);die('pool_status');}
	}server.step(100);
}}catch(e){error=e;}server?.close();fs.unlink('/tmp/adzero-dns-pool.json');if(error)die(error);
