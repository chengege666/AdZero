'use strict';
// Configuration transactions run only under ctl's existing operation lock.
import * as fs from 'fs';
import { cursor } from 'uci';
import * as lib from './source-lib.uc';
import * as progress from './progress-lib.uc';
import * as snapshots from './source-cache.uc';
import * as dns from './routing-lib.uc';
import { hostname } from './policy-lib.uc';
const root = getenv('ADZERO_SOURCES_ROOT') ?? '';
const dir = getenv('ADZERO_STATE_DIR') ?? root + '/etc/adzero';
const uci = cursor(root + '/etc/config');
const config = root + '/etc/config/adblock-fast', journal = dir + '/sources-pending.json';
function read(path) { let raw=fs.readfile(path); return raw == null ? null : json(raw); }
function same(a,b) { return sprintf('%J',a) == sprintf('%J',b); }
function atomic(path,text,mode) {
	if (fs.lstat(path)?.type == 'link') die('规则恢复目标为链接，已停止操作。');
	if (!fs.stat(dir) && !fs.mkdir(dir,0700)) die('无法创建规则恢复目录。');
	let temp=path+'.new', file=fs.open(temp,'wx',mode ?? 0600);
	if (!file) die('无法建立规则恢复文件。');
	let written=file.write(text),closed=file.close();
	if (written != length(text) || !closed || !fs.chmod(temp,mode ?? 0600) || !fs.rename(temp,path)) { fs.unlink(temp); die('规则恢复记录提交失败。'); }
}
function statistic(type,key,value){
	return type=='file_url'&&((index(['size','adzero_domains','adzero_skipped','adzero_updated','adzero_checked'],key)>=0&&match(''+value,/^[0-9]+$/))||key=='adzero_validation'&&index(['validated','backend_only','unchecked'],value)>=0);
}
function normalized_model(rows){
	// Schema 1 journals and schema 2 caches from older releases contain these
	// generated counters. Ignore only the same recognized values as live UCI;
	// retain all actual options and identities when checking for outside edits.
	if(type(rows)!='array')return null;
	let result=[];
	for(let row in rows){
		if(type(row)!='object'||type(row.type)!='string'||type(row.values)!='object'||row.id!=null&&type(row.id)!='string')return null;
		let values={};for(let key in sort(keys(row.values)))if(!statistic(row.type,key,row.values[key]))values[key]=row.values[key];
		push(result,{id:row.id,type:row.type,values});
	}return result;
}
function same_model(a,b){let left=normalized_model(a),right=normalized_model(b);return left!=null&&right!=null&&same(left,right);}
function model() {
	let result=[];
	uci.foreach('adblock-fast',null,s => {
		let values={};
		for (let key in sort(keys(s))) if (substr(key,0,1) != '.' && !statistic(s['.type'],key,s[key])) values[key]=s[key];
		// libuci regenerates anonymous IDs after deletion. Compare their ordered
		// contents, while retaining the actual identity of explicitly named ones.
		push(result,{id:s['.anonymous'] ? null : s['.name'],type:s['.type'],values});
	});
	return result;
}
function selected() {
	let result=[];
	uci.foreach('adblock-fast','file_url',s => { if ((s.action ?? 'block') == 'block' && s.url) push(result,s); });
	return result;
}
function semantic(package,context){
	let rows=[];
	function canonical(value){if(type(value)=='array')return map(value,v=>canonical(v));if(type(value)!='object')return value;let out={};for(let k in sort(keys(value)))out[k]=canonical(value[k]);return out;}
	(context??uci).foreach(package,null,s=>{
		let values={};for(let key in sort(keys(s)))if(substr(key,0,1)!='.'&&!statistic(s['.type'],key,s[key])){
			let value=s[key];if(package=='adzero'&&index(['dns_profile','dns_enhance'],key)>=0)try{value=canonical(json(value));}catch(e){}
			values[key]=value;
		}
		push(rows,{id:s['.name'],type:s['.type'],values});
	});return rows;
}
function revision(context){
	let value=snapshots.fingerprint(sprintf('%J',{schema:2,backend:semantic('adblock-fast',context),adzero:semantic('adzero',context)}),root);
	if(!value)die('无法计算配置版本，请核对临时目录权限。');return value;
}
function require_rules(items){
	if(uci.get('adblock-fast','config','enabled')=='1'&&!length(filter(items,s=>s.enabled!==false&&s.enabled!='0'))&&!length(uci.get('adblock-fast','config','blocked_domain')??[])){
		progress.failure('empty_ruleset');die('本次选择没有启用订阅或手动拦截项。请保留一项规则；暂停全部过滤请使用暂停或保护开关。');
	}
}
function capacity_key(){
	return snapshots.fingerprint(sprintf('%J',{sources:map(selected(),s=>({id:s['.name'],url:s.url,enabled:s.enabled!='0',format:s.adzero_format??filter(lib.catalog,c=>c.url==s.url)[0]?.format??'auto'})),blocked:uci.get('adblock-fast','config','blocked_domain')??[]}),root);
}
function capacity_receipt(count,unknown,total,over){
	let value={schema:1,at:time(),selection:capacity_key(),state:over?'over_limit':length(unknown)?'unknown':'complete',known_domains:count,unknown_sources:unknown,total,limit:500000,source_bytes_limit:25000000,scope:'unique_candidates_before_allow_and_optimization'};
	atomic(dir+'/sources-capacity.json',sprintf('%J',value));return value;
}
function clean_uci(context) {
	let current=context??uci;
	// adblock-fast leaves numeric file_url.size counters in the shared delta
	// directory. They describe downloaded lists, not a user's pending edits.
	for(let change in current.changes('adblock-fast')?.['adblock-fast'] ?? []) {
		if(change[0]=='set' && statistic(current.get('adblock-fast',change[1]),change[2],change[3]))continue;
		progress.failure('config_conflict');
		die('后端有尚未提交的外部修改，请先保存或撤销后再管理规则。');
	}
}
function guard_revision(expected){
	let current=cursor(root+'/etc/config');clean_uci(current);
	if(length(current.changes('adzero')?.adzero??[])||revision(current)!=expected){progress.failure('config_conflict');die('预检期间配置被其他操作修改，尚未提交或重载。请重新读取并核对。');}
}
function checksum(path){
	if(fs.lstat(path)?.type!='file'||!(fs.stat(path)?.size>0)||fs.stat(path).size>25000000)return null;
	let quote=s=>"'"+replace(s,/'/g,"'\\''")+"'";
	let proc=fs.popen('sha256sum '+quote(path)+' 2>/dev/null','r');if(!proc)return null;
	let output=proc.read('all'),code=proc.close(),digest=split(output??'',' ')[0];
	return code==0&&match(digest,/^[a-f0-9]{64}$/)?digest:null;
}
function dns_profile(){return dns.profile(json(uci.get('adzero','main','dns_profile')??'null'));}
function list() {
	let items=[];
	for (let s in selected()) {
		let builtin=filter(lib.catalog,c=>c.url == s.url)[0], valid=true;
		try { lib.url(s.url); } catch(e) { valid=false; }
		push(items,{id:s['.name'],name:s.name ?? builtin?.name ?? '已有规则',url:s.url,enabled:s.enabled != '0',
			format:s.adzero_format ?? builtin?.format ?? s.adzero_detected_format ?? 'unknown',catalog_id:builtin?.id ?? null,https:valid,
			validation:s.adzero_validation ?? (s.adzero_domains?'validated':'unchecked'),
			domains: s.adzero_domains ? int(s.adzero_domains) : null,skipped:int(s.adzero_skipped??'0'),updated:s.adzero_updated ? int(s.adzero_updated) : null,
			checked:s.adzero_checked?int(s.adzero_checked):s.adzero_updated?int(s.adzero_updated):null});
	}
	let legacy;try{legacy=json(uci.get('adzero','main','dns_enhance')??'null');}catch(e){}
	let capacity=null;try{capacity=read(dir+'/sources-capacity.json');if(capacity){capacity.current=capacity.selection==capacity_key();delete capacity.selection;}}catch(e){}
	return {catalog:lib.catalog,items,revision:revision(),capacity,dns:dns_profile(),dns_failover:dns_profile().failover??legacy?.failover??false,dns_test_proxy_port:legacy?.proxy_port??0,pending:!!read(journal),last:read(dir+'/sources-last.json')};
}
function download(address,kind,fresh,manual) {
	lib.url(address);if(kind!='auto')lib.format(kind);
	let snapshot=snapshots.load(address,root);
	if(manual){
		if(!snapshot)die('没有可用的本地规则快照，请先更新订阅后再校验。');
		progress.stage('validating');
		let raw=fs.readfile(snapshot.path),result;
		try{result=kind=='auto'?lib.detect(raw):lib.inspect(raw,kind);if(!result)die('本地快照无法按支持的格式校验。');}
		catch(e){progress.failure(progress.source_reason(e.message)??'source_format');die(e);}
		snapshots.save(address,raw,root,kind,result);return {...result,bytes:length(raw)};
	}
	if(snapshot&&!fresh&&!uci.get('adblock-fast','config','curl_additional_param')){
		progress.stage('checking');
		let value=snapshots.summary(snapshot,kind)??snapshots.parsed(snapshot,kind);
		if(value){if(value.names)snapshots.renew(snapshot,kind,value);return {...value,bytes:fs.stat(snapshot.path).size,reused:true};}
		try{
			progress.stage('validating');
			let raw=fs.readfile(snapshot.path),checked=kind=='auto'?lib.detect(raw):lib.inspect(raw,kind);
			snapshots.save(address,raw,root,kind,checked);return checked?{...checked,bytes:length(raw)}:null;
		}catch(e){}
	}
	// Fetch and validate first. A failed refresh must not destroy the last
	// verified snapshot needed by a later independent reload or recovery.
	progress.stage('downloading');
	let path=root+'/tmp/adzero-source-check';
	if (root && !fs.stat(root+'/tmp')) fs.mkdir(root+'/tmp',0700);
	if (fs.lstat(path)) die('规则校验临时文件已存在，请检查未完成操作。');
	let file=fs.open(path,'wx',0600);if (!file || !file.close()) die('无法创建临时规则文件。');
	try {
		let fixture=getenv('ADZERO_SOURCE_FETCH_FIXTURE');
		let argv = root && fixture ? [fixture,address,path] : ['curl','--fail','--location','--silent','--show-error','--proto','=https','--proto-redir','=https','--connect-timeout','10','--max-time','60','--max-filesize','25000000','--output',path,address];
		// Quiet output: a custom subscription URL may contain a private token.
		let quote=s=>"'"+replace(s,/'/g,"'\\''")+"'";
		if (system(join(' ',map(argv,quote))+' >/dev/null 2>&1',65000) != 0) {progress.failure('source_download');die('规则下载失败，请检查 HTTPS 地址和网络。');}
		let raw=fs.readfile(path,25000001),result,identical=snapshot&&raw==fs.readfile(snapshot.path);
		try{
			progress.stage(identical?'checking':'validating');
			if(identical)result=snapshots.summary(snapshot,kind)??snapshots.parsed(snapshot,kind);
			if(!result){progress.stage('validating');result=kind=='auto'?lib.detect(raw):lib.inspect(raw,kind);}
		}catch(e){progress.failure(progress.source_reason(e.message)??'source_format');die(e);}
		// From here the fresh response was accepted. If its optional cache
		// write fails, the backend must not replay older bytes as this update.
		if(fresh)snapshots.invalidate(address,root);
		let reused=!!result&&identical&&snapshots.renew(snapshot,kind,result);
		if(!reused){if(result&&!result.names)result=kind=='auto'?lib.detect(raw):lib.inspect(raw,kind);snapshots.save(address,raw,root,kind,result);}
		fs.unlink(path);return result?{...result,bytes:length(raw),reused}:null;
	} catch(e) { fs.unlink(path);die(e); }
}
// Only verified local snapshots participate here. Never re-download unchanged
// subscriptions just to count them, and never add per-list summary counts:
// overlap must remain valid even when the sum of individual counts is large.
function capacity_names(s,kind,checked){
	if(type(checked?.names)=='array')return checked.names;
	let snapshot=snapshots.load(s.url,root);if(!snapshot)return null;
	let parsed=snapshots.parsed(snapshot,kind);if(parsed)return parsed.names;
	// A corrupt/missing optional parsed cache may still have a digest-verified
	// raw snapshot. Re-parse locally; unsupported legacy formats remain native.
	try{
		let raw=fs.readfile(snapshot.path),value=kind=='auto'?lib.detect(raw):lib.inspect(raw,kind);
		return value?.names??null;
	}catch(e){return null;}
}
function validate_sources(only,fresh,manual,strict) {
	let union={}, count=0,enabled=filter(selected(),s=>s.enabled!='0'),position=0,unknown=[];
	function include(names){for(let name in names){union[name]=true;if(length(union)>500000){capacity_receipt(length(union),unknown,length(enabled),true);progress.failure('source_limit');die('所选规则合计超过 50 万个域名，请减少列表。');}}}
	let manual_blocks=uci.get('adblock-fast','config','blocked_domain')??[];
	include(map(type(manual_blocks)=='array'?manual_blocks:[manual_blocks],name=>hostname(name)));
	for (let s in enabled) {
		position++;
		let checking=only==null||(type(only)=='array'?index(only,s['.name'])>=0:s['.name']==only);
		let builtin=filter(lib.catalog,c=>c.url == s.url)[0],kind=s.adzero_format ?? builtin?.format ?? 'auto';
		let checked;
		if(checking){
			progress.source(position,length(enabled));
			try{checked=download(s.url,kind,fresh,manual);}catch(e){progress.failure(progress.source_reason(e.message)??'source_check');die(e);}
		}
		let names=capacity_names(s,kind,checked);
		// An unchanged source without a usable local proof must be checked
		// before a live rebuild, rather than silently contributing zero.
		if(!names&&!checking&&strict){checked=download(s.url,kind,false,false);names=capacity_names(s,kind,checked);}
		if(names){
			progress.source(position,length(enabled));
			include(names);
		}else push(unknown,position);
		if(!checking)continue;
		if(!uci.set('adblock-fast',s['.name'],'adzero_checked',''+time()))die('无法保存规则检查时间。');
		// The backend uses this size to schedule downloads. Without it, a new
		// source triggers another HEAD request despite already being downloaded.
		let snapshot=checked?null:snapshots.load(s.url,root),bytes=checked?.bytes??(snapshot?fs.stat(snapshot.path)?.size:null);
		if(bytes>0&&bytes<=25000000&&!uci.set('adblock-fast',s['.name'],'size',''+bytes))die('无法保存规则下载大小。');
		if(!checked){
			uci.delete('adblock-fast',s['.name'],'adzero_domains');uci.delete('adblock-fast',s['.name'],'adzero_detected_format');uci.delete('adblock-fast',s['.name'],'adzero_skipped');
			if(!uci.set('adblock-fast',s['.name'],'adzero_validation','backend_only')||!uci.set('adblock-fast',s['.name'],'adzero_updated',''+time()))die('无法保存规则检查记录。');
			continue;
		}
		names=names??[];
		let updated=checked.reused&&s.adzero_updated?s.adzero_updated:''+time();
		if (!uci.set('adblock-fast',s['.name'],'adzero_domains',''+(checked.domains??length(names))) || !uci.set('adblock-fast',s['.name'],'adzero_skipped',''+checked.skipped) || !uci.set('adblock-fast',s['.name'],'adzero_updated',updated)) die('无法保存规则校验结果。');
		if(!uci.set('adblock-fast',s['.name'],'adzero_validation','validated')||(kind=='auto'&&!uci.set('adblock-fast',s['.name'],'adzero_detected_format',checked.format)))die('无法保存规则格式记录。');
		count++;
	}
	capacity_receipt(length(union),unknown,length(enabled),false);
	if(strict&&length(unknown)){progress.source(unknown[0],length(enabled));progress.failure('source_capacity_unknown');die('部分来源无法完整预检容量，尚未提交或重载。请选择域名、Hosts 或基础 DNS Adblock 格式；现有配置保留。');}
	progress.source(null);
	return count;
}
function filtering_model(entries){
	let rows=normalized_model(entries);if(rows==null)return null;
	return map(filter(rows,s=>s.type!='file_url'||s.values.enabled!='0'),s=>{
		let values={};
		for(let k in keys(s.values))if(s.type!='file_url'||k!='name'&&k!='size'&&substr(k,0,7)!='adzero_')values[k]=s.values[k];
		return {id:s.type=='file_url'?null:s.id,type:s.type,values};
	});
}
function cache_path(){
	let mode=uci.get('adblock-fast','config','dns');
	return index(['dnsmasq.servers','dnsmasq.addnhosts'],mode)>=0?root+'/var/run/adblock-fast/'+mode:null;
}
function reusable_output(prior){
	let state=null,path=cache_path();try{state=read(dir+'/backend-cache.json');}catch(e){}
	if(!path||state?.schema!=2||!match(state.sha256??'',/^[a-f0-9]{64}$/))return false;
	let current=filtering_model(model());
	return same(current,filtering_model(prior))&&same(current,filtering_model(state.config))&&checksum(path)==state.sha256;
}
function begin(action,args) {
	if (read(journal)) die('上次规则变更尚未恢复，请先关闭并恢复。');
	clean_uci();
	let before=fs.readfile(config), prior=model(),expected=revision();
	if (before == null) die('无法读取现有规则配置。');
	let id=shift(args), address,removing=false;
	if (action == 'add') {
		let name=shift(args);address=shift(args);let kind=shift(args);
		if (id) {
			let item=filter(lib.catalog,c=>c.id == id)[0];if (!item) die('未知规则库项目。');
			name=item.name;address=item.url;kind=item.format;
		}
		name=lib.title(name);address=lib.url(address);kind=lib.format(kind);
		if (length(selected()) >= 30) die('最多管理 30 个拦截订阅。');
		if (length(filter(selected(),s=>s.url == address))) die('该地址已添加，可直接启用现有规则。');
		id=null;
		for (let n=1;n<=1000;n++) if (uci.get('adblock-fast','adzero_src_'+n) == null) { id='adzero_src_'+n;break; }
		if (!id || !uci.set('adblock-fast',id,'file_url')) die('无法添加规则。');
		let values={name,url:address,enabled:'1',action:'block',adzero_format:kind};
		for (let key in keys(values)) if (!uci.set('adblock-fast',id,key,values[key])) die('无法保存新增规则。');
	} else if (action == 'toggle' || action == 'remove') {
		address=shift(args);
		if (!match(id ?? '',/^[A-Za-z0-9_]+$/)) die('规则标识无效。');
		let entry=filter(selected(),s=>s['.name'] == id)[0];
		if (!entry || entry.url != address) die('规则已被其他操作修改，请重新读取列表。');
		if (action == 'remove') { removing=true;if (!uci.delete('adblock-fast',id)) die('无法删除规则。'); }
		else {
			let enabled=shift(args);if (index(['0','1'],enabled) < 0) die('规则开关无效。');
			removing=enabled=='0';
			if (enabled == '1') lib.url(address);
			if (!uci.set('adblock-fast',id,'enabled',enabled)) die('无法保存规则开关。');
		}
	} else if (action != 'refresh') die('未知规则变更。');
	require_rules(selected());
	// A removal cannot enlarge the same proven inputs. If live output cannot
	// be reused, the rebuild may fetch different remaining bytes: precheck
	// them before committing intent or stopping the working backend.
	let checked=!removing||uci.get('adblock-fast','config','enabled')=='1'&&!reusable_output(prior);
	if(checked)validate_sources(removing?[]:action=='refresh'?null:id,action=='refresh',false,uci.get('adblock-fast','config','enabled')=='1');
	let pending={schema:1,before,prior,after:model(),mode:fs.stat(config)?.mode & 0777,action,prechecked:checked};
	guard_revision(expected);
	atomic(journal,sprintf('%J',pending));
	if (!uci.commit('adblock-fast')) die('规则保存失败，恢复记录已保留。');
}
function batch_plan(path){
	if(fs.lstat(path)?.type!='file')die('待应用文件无效。');
	let p=lib.plan(fs.readfile(path,100001));
	clean_uci();
	if(length(uci.changes('adzero')?.adzero??[]))die('AdZero 有未提交的外部修改，请先保存或撤销。');
	if(p.revision!=revision()||(uci.get('adzero','main','routing_enabled')=='1')!=p.routing_before){progress.failure('config_conflict');die('配置已被其他操作修改，请重新读取并核对待应用选择。');}
	require_rules(p.items);
	if(p.dns&&!same(p.dns_before,dns_profile())){progress.failure('config_conflict');die('DNS 设置已被其他操作修改，请重新读取。');}
	p.dns_changed=!!p.dns&&!same(p.dns,p.dns_before);
	if((p.dns??dns_profile()).strict&&!p.routing_enabled)die('严格 DNS 模式需要自动分流；请同时修改后应用。');
	let active_changed=p.dns_changed&&!same(dns.effective(p.dns),dns.effective(p.dns_before));
	p.routing_changed=p.routing_before!=p.routing_enabled||active_changed&&p.routing_enabled;
	let existing=selected();
	for(let item in p.items)if(item.id){
		let old=filter(existing,s=>s['.name']==item.id)[0];
		if(!old)die('规则标识已变化，请重新读取。');
		if(item.format=='unknown'&&item.url!=old.url)die('修改地址时请选择文件格式。');
		if(item.url!=old.url)lib.url(item.url);
	}
	let before=list().items;
	let simple=items=>map(items,i=>({id:i.id,name:i.name,url:i.url,format:i.format,enabled:i.enabled}));
	p.rules_changed=!same(simple(before),p.items);
	return p;
}
function begin_batch(path){
	if(read(journal))die('上次规则变更尚未恢复，请先关闭并恢复。');
	let p=batch_plan(path),before=fs.readfile(config),prior=model(),existing=selected(),checks=[];
	for(let old in existing)if(!length(filter(p.items,i=>i.id==old['.name'])))if(!uci.delete('adblock-fast',old['.name']))die('无法删除规则。');
	for(let item in p.items){
		let old=item.id?filter(existing,s=>s['.name']==item.id)[0]:null,id=item.id;
		if(!id){for(let n=1;n<=1000;n++)if(uci.get('adblock-fast','adzero_src_'+n)==null){id='adzero_src_'+n;break;}
			if(!id||!uci.set('adblock-fast',id,'file_url'))die('无法添加规则。');}
		let values={name:item.name,url:item.url,enabled:item.enabled?'1':'0',action:'block'};
		let old_kind=old?.adzero_format??filter(lib.catalog,c=>c.url==old?.url)[0]?.format??old?.adzero_detected_format??'unknown';
		if(!old||item.format!=old_kind)values.adzero_format=item.format;
		for(let key in keys(values))if(!uci.set('adblock-fast',id,key,values[key]))die('无法保存待应用规则。');
		if(item.enabled&&(!old||old.enabled=='0'||old.url!=item.url||old_kind!=item.format))push(checks,id);
		if(old&&(old.url!=item.url||old_kind!=item.format))for(let key in ['adzero_domains','adzero_skipped','adzero_updated','adzero_checked','adzero_validation','adzero_detected_format'])uci.delete('adblock-fast',id,key);
	}
	require_rules(selected());
	let checked=length(checks)>0||p.rules_changed&&uci.get('adblock-fast','config','enabled')=='1'&&!reusable_output(prior);
	if(checked)validate_sources(checks,false,false,uci.get('adblock-fast','config','enabled')=='1');
	let pending={schema:1,before,prior,after:model(),mode:fs.stat(config)?.mode&0777,action:'batch',prechecked:checked};
	if(p.routing_before!=p.routing_enabled)pending.routing={before:uci.get('adzero','main','routing_enabled'),after:p.routing_enabled?'1':'0'};
	if(p.dns_changed)pending.dns={before:uci.get('adzero','main','dns_profile'),after:sprintf('%J',p.dns)};
	guard_revision(p.revision);
	atomic(journal,sprintf('%J',pending));
	if(!uci.commit('adblock-fast'))die('规则保存失败，恢复记录已保留。');
	if(pending.routing&&(!uci.set('adzero','main','routing_enabled',pending.routing.after)||!uci.commit('adzero')))die('分流选择保存失败，恢复记录已保留。');
	if(pending.dns&&(!uci.set('adzero','main','dns_profile',pending.dns.after)||!uci.commit('adzero')))die('DNS 设置保存失败，恢复记录已保留。');
}
function rollback() {
	let pending=read(journal);if (!pending) return;
	clean_uci();
	if (pending.schema != 1 || type(pending.before) != 'string' || (!same_model(model(),pending.after) && !same_model(model(),pending.prior))) die('配置出现并发变化，已保留规则恢复记录。');
	if(pending.dns){
		if(length(uci.changes('adzero')?.adzero??[]))die('DNS 有外部未保存修改，恢复记录已保留。');
		let p=pending.dns,current=uci.get('adzero','main','dns_profile');
		if(!same(current,p.before)&&current!=p.after)die('DNS 存在并发变化，恢复记录已保留。');
		let ok=p.before==null?(current==null||uci.delete('adzero','main','dns_profile')):uci.set('adzero','main','dns_profile',p.before);
		if(!ok||!uci.commit('adzero'))die('DNS 恢复失败。');
	}
	if(pending.routing){
		if(length(uci.changes('adzero')?.adzero??[]))die('分流配置有外部未保存修改，恢复记录已保留。');
		let current=uci.get('adzero','main','routing_enabled'),p=pending.routing;
		if(!same(current,p.before)&&current!=p.after)die('分流配置存在并发变化，恢复记录已保留。');
		let ok=p.before==null?(current==null||uci.delete('adzero','main','routing_enabled')):uci.set('adzero','main','routing_enabled',p.before);
		if(!ok||!uci.commit('adzero'))die('分流选择恢复失败。');
	}
	atomic(config,pending.before,pending.mode ?? 0600);
}
function effective_model(){
	let result=filtering_model(model());
	for(let s in result)if(s.type=='file_url'){
		if(s.values.enabled!='0'){
			let snapshot=snapshots.load(s.values.url,root);
			if(!snapshot||uci.get('adblock-fast','config','curl_additional_param'))return null;
			s.snapshot=snapshot.proof.body;
			s.semantic=index(['block','allow'],s.values.action??'block')>=0?snapshots.semantic(snapshot):null;
		}
	}
	return result;
}
function same_effective(current,prior){
	if(type(current)!='array'||type(prior)!='array'||length(current)!=length(prior))return false;
	for(let n=0;n<length(current);n++){
		let a=current[n],b=prior[n];
		if(!same({id:a.id,type:a.type,values:a.values},{id:b.id,type:b.type,values:b.values}))return false;
		if(a.type=='file_url' && (a.semantic&&b.semantic?a.semantic!=b.semantic:a.snapshot!=b.snapshot))return false;
	}
	return true;
}
function unchanged_selection(){
	let p=read(journal),state=read(dir+'/backend-cache.json'),path=cache_path();
	// A refresh can change bytes without changing options. This shortcut is
	// limited to an exact transaction changing cosmetic/disabled options only.
	if(!path||p?.schema!=1||p.prechecked!==false||p.action=='refresh'||state?.schema!=2||!match(state.sha256??'',/^[a-f0-9]{64}$/))return false;
	let current=filtering_model(model());
	return same(current,filtering_model(p.prior))&&same(current,filtering_model(p.after))&&
		same(current,filtering_model(state.config))&&checksum(path)==state.sha256;
}
function cache_save(preserve){
	let path=cache_path();if(!path)return;
	let digest=checksum(path);if(!digest)return;
	let current=model(),prior=null;try{prior=read(dir+'/backend-cache.json');}catch(e){}
	let proven=prior?.schema==2&&prior.sha256==digest&&same(filtering_model(current),filtering_model(prior.config));
	let effective=preserve?(proven?prior.effective:null):effective_model();
	atomic(dir+'/backend-cache.json',sprintf('%J',{schema:2,config:current,effective,sha256:digest}));
}
function cache_restamp(){
	if(!unchanged_selection())return false;
	let state=read(dir+'/backend-cache.json');state.config=model();
	// Raw snapshots may belong to a failed, unapplied refresh. Preserve which
	// inputs produced the live output; metadata edits cannot apply those bytes.
	atomic(dir+'/backend-cache.json',sprintf('%J',state));return true;
}
function sync_snapshots(){
	// Native scheduled updates do not run through our scoped curl wrapper.
	// If another writer replaced the processed output, its current source
	// bytes are unknown: never rebuild that output from our older snapshots.
	let state=null,path=cache_path();try{state=read(dir+'/backend-cache.json');}catch(e){}
	if(path&&match(state?.sha256??'',/^[a-f0-9]{64}$/)&&checksum(path)==state.sha256)return;
	uci.foreach('adblock-fast','file_url',s=>{if(s.enabled!='0'&&s.url)snapshots.invalidate(s.url,root);});
}
function cache_check(live){
	let state=read(dir+'/backend-cache.json'),path=cache_path();
	if(!path||state?.schema!=2||!match(state.sha256??'',/^[a-f0-9]{64}$/))return false;
	if(live&&live!='current'){let effective=effective_model();if(!effective||!same_effective(effective,state.effective))return false;}
	else if(!same_model(model(),state.config))return false;
	// Upstream moves the processed file to .cache on stop. Hash the exact
	// cache that start will restore; never trust config flags or timestamps.
	return checksum(path+(live?'':'.cache'))==state.sha256;
}
function stamp_verified_metadata(before){
	let state=read(dir+'/backend-cache.json'),path=cache_path();
	if(!path||state?.schema!=2||!same_model(before,state.config))return;
	if((checksum(path)??checksum(path+'.cache'))!=state.sha256)return;
	// A manual check changes counters only. Preserve the actual applied inputs,
	// including snapshots from before any failed/unapplied refresh.
	state.config=model();atomic(dir+'/backend-cache.json',sprintf('%J',state));
}
let action=shift(ARGV);if (action == '--') action=shift(ARGV);
try {
	if (action == 'list') print(sprintf('%J\n',list()));
	else if(action=='strict')exit(dns_profile().strict?0:1);
	else if(action=='preflight'){clean_uci();let expected=revision();require_rules(selected());validate_sources(null,false,false,true);guard_revision(expected);}
	else if(action=='plan-check'){let p=batch_plan(shift(ARGV));print((p.rules_changed?'1':'0')+' '+(p.routing_changed?'1':'0')+' '+(p.routing_enabled?'1':'0')+' '+(p.dns_changed?'1':'0')+'\n');}
	else if(action=='verify'){
		clean_uci();if(read(journal))die('请先完成待应用操作。');
		let before=model();
		if(!validate_sources(null,false,true))die('没有启用的规则可以校验。');
		if(!uci.commit('adblock-fast'))die('校验记录保存失败。');
		stamp_verified_metadata(before);
	}
	else if(action=='begin-batch')begin_batch(shift(ARGV));
	else if (action == 'begin') begin(shift(ARGV),ARGV);
	else if (action == 'rollback') rollback();
	else if (action == 'confirm') {
		let p=read(journal);clean_uci();
		if(p && (p.schema!=1 || !same_model(model(),p.after) || p.routing && uci.get('adzero','main','routing_enabled')!=p.routing.after || p.dns && uci.get('adzero','main','dns_profile')!=p.dns.after))
			die('规则在等待重载期间发生变化，恢复记录已保留。');
	}
	else if (action == 'finish') {
		let pending=read(journal);if (!pending) die('缺少规则完成记录。');
		atomic(dir+'/sources-selected','1\n');
		atomic(dir+'/sources-last.json',sprintf('%J',{ok:true,at:time(),action:pending.action}));
		if (!fs.unlink(journal)) die('规则已应用，但恢复记录清理失败。');
	} else if (action == 'discard') { if (fs.stat(journal) && !fs.unlink(journal)) die('无法清理规则恢复记录。'); }
	else if (action == 'pending') exit(read(journal) ? 0 : 1);
	else if(action=='cache-save')cache_save(shift(ARGV)=='preserve');
	else if(action=='cache-check')exit(cache_check()?0:1);
	else if(action=='cache-live')exit(cache_check(true)?0:1);
	else if(action=='cache-current')exit(cache_check('current')?0:1);
	else if(action=='cache-restamp')exit(cache_restamp()?0:1);
	else if(action=='cache-sync')sync_snapshots();
	else die('未知规则操作。');
} catch(e) { let reason=progress.source_reason(e.message);if(reason)progress.failure(reason);fs.stderr.write('AdZero: '+e.message+'\n');exit(action == 'pending' ? 2 : 1); }
