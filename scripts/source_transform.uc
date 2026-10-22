// Isolated production source parser; no UCI, downloads or service calls.
import * as lib from '../luci-app-adzero/root/usr/libexec/adzero/source-lib.uc';
import { readfile } from 'fs';
let request=json(readfile('/dev/stdin'));
let data;
if(request.action=='catalog')data=lib.catalog;
else if(request.action=='inspect'){
	let result=request.format?lib.inspect(request.raw,request.format):lib.detect(request.raw);
	data=result?{format:result.format,domains:length(result.names),skipped:result.skipped,validation:'validated'}:{format:'unknown',domains:null,skipped:0,validation:'backend_only'};
}else data=lib.parse(request.raw,request.format);
print(sprintf('%J',data));
