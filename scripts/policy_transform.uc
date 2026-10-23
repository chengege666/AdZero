// Read-only development harness for the production rule matcher.
import * as fs from 'fs';
import * as lib from '../luci-app-adzero/root/usr/libexec/adzero/policy-lib.uc';
let input=json(fs.readfile('/dev/stdin'));
print(sprintf('%J',lib.lookup(...input.arguments)));
