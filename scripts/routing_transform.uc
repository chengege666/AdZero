// Development harness, production compiler executed by real OpenWrt ucode.
import * as lib from '../luci-app-adzero/root/usr/libexec/adzero/routing-lib.uc';
import { readfile } from 'fs';
let input=json(readfile('/dev/stdin'));
let result=lib[input.operation](...input.arguments);
if(input.operation=='geoip')result=b64enc(result);
print(sprintf('%J',result));
