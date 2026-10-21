// Isolated production source parser; no UCI, downloads or service calls.
import * as lib from '../luci-app-adzero/root/usr/libexec/adzero/source-lib.uc';
import { readfile } from 'fs';
let request=json(readfile('/dev/stdin'));
let data=request.action == 'catalog' ? lib.catalog : lib.parse(request.raw,request.format);
print(sprintf('%J',data));
