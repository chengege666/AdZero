'use strict';
import * as fs from 'fs';
import * as net from 'socket';
import { cursor } from 'uci';
import * as lib from './dns-enhance-lib.uc';
import * as io from './dns-io.uc';
import * as retirement from './dns-cleanup.uc';
import { relay } from './dns-relay.uc';
import * as cache from './rules-cache.uc';
import * as handoff from './dns-handoff-lib.uc';
import * as dns from './routing-lib.uc';
import * as poolstate from './dns-pool-state.uc';
import { adapter_context } from './observe-state.uc';
const dir='/tmp/adzero-enhance',state='/etc/adzero',base=fs.dirname(sourcepath()),uid=fs.stat('/proc/self').uid;
const marker='AdZero DNS enhance v1',table='adzero_dns_enhance';
const adapter_state=adapter_context();
let action=shift(ARGV);if(action=='--')action=shift(ARGV);
function read(path,max){let s=fs.lstat(path);return s?.type=='file'&&s.size<=(max??65536)?fs.readfile(path):null;}
function decode(raw){try{return json(raw);}catch(e){return null;}}
function atomic(path,value){
	if(fs.lstat(path)?.type=='link')die('链接不是有效的状态文件。');
	let tmp=path+'.'+fs.readlink('/proc/self'),f=fs.open(tmp,'wx',0600),raw=sprintf('%J',value);
	if(!f)die('无法写入 DNS 增强状态。');let ok=f.write(raw)==length(raw),closed=f.close();
	if(!ok||!closed||!fs.rename(tmp,path)){fs.unlink(tmp);die('无法提交 DNS 增强状态。');}
}
function quote(s){return "'"+replace(''+s,/'/g,"'\\''")+"'";}
function command(argv){let p=fs.popen(join(' ',map(argv,quote))+' 2>/dev/null','r');if(!p)return null;let raw=p.read('all'),code=p.close();return code==0?raw:null;}
function settings(){let c=cursor();return lib.config(decode(c.get('adzero','main','dns_enhance')??'null'));}
function failover_settings(){let s=settings(),p=dns.profile(decode(cursor().get('adzero','main','dns_profile')??'null'));if(p.failover!=null)s.failover=p.failover;return s;}
function active(){let c=cursor();return c.get('adzero','main','enabled')=='1'&&c.get('adblock-fast','config','enabled')=='1'&&fs.lstat(state+'/managed')?.type=='file'&&!fs.stat(state+'/pause.json');}
function mutation_locked(){
	let path='/tmp/adzero.lock',lock=fs.lstat(path);if(!lock)return false;
	let owner=fs.lstat(path+'/owner');
	if(lock.type!='directory'||lock.uid!=uid||(lock.mode&077)||owner?.type!='file'||owner.uid!=uid||(owner.mode&077)||owner.size>128)return true;
	// These controller actions only inspect rules/update check metadata.
	// Unknown, incomplete and all mutating locks still withdraw the entry.
	return !match(trim(fs.readfile(path+'/owner',129)??''),/^[1-9][0-9]* (lookup|source-verify)$/);
}
function owns(){let v=decode(command(['nft','-j','list','table','inet',table]));return length(filter(v?.nftables??[],e=>e.table?.name==table&&e.table.comment==marker))==1;}
function cleanup(){
	try{
	let prior=decode(read(dir+'/owned.json'));
	if(fs.lstat(dir+'/owned.json')&&!prior)die('DNS 增强恢复记录无法读取，未清理连接。');
	retirement.release(prior,argv=>{
		let p=fs.popen(join(' ',map(argv,quote))+' 2>&1','r');if(!p)return {code:-1};
		let output=p.read('all'),code=p.close();return {code,output};
	});
	if(prior&&!fs.unlink(dir+'/owned.json'))die('DNS 增强恢复已完成，但记录未能清理。');
	}catch(e){try{atomic(dir+'/status.json',{state:'recovery_required',reason:'cleanup_pending',updated:io.now()});}catch(ignore){}die(e);}
}
function install(context){
	let raw=command(['nft','-j','list','table','inet',table]);if(raw&&!owns())die('AdZero DNS 表名已被其他配置使用。');
	let text=raw?'':sprintf('add table inet %s { comment "%s"; }\nadd set inet %s live { type ipv4_addr; flags timeout; timeout 8s; }\nadd chain inet %s input_dns { type nat hook prerouting priority -101; policy accept; }\nadd rule inet %s input_dns iifname "%s" ip daddr @live meta l4proto { tcp, udp } th dport 53 redirect to :5354\n',table,marker,table,table,table,context.lan.device);
	text+=sprintf('flush set inet %s live\nadd element inet %s live { %s timeout 8s }\n',table,table,context.lan.address);
	let path=dir+'/nft.'+fs.readlink('/proc/self'),f=fs.open(path,'wx',0600);if(!f)die('无法准备 DNS 接管。');let ok=f.write(text)==length(text),closed=f.close();
	// Persist intent before NAT can bind the first client packet. A crash
	// after installation must leave enough evidence to remove those bindings.
	atomic(dir+'/owned.json',context);
	let result=ok&&closed?command(['nft','-f',path]):null;fs.unlink(path);if(result==null)die('DNS 增强接管未完成。');
}
function context(){
	if(!active()||!settings().enabled||mutation_locked())return null;
	if(dns.profile(decode(cursor().get('adzero','main','dns_profile')??'null')).strict)return null;
	if(cursor().get('adblock-fast','config','dns')!='dnsmasq.servers')return null;
	let adapted=adapter_state();if(!adapted.present||adapted.stage!='configured_unverified')return null;
	if(index(['nailink','openclash'],adapted.plugin)>=0){
		let probe=decode(command([base+'/probe']));
		if(sprintf('%J',probe?.dns?.active_proxies)!=sprintf('%J',[adapted.plugin])||length(probe?.dns?.uncertain_proxies??[]))return null;
		let native=decode(command([base+'/adapter','alias-context']));
		if(!native||!handoff.lan_valid(native.lan))return null;
		for(let tcp in [false,true])if(!io.exchange(native.upstream_address??native.lan.address,native.port,lib.question('health.adzero.invalid'),tcp,0))return null;
		return {...native,updated:io.now()};
	}
	let c=decode(command([base+'/dns-handoff','context']));
	if(c&&adapted.plugin=='passwall'&&handoff.lan_valid(c.lan))return {...c,plugin:'passwall',updated:io.now()};
	let probe=decode(command([base+'/probe'])),proxies=probe?.dns?.active_proxies;
	if(type(proxies)!='array'||length(proxies)||length(probe.dns.uncertain_proxies??[])||probe.dns.dnsmasq_instances!=1)return null;
	if(adapted.plugin!='none')return null;
	let info=decode(command(['ubus','call','network.interface.lan','status'])),addresses=info?.['ipv4-address'];
	if(length(addresses??[])!=1)return null;
	let lan={device:info.l3_device,address:addresses[0].address,mask:addresses[0].mask};
	let u=cursor(),port=u.get('dhcp','@dnsmasq[0]','port');if(!handoff.lan_valid(lan)||port!=null&&port!='53')return null;
	// Probe the actual LAN listener, not a possibly different loopback instance.
	for(let tcp in [false,true])if(!io.exchange(lan.address,53,lib.question('health.adzero.invalid'),tcp,0))return null;
	return {port:53,lan,plugin:'none',updated:io.now()};
}
function published(){let value=decode(read(dir+'/status.json',4096));return value&&io.now()-value.updated<5?value:fs.lstat(dir+'/owned.json')?{state:'recovery_required',reason:'cleanup_pending'}:{state:'inactive',reason:'not_running'};}
if(!fs.lstat(dir)&&!fs.mkdir(dir,0700)&&!fs.lstat(dir))die('无法创建 DNS 增强目录。');
let st=fs.lstat(dir);if(st?.type!='directory'||st.uid!=uid||(st.mode&077))die('DNS 增强目录无效。');
function scan(){
	let c=cursor(),profile=dns.profile(decode(c.get('adzero','main','dns_profile')??'null')),s=settings(),groups={};
	let plugin=adapter_state().plugin,mode=c.get('passwall','@global[0]','dns_mode')??'tcp',routing_enabled=c.get('adzero','main','routing_enabled')=='1',port=profile.proxy_port??s.proxy_port,used=poolstate.paths(profile,plugin,mode,routing_enabled);
	for(let group in ['domestic','foreign'])groups[group]=map(profile[group].servers,address=>io.test(address,group=='foreign',port,used.domestic));
	let result={updated:time(),profile,plugin,routing_enabled,passwall_mode:plugin=='passwall'?mode:null,proxy_port:port,groups};atomic(dir+'/tests.json',result);return result;
}
function switch_plan(group,expected,next){
	let s=failover_settings(),c=cursor(),profile=dns.profile(decode(c.get('adzero','main','dns_profile')??'null')),tested=decode(read(dir+'/tests.json'));
	if(index(['domestic','foreign'],group)<0||!s.failover||!active()||c.get('adzero','main','routing_enabled')!='1'||
		profile[group].mode=='parallel'||profile[group].active!=expected||index(profile[group].servers,next)<0||tested?.plugin!=adapter_state().plugin||tested.routing_enabled!==true||tested.plugin=='passwall'&&tested.passwall_mode!=(c.get('passwall','@global[0]','dns_mode')??'tcp')||tested?.proxy_port!=(profile.proxy_port??s.proxy_port)||time()-tested.updated>45||
		sprintf('%J',profile)!=sprintf('%J',tested.profile)||!length(filter(tested.groups[group],r=>r.address==next&&r.ok)))die('DNS 备用切换条件已变化。');
	let adapter=decode(read(state+'/adapter.json',25000000));if(index(['nailink','passwall','openclash','nikki'],adapter?.plugin)<0||adapter.stage!='configured_unverified'||!adapter.split)die('当前代理分流尚未确认。');
	let current=decode(command([base+'/sources','list']));if(!current||current.pending)die('有待完成的规则变更。');
	let after=json(sprintf('%J',profile));after[group].active=next;
	let payload={revision:current.revision,routing_before:true,routing_enabled:true,dns_before:profile,dns:after,
		items:map(current.items,i=>({id:i.id,name:i.name,url:i.url,format:i.format,enabled:i.enabled}))};
	atomic(dir+'/switch-plan.json',payload);print(dir+'/switch-plan.json\n');
}
try{
	if(action=='invalidate'){atomic(dir+'/context.json',{updated:io.now()});}
	else if(action=='status'){print(sprintf('%J\n',{config:settings(),dns_failover:failover_settings().failover,profile:dns.profile(decode(cursor().get('adzero','main','dns_profile')??'null')),runtime:published(),tests:decode(read(dir+'/tests.json')),health:decode(read(dir+'/health.json'))}));}
	else if(action=='cleanup'){cleanup();atomic(dir+'/status.json',{state:'inactive',reason:'stopped',updated:io.now()});}
	else if(action=='save'){
		let p=decode(read(shift(ARGV),50000)),before=lib.config(p?.before),after=lib.config(p?.after),c=cursor();
		if(!p||sprintf('%J',before)!=sprintf('%J',settings())||length(c.changes('adzero')??{}))die('DNS 增强设置已变化，请重新读取。');
		if(!c.set('adzero','main','dns_enhance',sprintf('%J',after))||!c.commit('adzero'))die('无法保存 DNS 增强设置。');
	}
	else if(action=='test')scan();
	else if(action=='switch-plan')switch_plan(...ARGV);
	else if(action=='context-loop'){
		while(true){
			let value=null;try{value=context();}catch(e){}
			atomic(dir+'/context.json',value??{updated:io.now()});io.wait(2000);
		}
	}
	else if(action=='serve'){
		let server=null,key=null,rules={},allowed=[],identity=null,counts={cname:0,device:0},last=0,lease=null,created=io.now();
		while(true){
			let now=io.now();
			if(now-last>=1){
				last=now;let s=settings(),c=decode(read(dir+'/context.json')),ready=active()&&s.enabled&&c?.lan&&now-c.updated<8;
				if(s.enabled&&c&&now-c.updated>15&&now-created>15)die('DNS 上游检查进程未更新，增强入口已退出。');
				let fingerprint=ready?sprintf('%J',{...c,updated:null}):null;
				if(!ready||key!=fingerprint){server?.close();server=null;cleanup();key=null;identity=null;}
				if(ready){
					let stat=fs.stat('/var/run/adblock-fast/dnsmasq.servers'),id=sprintf('%J',[stat?.inode,stat?.mtime,stat?.ctime,stat?.size]);
					if(id!=identity){let list=cache.load('/var/run/adblock-fast/dnsmasq.servers','dnsmasq.servers','');rules={};for(let n in list)rules[n]=true;identity=id;}
					let u=cursor();allowed=u.get('adzero','main','allowed_domain')??[];if(type(allowed)!='array')allowed=[allowed];
					if(!server)server=relay(c,s,rules,allowed,d=>{counts[d.kind]++;});else server.configure(s,rules,allowed);
					key=fingerprint;lease=c;install(c);
				}
				atomic(dir+'/status.json',{state:server?'active':'waiting',reason:server?null:s.enabled?'unsupported_or_changing_path':'disabled',updated:now,counts,plugin:server?lease?.plugin:null,inspection:server?.inspection()??null});
			}
			if(server)server.step(100);else io.wait(500);
		}
	}
	else if(action=='monitor'){
		let boot=trim(fs.readfile('/proc/sys/kernel/random/boot_id')??''),saved=decode(read(dir+'/health.json')),hist=saved?.boot==boot?saved.groups??{}:{},last=0;
		while(true){
			let s=failover_settings(),c=cursor(),stamp=fs.lstat(state+'/adapter.json'),signature=sprintf('%J',[c.get('adzero','main','dns_profile'),s.proxy_port,stamp?.inode,stamp?.mtime,stamp?.size]);
			if(signature!=hist.signature){hist={signature,domestic:{failures:0,last_switch:hist.domestic?.last_switch??0},foreign:{failures:0,last_switch:hist.foreign?.last_switch??0}};}
			if(s.failover&&active()&&c.get('adzero','main','routing_enabled')=='1'&&io.now()-last>=60&&!fs.stat('/tmp/adzero.lock')){
				last=io.now();let result=scan();
				for(let g in ['domestic','foreign']){
					if(result.profile[g].mode=='parallel')continue;
					hist[g]=lib.fallback(hist[g],result.profile[g],result.groups[g],int(io.now()));
					if(hist[g].next){let rc=system(join(' ',map([base+'/ctl','dns-switch',g,result.profile[g].active,hist[g].next],quote)));hist[g].result=rc==0?'switched':'not_applied';break;}
				}
				atomic(dir+'/health.json',{updated:time(),boot,groups:hist});
			}
			io.wait(5000);
		}
	}
	else die('未知 DNS 增强操作。');
}catch(e){if(action=='serve')cleanup();fs.stderr.write('AdZero DNS enhance: '+e.message+'\n');exit(1);}
