'use strict';
import * as fs from 'fs';
import { cursor } from 'uci';
import * as state from './observe-state.uc';
import * as proxy from './proxy-state.uc';
import * as wire from './observe-lib.uc';
import * as cache from './rules-cache.uc';
let action=shift(ARGV);if(action=='--')action=shift(ARGV);
const dir=state.directory,root=state.root;
if(action=='status'){
	let value=state.snapshot();delete value.pid;delete value.sample;delete value.generation;delete value.boot;
	value.client_dns_verified=value.available===true&&value.active===true&&value.verification?.state=='passed';
	print(sprintf('%J\n',value));exit(0);
}
if(action=='start-test'){
	try{
		let current=state.snapshot();if(!current.available||!current.active)die('请先开启保护，并等待局域网 DNS 统计就绪。');
		if(!current.sample)die('当前规则中没有适合自动检测的公开样本。可使用域名查询与暂停对比。');
		let previous=state.read(dir+'/test.json',2048),now=state.monotime();
		if(previous&&previous.generation==current.generation&&previous.deadline>now&&current.verification?.state!='passed')die('已有检测正在等待查询，请先完成或等待两分钟后重试。');
		let nonce=replace(trim(fs.readfile('/proc/sys/kernel/random/uuid')??''),/-/g,'');if(!match(nonce,/^[a-f0-9]{32}$/))die('无法创建检测。');
		let request={nonce,generation:current.generation,deadline:now+120,sample:current.sample,control:'www.baidu.com'};
		state.atomic(dir+'/test.json',request);
		print(sprintf('%J\n',{ok:true,expires:120,commands:'nslookup -type=A '+nonce+'.adzero.invalid\nnslookup -type=A '+request.sample+'\nnslookup -type=A '+request.control}));
	}catch(e){print(sprintf('%J\n',{ok:false,message:e.message}));}exit(0);
}
if(action=='recent-start'||action=='recent-stop'){
	try{
		let current=state.snapshot(),now=state.monotime(),request={schema:1,enabled:false};
		if(action=='recent-start'){
			if(!current.available||!current.active)die('请先开启保护，并等待 DNS 统计就绪。');
			let nonce=replace(trim(fs.readfile('/proc/sys/kernel/random/uuid')??''),/-/g,'');if(!match(nonce,/^[a-f0-9]{32}$/))die('无法创建临时记录。');
			request={schema:1,enabled:true,nonce,generation:current.generation,deadline:now+300};
		}
		state.atomic(dir+'/recent.json',request);print('{"ok":true}\n');
	}catch(e){print(sprintf('%J\n',{ok:false,message:e.message}));}exit(0);
}
if(action=='reset-stats'){
	try{
		let current=state.snapshot(),now=state.monotime();if(!current.available)die('统计组件未就绪，暂时无法清零。');
		let nonce=replace(trim(fs.readfile('/proc/sys/kernel/random/uuid')??''),/-/g,'');if(!match(nonce,/^[a-f0-9]{32}$/))die('无法创建清零请求。');
		state.atomic(dir+'/reset.json',{schema:1,nonce,boot:current.boot,requested:now});
		print(sprintf('%J\n',{ok:true,token:nonce}));
	}catch(e){print(sprintf('%J\n',{ok:false,message:e.message}));}exit(0);
}
if(action!='collect')exit(2);
const device=shift(ARGV),loop=require('uloop'),uci=cursor(root+'/etc/config');
let recent=wire.recent(),tracker=wire.tracker((d,now)=>recent.event(d,now,time())),generation='',previous='',loaded='',rules={},active=false,verification=null,test=null,sample=null;
let result={schema:1,available:true,active:false,device,scope:'lan_dns',protocols:['udp','tcp'],pid:fs.readlink('/proc/self'),started:time(),updated:0,
	queries:0,blocked:0,answered:0,overflow:0,verification:{state:'idle'}};
const boot=trim(fs.readfile('/proc/sys/kernel/random/boot_id')??'');
let prior=state.read(dir+'/status.json',16384);
if(match(boot,/^[a-f0-9-]{36}$/)&&prior?.boot==boot){
	for(let name in keys(tracker.counts))if(type(prior[name])=='int'&&prior[name]>=0&&prior[name]<9007199254740991)tracker.counts[name]=prior[name];
	if(type(prior.started)=='int'&&prior.started>0&&prior.started<=time())result.started=prior.started;
	if(match(prior.reset_token??'',/^[a-f0-9]{32}$/))result.reset_token=prior.reset_token;
}
result.boot=boot;
const outputs={'dnsmasq.servers':'/var/run/adblock-fast/dnsmasq.servers','dnsmasq.addnhosts':'/var/run/adblock-fast/dnsmasq.addnhosts','smartdns.domainset':'/var/run/adblock-fast/smartdns.domainset','unbound.adb_list':'/var/lib/unbound/adb_list.adblock-fast'};
const adapter_context=state.adapter_context();
const native_runtime={passwall:proxy.dns_runtime(root,'passwall'),ssrplus:proxy.dns_runtime(root,'ssrplus')};
function refresh(){
	uci.unload('adzero');uci.unload('adblock-fast');
	let mode=uci.get('adblock-fast','config','dns'),path=outputs[mode],file=path?fs.stat(root+path):null,config=fs.stat(root+'/etc/config/adzero');
	let source=join('|',[path??'',file?.inode??0,file?.mtime??0,file?.size??0]),journal=fs.stat(root+'/etc/adzero/adapter.json');
	let signature=join('|',[source,config?.inode??0,config?.mtime??0,config?.size??0,journal?.inode??0,journal?.mtime??0,journal?.size??0]);
	let reason=uci.get('adzero','main','enabled')!='1'?'protection_disabled':uci.get('adblock-fast','config','enabled')!='1'?'backend_disabled':!fs.stat(root+'/etc/adzero/managed')?'not_managed':!path?'unsupported_resolver':!file?.size?'rules_unavailable':null;
	let context=adapter_context();
	result.connection={plugin:context.present?context.plugin??null:'none',stage:context.present?context.stage??'unknown':'inactive',domains:context.domains??null,routing_mode:context.routing_mode??'inactive',confirmed:context.present&&!context.reason};
	if(native_runtime[context.plugin]){
		result.connection.runtime=context.runtime_supported?native_runtime[context.plugin](context.runtime_samples,context.dns_engine):{state:'unknown',reason:'runtime_unavailable'};
		result.connection.runtime_retry_exhausted=context.runtime_retry_exhausted;
		result.connection.confirmed&&=result.connection.runtime.state=='ready';
		signature+='|'+result.connection.runtime.state+'|'+result.connection.runtime.reason;
	}
	if(!reason&&context.present)reason=context.reason;
	let enabled=!reason;
	if(signature!=previous||enabled!=active){
		if(enabled&&source!=loaded){
			let list=cache.load(root+path,mode,root);rules={};for(let name in list)rules[name]=true;loaded=source;
			sample=null;for(let name in ['doubleclick.net','googleadservices.com','googlesyndication.com'])if(wire.rules_match(rules,name)){sample=name;break;}
		}
		generation=replace(trim(fs.readfile('/proc/sys/kernel/random/uuid')??''),/-/g,'');previous=signature;active=enabled;
		verification=null;test=null;tracker.configure(rules,generation,active);
	}
	return reason;
}
function tick(){
	let now=state.monotime();
	let reset=state.read(dir+'/reset.json',2048);
	if(state.reset_request(reset,boot,now)&&reset.nonce!=result.reset_token){tracker.reset();result.reset_token=reset.nonce;result.started=time();}
	try{let reason=refresh();if(reason)result.reason=reason;else delete result.reason;}catch(e){active=false;tracker.configure({},'',false);result.reason='rules_unavailable';}
	let recording=state.read(dir+'/recent.json',2048);
	if(active&&state.recent_request(recording,generation,now))recent.configure(recording.nonce,recording.deadline,now);else recent.configure(null,0,now);
	let requested=state.read(dir+'/test.json',2048);
	if(requested?.generation==generation&&match(requested.nonce??'',/^[a-f0-9]{32}$/)&&requested.deadline>now&&requested.deadline<=now+125){
		if(test?.nonce!=requested.nonce){test=requested;verification=null;tracker.verification(test);}
	}
	test=tracker.verification();
	if(test&&test.generation==generation){
		if(test.marker&&test.blocked&&test.normal){if(verification?.state!='passed')verification={state:'passed',at:time(),client:test.client};}
		else if(now>=test.deadline)verification={state:'expired'};
		else verification={state:'waiting',remaining:int(test.deadline-now),marker:!!test.marker,blocked:!!test.blocked,normal:!!test.normal};
	}
	tracker.tick(now);
	result={...result,...tracker.counts,active,updated:now,generation,sample,current:tracker.current,recent_token:state.recent_request(recording,generation,now)?recording.nonce:null,recent:recent.snapshot(now),verification:active?(verification??{state:'idle'}):{state:'idle'}};
	state.atomic(dir+'/status.json',result);
}
try{
	loop.init();
	// OpenWrt 24.10's stdio read discards partial data on EAGAIN. Keep the
	// framed blocking reader in a small child; uloop owns its IPC and timers.
	// Fork before loading the domain map so the child does not retain it.
	let capture=fs.open('/proc/self/fd/0','r');if(!capture)die('capture_input');
	let reader=loop.task(pipe=>{
		// uloop.task repurposes stdin for its IPC; preserve the capture FD.
		let input=capture,decoder=wire.decoder(d=>pipe.send(d));
		function exact(size){let data='';while(length(data)<size){let part=input.read(size-length(data));if(!part||!length(part))return null;data+=part;}return data;}
		try{
			let header=exact(24);if(!header)die('header');decoder.feed(header);
			let little=ord(header,0)==0xd4||ord(header,0)==0x4d;
			while(true){
				let frame=exact(16);if(!frame)break;
				let size=0;for(let i=0;i<4;i++)size=size*256+ord(frame,8+(little?3-i:i));if(size>262144)die('frame');
				let data=exact(size);if(data==null)break;decoder.tick(state.monotime());decoder.feed(frame+data);
			}
		}catch(e){}
		pipe.send({capture:'closed'});input.close();
	},message=>{
		if(type(message)!='object')return;
		if(message?.capture=='closed'){result.available=false;result.reason='capture_stopped';state.atomic(dir+'/status.json',result);loop.end();return;}
		tracker.event(message,state.monotime());
	});
	if(!reader)die('capture_reader');
	capture.close();
	refresh();tick();
	let timer;
	timer=loop.timer(1000,()=>{tick();timer.set(1000);});
	loop.run();loop.done();
}catch(e){if(getenv('ADZERO_OBSERVER_DEBUG')=='1')warn(sprintf('%J\n',e));result.available=false;result.reason='capture_failed';result.updated=state.monotime();try{state.atomic(dir+'/status.json',result);}catch(ignore){}exit(1);}
