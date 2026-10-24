import * as fs from 'fs';
import * as capacity from '../luci-app-adzero/root/usr/libexec/adzero/capacity-lib.uc';
let input=json(fs.readfile('/dev/stdin'));
print(sprintf('%J',capacity[input.operation](...input.arguments)));
