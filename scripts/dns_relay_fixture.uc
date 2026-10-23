import * as fs from 'fs';
import { relay } from '../luci-app-adzero/root/usr/libexec/adzero/dns-relay.uc';
let p=json(fs.readfile(ARGV[0])),counts={device:0,cname:0};
let server=relay(p.context,p.settings,p.rules,p.allowed,d=>{counts[d.kind]++;});
for(let i=0;i<200;i++)server.step(25);
server.close();print(sprintf('%J\n',counts));
