import * as fs from 'fs';
import { rules } from '../luci-app-adzero/root/usr/libexec/adzero/dns-guard-lib.uc';
let c=json(fs.readfile('/dev/stdin'));
print(rules(c.lan,c.profile,c.ready,c.bootstrap));
