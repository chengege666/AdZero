'use strict';
// Public task metadata is a fixed vocabulary. Never forward private log text.
import * as fs from 'fs';
export const stages=['queued','waiting_lock','checking','downloading','validating','processing','adapting','restarting','confirming_proxy','restoring','verifying'];
export const messages={
	control_scope:'部分域名由父域规则拦截。请先在“访问控制”查询域名，核对实际命中范围后加入放行；待应用选择已保留。',
	config_conflict:'配置有其他未保存的编辑或已经变化。请重新读取并核对；规则数量统计不会阻止应用。',
	nailink_auth:'NaiLink 后端授权未通过。请通过原生服务重启刷新本机授权，再关闭并恢复 AdZero。',
	nailink_gateway:'NaiLink 重载请求未确认，本批规则与恢复记录已保留，后台会继续核对。请勿重复提交；旧版遗留记录需先重启 NaiLink 原生服务再关闭恢复。',
	lock_busy:'本次请求未取得操作锁，未执行任何配置修改。请核对当前保护状态，等待其他操作完成后按需重试。',
	source_download:'规则下载失败，已停止应用。请检查该订阅的 HTTPS 地址与网络。',
	source_format:'下载内容未通过规则格式校验，原有选择未被替换。',
	source_check:'订阅预检未完成，请核对本地快照、临时文件或订阅设置；具体错误保留在路由器任务日志。未确认的更改不会视为已应用。',
	source_limit:'规则超过安全上限（单文件 25 MB、单列表或合并后 50 万个域名）。请减少启用的列表；不会因为不同列表包含相同域名而报错。',
	source_duplicate:'存在完全相同的订阅地址或规则标识，请编辑或删除重复项。不同列表的域名重叠会自动去重。',
	country_data:'国内分类库下载或校验失败，未能开启自动分流。',
	adapter:'代理配置应用或恢复未完成，请检查 AdZero 的恢复记录。',
	dns_passwall_mode:'PassWall 当前 DNS 引擎不支持国外并发。请把国外组改为“单一 + 备用”，国内组仍可并发；不会替换原引擎。',
	dns_socks_required:'此 DNS 组合需要当前代理的本机无认证 SOCKS5 端口。请填写真实监听端口，或关闭国外并发／严格模式。',
	dns_socks_unavailable:'本机 SOCKS5 的 DNS 查询未通过。请核对端口、监听和认证设置；没有回落直连。',
	openclash_hook:'OpenClash 未保留 AdZero 的生成配置，请检查自定义覆写设置；原始错误保留在任务日志。',
	openclash_yaml:'OpenClash 配置读取或字符转换失败，尚未完成代理接入；原配置与恢复记录已保留。',
	openclash_dns:'OpenClash 的 DNS 未开启，无法接入广告过滤。请先在 OpenClash 中启用 DNS。',
	openclash_core:'OpenClash 的 Mihomo 内核不存在或未通过配置检查，请检查原生内核与配置。',
	openclash_confirmation:'未收到 OpenClash 配置生成回执，请检查原生启动日志；本次开启未完成。',
	backend:'过滤后端未能完成规则处理或 DNS 重载，请检查后端状态。',
	interrupted:'后台任务已停止且没有完成回执，请重新检测；有恢复提示时先关闭并恢复。'
};
function write(name,value){
	let dir=getenv('ADZERO_JOB_CONTEXT');if(!dir||fs.lstat(dir)?.type!='directory')return;
	let path=dir+'/'+name,tmp=path+'.new';
	if(fs.lstat(path)?.type=='link'||fs.lstat(tmp)?.type=='link')return;
	let file=fs.open(tmp,'w',0600);if(!file)return;
	let written=file.write(value),closed=file.close();if(written==length(value)&&closed)fs.rename(tmp,path);else fs.unlink(tmp);
}
export function stage(value){
	let dir=getenv('ADZERO_JOB_CONTEXT');if(index(stages,value)<0||!dir)return;
	if(trim(fs.readfile(dir+'/stage')??'')==value)return;
	let now=time();write('stage_started',''+now);write('stage',value+'\n');
	if(fs.lstat(dir+'/timeline')?.type=='link')return;
	let log=fs.open(dir+'/timeline','a',0600);if(log){log.write(''+now+' '+value+'\n');log.close();}
};
export function failure(value){
	let dir=getenv('ADZERO_JOB_CONTEXT');if(!dir||messages[trim(fs.readfile(dir+'/reason')??'')])return;
	if(messages[value])write('reason',value);
};
// Numeric positions only: never publish subscription URLs, names or log text.
export function source(index,total){
	if(index==null){let dir=getenv('ADZERO_JOB_CONTEXT');if(dir&&fs.lstat(dir)?.type=='directory'&&fs.lstat(dir+'/source')?.type=='file')fs.unlink(dir+'/source');return;}
	if(type(index)=='int'&&type(total)=='int'&&index>=1&&index<=total&&total<=30)write('source',sprintf('%J',{index,total}));
};
export function source_reason(message){
	if(type(message)!='string')return null;
	if(index(message,'50 万')>=0||index(message,'25 MB')>=0)return 'source_limit';
	if(message=='待应用规则中存在重复项。'||message=='该订阅地址已存在。')return 'source_duplicate';
	return null;
};
