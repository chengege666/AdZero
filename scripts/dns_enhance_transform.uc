import * as fs from 'fs';
import * as lib from '../luci-app-adzero/root/usr/libexec/adzero/dns-enhance-lib.uc';
let p=json(fs.readfile('/dev/stdin'));
if(p.wire)for(let i in p.wire)p.args[i]=b64dec(p.args[i]);
let result=lib[p.operation](...p.args);
if(p.output_wire)result=b64enc(result);
print(sprintf('%J\n',result));
