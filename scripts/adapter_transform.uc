// Development harness. Runs the production transformations with actual ucode.
import * as lib from '../luci-app-adzero/root/usr/libexec/adzero/adapter-lib.uc';
import { readfile } from 'fs';
let input = json(readfile('/dev/stdin'));
let result = lib[input.operation](...input.arguments);
if (input.operation == 'geosite') result = b64enc(result);
print(sprintf('%J', result));
