// Development fixture. Production socket state machine, loopback only.
import * as fs from 'fs';
import { pool } from '../luci-app-adzero/root/usr/libexec/adzero/dns-pool-lib.uc';
let c=json(fs.readfile(ARGV[0])),s=pool(c.groups,c.ports,c.options);
fs.writefile(ARGV[1],'ready');
for(let i=0;i<300;i++)s.step(100);
s.close();
