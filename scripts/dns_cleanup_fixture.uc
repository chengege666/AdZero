import * as fs from 'fs';
import { release } from '../luci-app-adzero/root/usr/libexec/adzero/dns-cleanup.uc';
let p=json(fs.readfile('/dev/stdin')),calls=[],error=null;
try{release(p.prior,argv=>{push(calls,argv);return shift(p.results);});}catch(e){error=e.message;}
print(sprintf('%J\n',{calls,error}));
