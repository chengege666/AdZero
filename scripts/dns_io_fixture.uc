import * as fs from 'fs';
import * as io from '../luci-app-adzero/root/usr/libexec/adzero/dns-io.uc';
let p=json(fs.readfile('/dev/stdin'));
if(p.wait!=null){let start=io.now();io.wait(p.wait);print(sprintf('%J\n',{elapsed:io.now()-start}));exit(0);}
let result=io.exchange(p.address,p.port,b64dec(p.query),p.tcp,p.proxy_port??0);
print(sprintf('%J\n',result?b64enc(result):null));
