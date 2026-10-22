'use strict';
import * as fs from 'fs';
import * as lib from '../luci-app-adzero/root/usr/libexec/adzero/observe-lib.uc';
import * as state from '../luci-app-adzero/root/usr/libexec/adzero/observe-state.uc';
let input=json(fs.readfile('/dev/stdin'));
if(input.operation=='dns')print(sprintf('%J',lib.dns(b64dec(input.data))));
else if(input.operation=='pcap'){
	let messages=[],decoder=lib.decoder(d=>push(messages,d)),raw=b64dec(input.data),size=input.chunk??length(raw);
	for(let i=0;i<length(raw);i+=size)decoder.feed(substr(raw,i,size));
	print(sprintf('%J',messages));
}else if(input.operation=='tracker'){
	let recorded=[],tracker=lib.tracker((d,at)=>push(recorded,{name:d.name,at})),rules={};for(let name in input.rules)rules[name]=true;
	tracker.configure(rules,'generation',true);let test=input.test;if(test)tracker.verification(test);
	for(let item in input.events){if(item.reset){tracker.reset();continue;}if(item.configure){tracker.configure(rules,item.generation,item.active);continue;}tracker.tick(item.at);tracker.event(item.dns,item.at);}
	print(sprintf('%J',{counts:tracker.counts,current:tracker.current,recorded,test}));
}else if(input.operation=='recent'){
	let recent=lib.recent(),values=[];
	for(let item in input.steps){if(item.configure)recent.configure(item.token,item.deadline,item.at);if(item.dns)recent.event(item.dns,item.at,item.wall);if(item.snapshot)push(values,json(sprintf('%J',recent.snapshot(item.at))));}
	print(sprintf('%J',values));
}else if(input.operation=='reset-request'){
	print(sprintf('%J',!!state.reset_request(input.request,input.boot,input.at)));
}else if(input.operation=='recent-request'){
	print(sprintf('%J',!!state.recent_request(input.request,input.generation,input.at)));
}else if(input.operation=='adapter-context'){
	let reads=0,inspect=state.adapter_context((path,limit)=>{reads++;return fs.readfile(path,limit);}),values=[];
	let path=state.root+'/etc/adzero/adapter.json';
	for(let step in input.steps){
		if(step.raw!=null){let f=fs.open(path+'.next','w',0600);f.write(step.raw);f.close();fs.chmod(path+'.next',0600);fs.rename(path+'.next',path);}
		if(step.remove)fs.unlink(path);
		for(let i=0;i<(step.repeat??1);i++)push(values,inspect());
	}
	print(sprintf('%J',{values,reads}));
}else die('operation');
