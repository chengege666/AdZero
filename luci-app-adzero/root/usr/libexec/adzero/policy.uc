'use strict';
// All mutations run under ctl's one operation lock. Files are recovery journals.
import * as fs from 'fs';
import { cursor } from 'uci';
import * as lib from './policy-lib.uc';
import * as rulecache from './rules-cache.uc';

const root = getenv('ADZERO_POLICY_ROOT') ?? '';
const dir = getenv('ADZERO_STATE_DIR') ?? root + '/etc/adzero';
const uci = cursor(root + '/etc/config');
const mirror_path = dir + '/allow-state.json', pending_path = dir + '/allow-pending.json', pause_path = dir + '/pause.json';
const routing_path=dir+'/routing-pending.json';
function same(a,b) { return sprintf('%J', a) == sprintf('%J', b); }
function read(path) { let data = fs.readfile(path); return data == null ? null : json(data); }
function atomic(path, data) {
	if (fs.lstat(path)?.type == 'link') die('状态文件为链接，已停止操作。');
	if (!fs.stat(dir) && !fs.mkdir(dir,0700)) die('无法创建恢复目录。');
	let tmp = path + '.new', file = fs.open(tmp,'wx',0600);
	if (!file) die('无法创建恢复记录；请检查未完成的操作。');
	data = sprintf('%J\n',data);
	let count = file.write(data), closed = file.close();
	if (count != length(data) || !closed || !fs.rename(tmp,path)) { fs.unlink(tmp); die('无法提交恢复记录。'); }
}
function set(config, option, value) {
	let ok = value == null ? (uci.get(config,'main',option) == null || uci.delete(config,'main',option)) : uci.set(config,'main',option,value);
	if (!ok || !uci.commit(config)) die('无法保存个人放行名单。');
}
function backend(value) {
	let ok = value == null ? (uci.get('adblock-fast','config','allowed_domain') == null || uci.delete('adblock-fast','config','allowed_domain')) : uci.set('adblock-fast','config','allowed_domain',value);
	if (!ok || !uci.commit('adblock-fast')) die('无法保存过滤后端的放行配置。');
}
function own() { return lib.list(uci.get('adzero','main','allowed_domain')); }
function merged(original, allowed) {
	let result = original == null ? [] : type(original) == 'array' ? [...original] : [original];
	for (let name in allowed) if (index(result,name) < 0) push(result,name);
	return result;
}
function validate() {
	let flag=uci.get('adzero','main','routing_enabled'),adapter=read(dir+'/adapter.json');
	if(flag!=null && flag!='0' && flag!='1')die('自动分流设置无效。');
	if(uci.get('adzero','main','enabled')=='1' && uci.get('adblock-fast','config','enabled')=='1' && ((flag=='1') != !!adapter?.split))die('自动分流配置与实际接入不一致，请关闭并恢复。');
	let state = read(mirror_path), current = uci.get('adblock-fast','config','allowed_domain');
	if (state && (!same(current,state.after) || !same(state.after,merged(state.before,own())))) die('后端放行配置已被外部修改。');
	if (!state && length(own()) && uci.get('adblock-fast','config','enabled') == '1') die('个人放行名单尚未同步。');
}
function apply() {
	let allowed = own(), state = read(mirror_path), current = uci.get('adblock-fast','config','allowed_domain');
	if (state && (!same(current,state.after) && !same(current,state.before))) die('后端放行配置被其他操作修改，请先检查恢复记录。');
	if (!state && !length(allowed)) return;
	state ??= {schema:1,before:current};
	state.after = length(allowed) ? merged(state.before,allowed) : state.before;
	atomic(mirror_path,state); // Save intended change before changing UCI.
	backend(state.after);
	if (!length(allowed)) fs.unlink(mirror_path);
}
function rollback() {
	let pending = read(pending_path);
	if (!pending) return;
	let current = uci.get('adzero','main','allowed_domain'), state = read(mirror_path), actual = uci.get('adblock-fast','config','allowed_domain');
	if (!same(current,pending.before) && !same(current,pending.after)) die('个人放行名单已被其他操作修改。');
	if (!same(actual,pending.backend_before) && !same(actual,state?.after)) die('并发修改阻止恢复放行配置。');
	set('adzero','allowed_domain',pending.before);
	backend(pending.backend_before);
	if (pending.mirror_before == null) fs.unlink(mirror_path); else atomic(mirror_path,pending.mirror_before);
}
function restore_allow() {
	rollback();
	let state = read(mirror_path);
	if (state) {
		let actual = uci.get('adblock-fast','config','allowed_domain');
		if (!same(actual,state.after) && !same(actual,state.before)) die('后端放行配置已变化，恢复记录已保留。');
		backend(state.before);
		fs.unlink(mirror_path);
	}
	fs.unlink(pending_path);
}
function routing_clean(){if(length(uci.changes('adzero')??{}))die('AdZero 有未提交的外部修改，请先保存或撤销。');}
function routing_begin(value){
	if(index(['0','1'],value)<0)die('自动分流开关无效。');
	routing_clean();if(read(routing_path))die('上次分流切换尚未恢复。');
	atomic(routing_path,{schema:1,before:uci.get('adzero','main','routing_enabled'),after:value,stage:'prepared'});
}
function routing_save(){
	routing_clean();let p=read(routing_path);if(!p||p.schema!=1||p.stage!='prepared')die('分流切换记录无效。');
	let current=uci.get('adzero','main','routing_enabled');if(!same(current,p.before)&&current!=p.after)die('分流开关被其他操作修改。');
	set('adzero','routing_enabled',p.after);p.stage='applied';atomic(routing_path,p);
}
function routing_rollback(){
	routing_clean();let p=read(routing_path);if(!p)return;
	let current=uci.get('adzero','main','routing_enabled');if(!same(current,p.before)&&current!=p.after)die('分流恢复遇到并发修改。');
	set('adzero','routing_enabled',p.before);p.stage='rolled_back';atomic(routing_path,p);
}
function routing_finish(){
	let p=read(routing_path);if(!p)return;
	let expected=p.stage=='applied'?p.after:p.stage=='rolled_back'?p.before:'invalid';
	if(!same(uci.get('adzero','main','routing_enabled'),expected))die('分流切换结果未确认。');
	if(!fs.unlink(routing_path))die('分流已应用，但完成记录未能清理。');
}
function restore(){if(read(routing_path)){routing_rollback();fs.unlink(routing_path);}restore_allow();}
function query(value) {
	let name = lib.hostname(value), mode = uci.get('adblock-fast','config','dns');
	let output = mode == 'unbound.adb_list' ? '/var/lib/unbound/adb_list.adblock-fast' : '/var/run/adblock-fast/' + mode;
	if (index(['dnsmasq.servers','dnsmasq.addnhosts','smartdns.domainset','unbound.adb_list'],mode) < 0) die('当前过滤模式无法查询。');
	let raw = fs.readfile(root + output,25000001);
	if (!length(raw)) return {domain:name,available:false,match:'unavailable',scope:null};
	let rules = rulecache.load(root + output,mode,root), adapter = read(dir + '/adapter.json');
	let result = lib.lookup(name,rules,own(),mode != 'dnsmasq.addnhosts' || !!adapter);
	return {...result,available:true,scope_includes_subdomains:true,source:'processed_rules'};
}
function pause_info() {
	let state = read(pause_path);
	if (!state) return null;
	if (state.schema != 1 || index(['pausing','paused','resuming','recovery_required'],state.stage) < 0 || index([300,900,1800],state.duration) < 0 || type(state.deadline) != 'int') die('暂停恢复记录无效。');
	let boot = trim(fs.readfile(root + '/proc/sys/kernel/random/boot_id') ?? ''), uptime = int(fs.readfile(root + '/proc/uptime') ?? '0');
	let remaining = boot != state.boot || state.deadline < uptime ? 0 : state.deadline - uptime;
	let retry = state.retry_boot == boot && state.retry_after > uptime ? state.retry_after - uptime : 0;
	return {...state,remaining,expired:remaining == 0,retry_remaining:retry};
}
let action = shift(ARGV);
if (action == '--') action = shift(ARGV);
try {
	if (action == 'status') print(sprintf('%J\n',{allowed:own(),pending:!!read(pending_path),pause:pause_info(),routing_enabled:uci.get('adzero','main','routing_enabled')=='1',routing_pending:!!read(routing_path)}));
	else if (action == 'lookup') print(sprintf('%J\n',query(shift(ARGV))));
	else if (action == 'apply') { if (read(pending_path)) die('放行事务尚未恢复。'); apply(); }
	else if (action == 'validate') validate();
	else if (action == 'restore') restore();
	else if (action == 'begin-allow' || action == 'begin-revoke') {
		if (read(pending_path)) die('上一项放行操作尚未恢复，请先关闭并恢复。');
		let domain = lib.hostname(shift(ARGV)), scope = lib.hostname(shift(ARGV)), before = uci.get('adzero','main','allowed_domain'), after = own();
		if (action == 'begin-allow') {
			let result = query(domain);
			if (!result.available || index(['exact','parent'],result.match) < 0 || result.scope != scope) die('命中规则已变化，请重新查询并确认放行范围。');
			let mode = uci.get('adblock-fast','config','dns'), path = mode == 'unbound.adb_list' ? '/var/lib/unbound/adb_list.adblock-fast' : '/var/run/adblock-fast/' + mode;
			if (!length(filter(rulecache.load(root + path,mode,root),d => !lib.covers(scope,d)))) die('该范围覆盖全部过滤规则，请使用临时暂停。');
			if (length(after) >= 100) die('个人放行名单最多 100 项。');
			push(after,scope); after = lib.list(after);
		} else {
			if (domain != scope || index(after,scope) < 0) die('该域名不在个人放行名单中。');
			after = filter(after,d => d != scope);
		}
		atomic(pending_path,{schema:1,before,after,backend_before:uci.get('adblock-fast','config','allowed_domain'),mirror_before:read(mirror_path)});
		set('adzero','allowed_domain',length(after) ? after : null); apply();
	}
	else if (action == 'rollback') rollback();
	else if (action == 'finish') { if (fs.stat(pending_path) && !fs.unlink(pending_path)) die('无法清除已完成的放行记录。'); }
	else if (action == 'pause-begin') {
		let duration = int(shift(ARGV));
		if (index([300,900,1800],duration) < 0 || fs.stat(pause_path)) die('暂停时长无效或已有未完成暂停。');
		let boot = trim(fs.readfile(root + '/proc/sys/kernel/random/boot_id') ?? ''), uptime = int(fs.readfile(root + '/proc/uptime') ?? '0');
		if (!length(boot) || uptime <= 0) die('无法读取启动时钟，未开始暂停。');
		atomic(pause_path,{schema:1,stage:'pausing',boot,duration,deadline:uptime+duration,error:null});
	}
	else if (action == 'pause-stage') {
		let state = read(pause_path), stage = shift(ARGV), error = shift(ARGV);
		if (!state || index(['paused','resuming','recovery_required'],stage) < 0 || (error != null && error != 'resume_failed')) die('无效的暂停状态。');
		state.stage = stage; state.error = error ?? null;
		if (error) { state.retry_boot = trim(fs.readfile(root + '/proc/sys/kernel/random/boot_id') ?? ''); state.retry_after = int(fs.readfile(root + '/proc/uptime') ?? '0') + 30; }
		atomic(pause_path,state);
	}
	else if (action == 'pause-clear') { if (fs.stat(pause_path) && !fs.unlink(pause_path)) die('无法清理暂停恢复记录。'); }
	else if (action == 'is-paused') { let p = pause_info(); exit(p?.stage == 'paused' ? 0 : 1); }
	else if (action == 'pause-due') { let p = pause_info(); exit(p?.stage == 'paused' && p.expired && !p.retry_remaining ? 0 : 1); }
	else if (action == 'has-allowed') exit(length(own()) ? 0 : 1);
	else if (action == 'pending') exit(read(pending_path)||read(routing_path) ? 0 : 1);
	else if (action == 'routing-begin') routing_begin(shift(ARGV));
	else if (action == 'routing-save') routing_save();
	else if (action == 'routing-rollback') routing_rollback();
	else if (action == 'routing-finish') routing_finish();
	else die('未知的策略操作。');
} catch(e) { fs.stderr.write('AdZero: ' + e.message + '\n'); exit(action == 'pending' ? 2 : 1); }
