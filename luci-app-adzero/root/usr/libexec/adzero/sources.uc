'use strict';
// Configuration transactions run only under ctl's existing operation lock.
import * as fs from 'fs';
import { cursor } from 'uci';
import * as lib from './source-lib.uc';
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
function model() {
	let result=[];
	uci.foreach('adblock-fast',null,s => {
		let values={};
		for (let key in sort(keys(s))) if (substr(key,0,1) != '.' && !(key == 'size' && s['.type'] == 'file_url' && match(''+s[key],/^[0-9]+$/))) values[key]=s[key];
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
function clean_uci() {
	let changes=uci.changes('adblock-fast');
	if (changes && length(changes)) die('后端有尚未提交的外部修改，请先保存或撤销后再管理规则。');
}
function list() {
	let items=[];
	for (let s in selected()) {
		let builtin=filter(lib.catalog,c=>c.url == s.url)[0], valid=true;
		try { lib.url(s.url); } catch(e) { valid=false; }
		push(items,{id:s['.name'],name:s.name ?? builtin?.name ?? '已有规则',url:s.url,enabled:s.enabled != '0',
			format:s.adzero_format ?? builtin?.format ?? 'unknown',catalog_id:builtin?.id ?? null,https:valid,
			domains: s.adzero_domains ? int(s.adzero_domains) : null,updated:s.adzero_updated ? int(s.adzero_updated) : null});
	}
	return {catalog:lib.catalog,items,pending:!!read(journal),last:read(dir+'/sources-last.json')};
}
function download(address,kind) {
	lib.url(address);lib.format(kind);
	let path=root+'/tmp/adzero-source-check';
	if (root && !fs.stat(root+'/tmp')) fs.mkdir(root+'/tmp',0700);
	if (fs.lstat(path)) die('规则校验临时文件已存在，请检查未完成操作。');
	let file=fs.open(path,'wx',0600);if (!file || !file.close()) die('无法创建临时规则文件。');
	try {
		let fixture=getenv('ADZERO_SOURCE_FETCH_FIXTURE');
		let argv = root && fixture ? [fixture,address,path] : ['curl','--fail','--location','--silent','--show-error','--proto','=https','--proto-redir','=https','--connect-timeout','10','--max-time','60','--max-filesize','25000000','--output',path,address];
		// Quiet output: a custom subscription URL may contain a private token.
		let quote=s=>"'"+replace(s,/'/g,"'\\''")+"'";
		if (system(join(' ',map(argv,quote))+' >/dev/null 2>&1',65000) != 0) die('规则下载失败，请检查 HTTPS 地址和网络。');
		let raw=fs.readfile(path,25000001), result=lib.parse(raw,kind);
		fs.unlink(path);return result;
	} catch(e) { fs.unlink(path);die(e); }
}
function validate_sources() {
	let union={}, count=0;
	for (let s in selected()) if (s.enabled != '0') {
		let builtin=filter(lib.catalog,c=>c.url == s.url)[0],kind=s.adzero_format ?? builtin?.format;
		// Existing backend-only formats retain their current behavior; do not
		// silently reinterpret a pre-existing configuration as a new import.
		if (!kind) continue;
		let names=download(s.url,kind);
		for (let name in names) union[name]=true;
		if (length(union) > 500000) die('所选规则合计超过 50 万个域名，请减少列表。');
		if (!uci.set('adblock-fast',s['.name'],'adzero_domains',''+length(names)) || !uci.set('adblock-fast',s['.name'],'adzero_updated',''+time())) die('无法保存规则校验结果。');
		count++;
	}
	return count;
}
function begin(action,args) {
	if (read(journal)) die('上次规则变更尚未恢复，请先关闭并恢复。');
	clean_uci();
	let before=fs.readfile(config), prior=model();
	if (before == null) die('无法读取现有规则配置。');
	let id=shift(args), address;
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
		if (action == 'remove') { if (!uci.delete('adblock-fast',id)) die('无法删除规则。'); }
		else {
			let enabled=shift(args);if (index(['0','1'],enabled) < 0) die('规则开关无效。');
			if (enabled == '1') lib.url(address);
			if (!uci.set('adblock-fast',id,'enabled',enabled)) die('无法保存规则开关。');
		}
	} else if (action != 'refresh') die('未知规则变更。');
	if (uci.get('adblock-fast','config','enabled') == '1' && !length(filter(selected(),s=>s.enabled != '0')) && !length(uci.get('adblock-fast','config','blocked_domain') ?? [])) die('至少保留一项启用的规则；需要暂停全部过滤时请使用临时暂停或关闭保护。');
	validate_sources(); // No committed config or running service changes yet.
	let pending={schema:1,before,prior,after:model(),mode:fs.stat(config)?.mode & 0777,action};
	atomic(journal,sprintf('%J',pending));
	if (!uci.commit('adblock-fast')) die('规则保存失败，恢复记录已保留。');
}
function rollback() {
	let pending=read(journal);if (!pending) return;
	clean_uci();
	if (pending.schema != 1 || type(pending.before) != 'string' || (!same(model(),pending.after) && !same(model(),pending.prior))) die('配置出现并发变化，已保留规则恢复记录。');
	atomic(config,pending.before,pending.mode ?? 0600);
}
let action=shift(ARGV);if (action == '--') action=shift(ARGV);
try {
	if (action == 'list') print(sprintf('%J\n',list()));
	else if (action == 'begin') begin(shift(ARGV),ARGV);
	else if (action == 'rollback') rollback();
	else if (action == 'finish') {
		let pending=read(journal);if (!pending) die('缺少规则完成记录。');
		atomic(dir+'/sources-selected','1\n');
		atomic(dir+'/sources-last.json',sprintf('%J',{ok:true,at:time(),action:pending.action}));
		if (!fs.unlink(journal)) die('规则已应用，但恢复记录清理失败。');
	} else if (action == 'discard') { if (fs.stat(journal) && !fs.unlink(journal)) die('无法清理规则恢复记录。'); }
	else if (action == 'pending') exit(read(journal) ? 0 : 1);
	else die('未知规则操作。');
} catch(e) { fs.stderr.write('AdZero: '+e.message+'\n');exit(action == 'pending' ? 2 : 1); }
