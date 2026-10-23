'use strict';
// Explain only snapshots whose digest is bound to the currently applied output.
import * as fs from 'fs';
import * as cache from './source-cache.uc';
import * as policy from './policy-lib.uc';
function digest(path) {
	let p=fs.popen("sha256sum '"+replace(path,/'/g,"'\\''")+"' 2>/dev/null",'r');
	if(!p)return null;let raw=p.read('all'),code=p.close();return code==0?split(raw,' ')[0]:null;
}
export function explain(root,dir,output,rule,adapter) {
	let result={state:'unavailable',items:[],incomplete:true};
	try {
		let receipt=json(fs.readfile(dir+'/backend-cache.json')??'null');
		if(receipt?.schema!=2||!rule||digest(output)!=receipt.sha256||type(receipt.effective)!='array')return result;
		if(adapter&&(adapter.stage!='configured_unverified'||adapter.plugin!='none'&&adapter.rules_source?.sha256!=receipt.sha256))return result;
		let missing=false,position=0;
		for(let entry in receipt.effective) {
			if(entry.type!='file_url'||(entry.values.action??'block')!='block')continue;
			position++;
			let snapshot=cache.load(entry.values.url,root);
			if(!snapshot||snapshot.proof.body!=entry.snapshot){missing=true;continue;}
			let found=cache.contains(snapshot,rule);
			if(found==null){missing=true;continue;}
			if(found) {
				let saved=filter(receipt.config,s=>s.type=='file_url'&&s.values.url==entry.values.url)[0];
				push(result.items,{kind:'subscription',name:substr(saved?.values.name??'规则订阅 '+position,0,80),rule});
			}
		}
		for(let entry in receipt.config)if(entry.type=='adblock-fast'&&index(policy.list(entry.values.blocked_domain),rule)>=0)
			push(result.items,{kind:'custom',name:'自定义拦截',rule});
		result.state=length(result.items)?'known':'unavailable';result.incomplete=missing||!length(result.items);
	}catch(e){} // Old/missing snapshots must never be attributed to new bytes.
	return result;
};
