import * as fs from 'fs';
import * as net from 'socket';
import { lookup } from '../luci-app-adzero/root/usr/libexec/adzero/dns-alias-http.uc';
let p=json(fs.readfile('/dev/stdin')),r=null;
try{
	r=lookup(p.context,b64dec(p.query));if(!r)die('lookup_skipped');
	for(let i=0;i<50;i++)for(let ev in net.poll(50,[r.socket,r.events()])??[])if(ev[1]){let result=r.step(ev[1]);if(result){print(sprintf('%J',{raw:b64enc(result)}));r.close();exit(0);}}
	die('lookup_timeout');
}catch(e){r?.close();print(sprintf('%J',{error:e.message}));exit(1);}
