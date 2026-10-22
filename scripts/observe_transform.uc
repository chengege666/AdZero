'use strict';
import * as fs from 'fs';
import * as lib from '../luci-app-adzero/root/usr/libexec/adzero/observe-lib.uc';
let input=json(fs.readfile('/dev/stdin'));
if(input.operation=='dns')print(sprintf('%J',lib.dns(b64dec(input.data))));
else if(input.operation=='pcap'){
	let messages=[],decoder=lib.decoder(d=>push(messages,d)),raw=b64dec(input.data),size=input.chunk??length(raw);
	for(let i=0;i<length(raw);i+=size)decoder.feed(substr(raw,i,size));
	print(sprintf('%J',messages));
}else if(input.operation=='tracker'){
	let tracker=lib.tracker(),rules={};for(let name in input.rules)rules[name]=true;
	tracker.configure(rules,'generation',true);let test=input.test;if(test)tracker.verification(test);
	for(let item in input.events){if(item.configure){tracker.configure(rules,item.generation,item.active);continue;}tracker.tick(item.at);tracker.event(item.dns,item.at);}
	print(sprintf('%J',{counts:tracker.counts,test}));
}else die('operation');
