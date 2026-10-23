'use strict';
import * as fs from 'fs';
import { cursor } from 'uci';
import * as lib from './dns-handoff-lib.uc';

// Only the default IPv4 LAN -> router DNS handoff is supported. Unknown
// topology, ACLs, multiple proxies and changing native rules fail closed.
const root=getenv('ADZERO_HANDOFF_ROOT')??'',dir=root+'/tmp/adzero-dns-handoff';
const uid=fs.stat('/proc/self')?.uid;
let action=shift(ARGV);if(action=='--')action=shift(ARGV);
function read(path,max){let s=fs.lstat(path);return s?.type=='file'&&s.size<=max?fs.readfile(path,max):null;}
function monotime(){return int(split(fs.readfile(root+'/proc/uptime')??'0',' ')[0]);}
function status(){
	let d=fs.lstat(dir),f=fs.lstat(dir+'/status.json');
	if(d?.type!='directory'||d.uid!=uid||(d.mode&077)!=0||f?.uid!=uid||(f.mode&077)!=0)return {state:'unavailable',reason:'stopped'};
	let raw=read(dir+'/status.json',2048),s;
	try{s=json(raw);}catch(e){}
	if(!s||s.schema!=1||type(s.updated)!='int'||monotime()-s.updated>20||s.updated>monotime())return {state:'unavailable',reason:'stopped'};
	return s;
}
if(action=='status'){print(sprintf('%J\n',status()));exit(0);}
if(action!='run'&&!(action=='step'&&root))exit(2);
if(!root&&uid!=0)exit(1);
if(!fs.stat(dir)&&!fs.mkdir(dir,0700))exit(1);
let stat=fs.lstat(dir);if(stat?.type!='directory'||stat.uid!=uid||(stat.mode&077)!=0)exit(1);
function start_identity(pid){
	let raw=fs.readfile(root+'/proc/'+pid+'/stat',8192)??'',fields=split(substr(raw,index(raw,')')+2),' ');
	return match(fields[19]??'',/^[0-9]+$/)?fields[19]:null;
}
const tmp=dir+'/command.'+fs.readlink('/proc/self');
function quote(v){return "'"+replace(''+v,/'/g,"'\\''")+"'";}
function command(argv,max,timeout){
	let f=fs.open(tmp,'wx',0600);if(!f)return null;f.close();
	let rc=system('ulimit -f 2048; '+join(' ',map(argv,quote))+' > '+quote(tmp)+' 2>/dev/null',timeout??2000);
	let data=read(tmp,max??65536);fs.unlink(tmp);
	return rc==0?data:null;
}
function decode(raw){try{return json(raw);}catch(e){return null;}}
if(action=='run'){
	// A private lease prevents a second worker. Validate PID start time so a
	// stale lease after a crash is reclaimed without removing a live lease.
	let path=dir+'/owner',old=fs.lstat(path),owner=decode(read(path,128));
	if(old){
		if(old.type!='file'||!owner||!match(owner.pid??'',/^[1-9][0-9]*$/)||!owner.start)exit(1);
		if(start_identity(owner.pid)==owner.start)exit(0);
		if(fs.lstat(path)?.inode!=old.inode||!fs.unlink(path))exit(1);
	}
	let f=fs.open(path,'wx',0600);if(!f)exit(1);
	let pid=fs.readlink('/proc/self'),data=sprintf('%J',{pid,start:start_identity(pid)});
	if(f.write(data)!=length(data)||!f.close())exit(1);
}
function binary(name){for(let p in ['/usr/sbin/','/usr/bin/','/sbin/','/bin/'])if(fs.access(root+p+name,'x'))return root+p+name;return null;}
let repaired=0,last_repair=null,previous=null;
function publish(state,reason){
	let data={schema:1,state,reason,repaired,last_repair,updated:monotime()},name=dir+'/status.'+fs.readlink('/proc/self');
	let f=fs.open(name,'wx',0600);if(!f)return;
	let raw=sprintf('%J',data),ok=f.write(raw)==length(raw);f.close();
	if(!ok||!fs.rename(name,dir+'/status.json'))fs.unlink(name);
}
function gate(){
	let uci=cursor(root+'/etc/config');
	if(uci.get('adzero','main','enabled')!='1'||uci.get('adblock-fast','config','enabled')!='1'||
		fs.lstat(root+'/etc/adzero/managed')?.type!='file'||fs.stat(root+'/etc/adzero/pause.json'))return false;
	let count=0,enabled=false,acl=false;
	uci.foreach('passwall','global',s=>{count++;enabled=s.enabled=='1'&&s.dns_redirect=='1';});
	uci.foreach('passwall','acl_rule',s=>{if(s.enabled=='1')acl=true;});
	// Unknown section variants are not accepted as an empty ACL inventory.
	uci.foreach('passwall','acl_rules',s=>{if(s.enabled=='1')acl=true;});
	return count==1&&enabled&&!acl;
}
function context(){
	if(!gate())return null;
	let raw=read(root+'/tmp/etc/passwall/acl/default/dnsmasq.conf',1048576),ports=[];
	for(let line in split(raw??'','\n')){let m=match(line,/^port=([0-9]+)$/);if(m)push(ports,int(m[1]));}
	if(length(ports)!=1||ports[0]<1024||ports[0]>65535)return null;
	let pid=null,identity=null,processes={};
	let bus=binary('ubus'),nft=binary('nft');if(!bus||!nft)return null;
	let lan=decode(command([bus,'call','network.interface.lan','status'],16384)),addresses=lan?.['ipv4-address'];
	if(type(addresses)!='array'||length(addresses)!=1)return null;
	lan={device:lan.l3_device,address:addresses[0].address,mask:addresses[0].mask};
	if(!lib.lan_valid(lan))return null;
	// bind-dynamic creates per-interface sockets; a wildcard socket is not
	// required. A loopback-only DNS socket cannot serve a LAN redirect.
	let address=join('',reverse(map(split(lan.address,'.'),p=>sprintf('%02X',int(p)))));
	for(let path in fs.glob(root+'/proc/[0-9]*/cmdline')??[]){
		let args=split(read(path,8192)??'', '\x00'),at=index(args,'-C');
		if(args[0]!='/tmp/etc/passwall/bin/dnsmasq_default'||at<0||args[at+1]!='/tmp/etc/passwall/acl/default/dnsmasq.conf')continue;
		let id=fs.basename(fs.dirname(path)),raw=read(root+'/proc/'+id+'/stat',8192)??'',fields=split(substr(raw,index(raw,')')+2),' ');
		let start=start_identity(id),parent=fields[1];
		if(!start||!match(parent??'',/^[0-9]+$/))return null;
		processes[id]={start,parent};
	}
	// Normal dnsmasq TCP workers retain their parent's argv. They are not
	// independent DNS instances and must not prevent a UDP handoff.
	let parents=filter(keys(processes),id=>!processes[processes[id].parent]);
	if(length(parents)!=1)return null;
	pid=parents[0];identity=processes[pid].start;
	let sockets={};
	for(let path in fs.glob(root+'/proc/'+pid+'/fd/*')??[]){let m=match(fs.readlink(path)??'',/^socket:\[([0-9]+)\]$/);if(m)sockets[m[1]]=true;}
	for(let protocol in ['udp','tcp']){
		let listening=false;
		for(let line in split(fs.readfile(root+'/proc/net/'+protocol)??'','\n')){
			let fields=split(trim(line),/[[:space:]]+/),local=split(fields[1]??'',':');
			if(length(local)==2&&index(['00000000',address],uc(local[0]))>=0&&int(local[1],16)==ports[0]&&sockets[fields[9]]&&fields[3]==(protocol=='tcp'?'0A':'07'))listening=true;
		}
		if(!listening)return null;
	}
	let rules=decode(command([nft,'-j','list','chain','inet','passwall','PSW_DNS']));
	if(!lib.target(rules,ports[0]))return null;
	let dispatch=decode(command([nft,'-j','list','chain','inet','passwall','dstnat']));
	if(!lib.dispatch(dispatch))return null;
	// Drop changing counters, retain handles, match expressions and redirect.
	for(let item in rules.nftables)if(item.rule)item.rule.expr=filter(item.rule.expr,e=>!e.counter);
	for(let item in dispatch.nftables)if(item.rule)item.rule.expr=filter(item.rule.expr,e=>!e.counter);
	return {pid,identity,port:ports[0],lan,rules,dispatch};
}
function sole_passwall(){
	let data=decode(command([root?root+'/usr/libexec/adzero/probe':fs.dirname(sourcepath())+'/probe'],65536,5000));
	return type(data?.dns?.active_proxies)=='array'&&length(data.dns.active_proxies)==1&&data.dns.active_proxies[0]=='passwall'&&
		type(data.dns.uncertain_proxies)=='array'&&!length(data.dns.uncertain_proxies);
}
function key(c){return sprintf('%J',c);}
function tick(){
	let current=context();
	if(!current){previous=null;publish('skipped',gate()?'unsupported_context':'inactive');return;}
	let conntrack=binary('conntrack');if(!conntrack){publish('unavailable','conntrack_missing');return;}
	if(previous!=key(current)){previous=key(current);publish('waiting','stabilizing');return;}
	let argv=[conntrack,'-L','-f','ipv4','-p','udp','--orig-dst',current.lan.address,'--dport','53','-o','extended,id'];
	let candidates=lib.plan(command(argv,1048576),current.lan,current.port);
	if(candidates==null){publish('unavailable','inventory_failed');return;}
	if(!length(candidates)){publish('ready',null);return;}
	if(!sole_passwall()){publish('skipped','proxy_unconfirmed');return;}
	// Bound each pass, including repeated native-context checks.
	for(let c in slice(candidates,0,16)){
		// Native restarts, rule replacement, disable/pause and LAN changes must
		// stop the batch. Exact reply filters protect a newly correct tuple.
		if(key(context())!=key(current)||!gate()){previous=null;publish('waiting','context_changed');return;}
		if(command([conntrack,...lib.deletion(c)],4096)==null){publish('waiting','retry');return;}
		repaired++;last_repair=time();
	}
	publish('ready',null);
}
try{
	if(action=='step'){
		// Test-only step supports an explicit previous fingerprint fixture.
		previous=read(dir+'/previous',65536);tick();
		if(previous!=null)fs.writefile(dir+'/previous',previous);exit(0);
	}
	let loop=require('uloop');loop.init();tick();let timer;
	timer=loop.timer(5000,()=>{try{tick();}catch(e){previous=null;publish('unavailable','check_failed');}timer.set(5000);});
	loop.run();loop.done();
}catch(e){publish('unavailable','check_failed');exit(1);}
