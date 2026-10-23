import * as fs from 'fs';
import { relay } from '../luci-app-adzero/root/usr/libexec/adzero/dns-relay.uc';
let current=fs.readfile(ARGV[0]),p=json(current),counts={device:0,cname:0};
let server=relay(p.context,p.settings,p.rules,p.allowed,d=>{counts[d.kind]++;});
for(let i=0;i<1000;i++){
	server.step(25);let raw=fs.readfile(ARGV[0]);
	if(raw!=current){let next=json(raw);server.configure(next.settings,next.rules,next.allowed);current=raw;fs.writefile(ARGV[0]+'.applied','1');}
}
server.close();print(sprintf('%J\n',counts));
