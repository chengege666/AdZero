'use strict';
import * as fs from 'fs';
import { cursor } from 'uci';
import * as dns from './routing-lib.uc';
import * as lib from './dns-guard-lib.uc';
import { lan_valid,plan,deletion } from './dns-handoff-lib.uc';
import { now,wait,exchange } from './dns-io.uc';
import { question } from './dns-enhance-lib.uc';
const root=getenv('ADZERO_GUARD_ROOT')??'',state=root+'/etc/adzero/dns-guard.json',c=cursor(root+'/etc/config');
let action=shift(ARGV);if(action=='--')action=shift(ARGV);
function read(path){let s=fs.lstat(path);if(s?.type!='file'||s.uid!=fs.stat('/proc/self').uid||(s.mode&077)||s.size>16000)return null;try{return json(fs.readfile(path));}catch(e){return null;}}
function profile(){c.unload('adzero');return dns.profile(json(c.get('adzero','main','dns_profile')??'null'));}
function same(a,b){return sprintf('%J',a)==sprintf('%J',b);}
function quote(s){return "'"+replace(s,/'/g,"'\\''")+"'";}
function execute(argv,input){let f=fs.popen(join(' ',map(argv,quote))+' 2>&1','r');if(!f)die('严格 DNS 检查无法运行。');let data=f.read('all'),code=f.close();if(code!=0)die('严格 DNS 命令失败，保护记录已保留。');return data;}
function atomic(value){if(fs.lstat(state)?.type=='link')die('严格 DNS 恢复记录无效。');let path=state+'.'+fs.readlink('/proc/self'),f=fs.open(path,'wx',0600),raw=sprintf('%J',value);if(!f)die('严格 DNS 恢复记录保存失败。');let ok=f.write(raw)==length(raw),closed=f.close();if(!ok||!closed||!fs.rename(path,state)){fs.unlink(path);die('严格 DNS 恢复记录保存失败。');}}
function lan(){let data=json(execute(['ubus','call','network.interface.lan','status'])),rows=data['ipv4-address'];if(type(rows)!='array'||length(rows)!=1)die('严格模式需要单个默认 LAN IPv4 地址。');let value={device:data.l3_device,address:rows[0].address,mask:rows[0].mask};if(!lan_valid(value))die('严格模式无法确认 LAN，原设置保持不变。');return value;}
function owned(){let data=json(execute(['nft','-j','list','tables']));if(type(data.nftables)!='array')die('无法核对严格 DNS 防火墙。');let exists=length(filter(data.nftables,v=>v.table?.family=='inet'&&v.table.name==lib.table));if(!exists)return false;
	let t=json(execute(['nft','-j','list','table','inet',lib.table]));if(length(filter(t.nftables??[],v=>v.table?.family=='inet'&&v.table.name==lib.table&&v.table.comment==lib.marker))!=1)die('严格 DNS 表由其他配置管理，未覆盖。');return true;}
function commit_firewall(value,ready,bootstrap){let exists=owned(),script=(exists?'delete table inet '+lib.table+'\n':'')+lib.rules(value.lan,value.profile,ready,bootstrap),path=root+'/tmp/adzero-dns-guard.'+fs.readlink('/proc/self');
	let f=fs.open(path,'wx',0600);if(!f)die('无法准备严格 DNS 防火墙。');let ok=f.write(script)==length(script),closed=f.close();if(!ok||!closed){fs.unlink(path);die('无法准备严格 DNS 防火墙。');}try{execute(['nft','-c','-f',path]);execute(['nft','-f',path]);}catch(e){fs.unlink(path);die(e);}fs.unlink(path);
}
function pinned(value){c.unload('dhcp');return value?.pin&&same(c.get('dhcp',value.section,'server'),value.pin.server)&&same(c.get('dhcp',value.section,'noresolv'),value.pin.noresolv);}
function values(section){return {server:c.get('dhcp',section,'server')??null,noresolv:c.get('dhcp',section,'noresolv')??null};}
function native_before(){c.unload('openclash');if(c.get('openclash','config','redirect_dns')!='1')return null;return {server:c.get('openclash','config','dnsmasq_server')??null,noresolv:c.get('openclash','config','dnsmasq_noresolv')??null};}
function retire_udp(value){
	let rows=plan(execute(['conntrack','-L','-f','ipv4','-p','udp','--dport','53','-o','extended,id']),value.lan,53);
	if(rows==null)die('旧 DNS 连接范围无法确认，严格模式继续阻断。');
	for(let row in rows){let proc=fs.popen(join(' ',map(['conntrack',...deletion(row)],quote))+' 2>&1','r');if(!proc)die('旧 DNS 连接清理未确认。');let text=proc.read('all'),code=proc.close();if(code!=0&&!(code==1&&match(text??'',/0 flow entries have been deleted/)))die('旧 DNS 连接清理未确认。');}
}
function restart_dns(){let path=root+'/etc/init.d/dnsmasq',head=split(fs.readfile(path,256)??'','\n')[0],args=match(head,/^#!\/bin\/sh[[:space:]]+\/etc\/rc.common/)?['/bin/sh',root+'/etc/rc.common',path,'restart']:['/bin/sh',path,'restart'];
	let timeout=fs.access(root+'/usr/libexec/timeout-coreutils','x')?root+'/usr/libexec/timeout-coreutils':root+'/usr/bin/timeout';execute([timeout,'-k','5','30',...args]);}
function hold(value){let bootstrap=!!pinned(value);commit_firewall(value,false,bootstrap);value.state='held';value.bootstrap=bootstrap;value.updated=now();value.boot=fs.readfile('/proc/sys/kernel/random/boot_id');atomic(value);}
function cleanup(value){if(!value){if(owned())die('严格 DNS 缺少恢复记录，未删除保护。');return;}
	hold(value);if(length(c.changes('dhcp')?.dhcp??[]))die('DNS 存在未提交修改，请先保存或撤销。');let changed=false;
	for(let key in value.pin?['server','noresolv']:[])if(same(c.get('dhcp',value.section,key),value.pin[key])){let old=value.before[key];if(old==null)c.delete('dhcp',value.section,key);else c.set('dhcp',value.section,key,old);changed=true;}
	if(changed){if(!c.commit('dhcp'))die('原 DNS 恢复失败。');restart_dns();}
	if(owned())execute(['nft','delete','table','inet',lib.table]);if(!fs.unlink(state))die('严格 DNS 已退出，但恢复记录未清理。');
}
try{
	let value=read(state),p=profile();if(fs.lstat(state)&&!value)die('严格 DNS 恢复记录无效。');
	if(action=='status'){print(sprintf('%J',value?{state:value.state,plugin:value.plugin,scope:'default_lan_ipv4_dns',ipv6_dns:'blocked',dot:'blocked',doh:'device_policy_required',bootstrap:'domestic_group',updated:value.updated}:{state:'off'}));exit(0);}
	if(action=='socks'){if(!p.proxy_port)die('本机 SOCKS5 端口未配置。');let raw=exchange(p.foreign.active,53,question('health.adzero.invalid'),true,p.proxy_port);if(!raw||index([0,3],ord(raw,3)&15)<0)die('本机 SOCKS5 DNS 路径未通过检查，尚未更改代理。');exit(0);}
	if(action=='preflight'){
		if(!p.strict&&!value)exit(0);lan();owned();let rows=[];c.foreach('dhcp','dnsmasq',s=>push(rows,s));if(length(rows)!=1||(rows[0].port??'53')!='53'||length(c.changes('dhcp')?.dhcp??[]))die('严格模式需要单个 53 端口 dnsmasq，且没有未提交修改。');exit(0);
	}
	if(action=='cleanup'){cleanup(value);exit(0);}
	if(action=='boot-ensure'){
		if(!p.strict)exit(0);
		if(value){if(value.boot!=fs.readfile('/proc/sys/kernel/random/boot_id')||!owned())hold(value);exit(0);}
		action='ensure';
	}
	if(action=='hold'||action=='ensure'){
		if(!p.strict&&!value)exit(0);
		let current_lan=p.strict?lan():value?.lan;
		if(action=='ensure'&&value?.state=='active'&&same(value.lan,current_lan)&&value.boot==fs.readfile('/proc/sys/kernel/random/boot_id')&&pinned(value)&&owned())exit(0);
		if(!value){let rows=[];c.foreach('dhcp','dnsmasq',s=>push(rows,s));if(length(rows)!=1)die('严格模式需要单个 dnsmasq。');value={schema:1,lan:lan(),section:rows[0]['.name'],before:{server:rows[0].server??null,noresolv:rows[0].noresolv??null},profile:p,state:'held'};atomic(value);}
		value.lan=current_lan;
		hold(value);exit(0);
	}
	if(action=='pin'){
		if(!value)die('严格 DNS 缺少接管记录。');let plugin=shift(ARGV),target=shift(ARGV);if(index(['nailink','passwall','openclash','nikki'],plugin)<0||!match(target??'',/^(127[.]0[.]0[.]1#[1-9][0-9]{3,4})$/))die('严格 DNS 接入端口无效。');
		if(int(split(target,'#')[1])>65535)die('严格 DNS 接入端口无效。');
		let was_pinned=!!pinned(value),desired={server:[target],noresolv:'1'},current=values(value.section),handoff=value.plugin&&value.plugin!=plugin;
		if(value.pin&&!was_pinned&&!(value.state=='held'&&(same(current,value.native_before)||same(current,value.before)||same(current,desired))))die('系统 DNS 已被外部修改，严格模式保持阻断。');if(length(c.changes('dhcp')?.dhcp??[]))die('系统 DNS 有未提交修改。');
		if(value.plugin==plugin&&same(value.pin?.server,[target])&&pinned(value)&&same(dns.effective(value.profile),dns.effective(p)))exit(0);
		// A stopped OpenClash restores its own DNS snapshot. Retire its port,
		// rather than preserving that now-dead port as the new proxy's baseline.
		let baseline=handoff&&value.plugin=='openclash'?value.native_before??value.before:value.before;
		if(handoff&&plugin=='openclash'){
			let saved=native_before();
			// OpenClash may have started while our former pin was installed.
			// Repair only that exact generated backup; never replace a user value.
			if(saved&&same(saved.server,value.pin?.server)){
				if(length(c.changes('openclash')?.openclash??[]))die('OpenClash 有未保存修改，严格 DNS 保持阻断。');
				value.native_repair={before:saved,after:baseline};atomic(value);
				for(let key in ['server','noresolv']){let option=key=='server'?'dnsmasq_server':'dnsmasq_noresolv';if(baseline[key]==null)c.delete('openclash','config',option);else c.set('openclash','config',option,baseline[key]);}
				if(!c.commit('openclash'))die('OpenClash 原生 DNS 恢复快照未确认。');
			}
			value.before=desired;
		}else if(handoff)value.before=baseline;
		if(plugin=='openclash')value.native_before=native_before()??baseline;else delete value.native_before;
		value.plugin=plugin;value.profile=p;value.pin={server:[target],noresolv:'1'};atomic(value);
		if(!c.set('dhcp',value.section,'server',value.pin.server)||!c.set('dhcp',value.section,'noresolv','1')||!c.commit('dhcp'))die('严格 DNS 路径保存失败。');restart_dns();hold(value);exit(0);
	}
	if(action=='ready'){
		if(!value||!p.strict||!pinned(value)||!same(dns.effective(value.profile),dns.effective(p)))die('严格 DNS 路径尚未确认。');
		let a=fs.lstat(root+'/etc/adzero/adapter.json');if(a?.type!='file'||a.size>25000000)die('严格 DNS 接入记录尚未确认。');
		let adapter=json(fs.readfile(root+'/etc/adzero/adapter.json'));if(adapter.plugin!=value.plugin||adapter.stage!='configured_unverified')die('严格 DNS 接入尚未完成。');
		let identity={inode:a.inode,mtime:a.mtime,size:a.size};
		for(let tcp in [false,true]){let raw=exchange('127.0.0.1',int(split(value.pin.server[0],'#')[1]),question('health.adzero.invalid'),tcp,0);if(!raw||index([0,3],ord(raw,3)&15)<0)die('严格 DNS 接入尚未通过 UDP／TCP 应答检查，继续保持阻断。');}
		if(value.state=='active'&&same(value.adapter,identity)&&owned())exit(0);
		retire_udp(value);commit_firewall(value,true,true);value.adapter=identity;value.state='active';value.bootstrap=true;value.boot=fs.readfile('/proc/sys/kernel/random/boot_id');value.updated=now();atomic(value);exit(0);
	}
	if(action=='watch'){
		while(true){c.unload('adzero');if(c.get('adzero','main','enabled')!='1')break;value=read(state);if(value){let a=fs.lstat(root+'/etc/adzero/adapter.json'),raw=execute([root+'/usr/libexec/adzero/probe']),inventory=json(raw),active=inventory.dns?.active_proxies,stable=a?.type=='file'&&same({inode:a.inode,mtime:a.mtime,size:a.size},value.adapter),current_lan=lan(),moved=!same(current_lan,value.lan);
			if(!owned()||!pinned(value)||!stable||moved||type(active)!='array'||length(active)!=1||active[0]!=value.plugin||length(inventory.dns.uncertain_proxies??[])||!same(dns.effective(profile()),dns.effective(value.profile)))if(value.state!='held'||!!pinned(value)!==value.bootstrap||moved||!owned()){value.lan=current_lan;hold(value);}
		}wait(1000);}exit(0);
	}
	die('严格 DNS 操作无效。');
}catch(e){if(action=='watch'||action=='ready'){let value=read(state);if(value){let failed=action=='watch';try{hold(value);}catch(ignore){failed=true;}if(failed){value.state='error';try{atomic(value);}catch(ignore){}}}}fs.stderr.write('AdZero strict DNS: '+e.message+'\n');exit(1);}
