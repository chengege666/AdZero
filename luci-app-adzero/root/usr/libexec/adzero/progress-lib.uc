'use strict';
// Public task metadata is a fixed vocabulary. Never forward private log text.
import * as fs from 'fs';
export const stages=['queued','waiting_lock','checking','downloading','validating','processing','adapting','restarting','confirming_proxy','restoring','verifying'];
export const messages={
	config_conflict:'配置有其他未保存的编辑或已经变化。请重新读取并核对；规则数量统计不会阻止应用。',
	nailink_auth:'NaiLink 后端授权未通过。请通过原生服务重启刷新本机授权，再关闭并恢复 AdZero。',
	nailink_gateway:'NaiLink 重载请求未确认，本批规则与恢复记录已保留，后台会继续核对。请勿重复提交；旧版遗留记录需先重启 NaiLink 原生服务再关闭恢复。',
	lock_busy:'另一项操作仍在进行，等待操作锁超时。请核对当前任务后重试。',
	source_download:'规则下载失败，已停止应用。请检查该订阅的 HTTPS 地址与网络。',
	source_format:'下载内容未通过规则格式校验，原有选择未被替换。',
	country_data:'国内分类库下载或校验失败，未能开启自动分流。',
	adapter:'代理配置应用或恢复未完成，请检查 AdZero 的恢复记录。',
	openclash_hook:'OpenClash 未保留 AdZero 的生成配置，请检查自定义覆写设置；原始错误保留在任务日志。',
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
