'use strict';
// Public task metadata is a fixed vocabulary. Never forward private log text.
import * as fs from 'fs';
export const stages=['queued','waiting_lock','checking','downloading','validating','processing','adapting','restarting','restoring','verifying'];
export const messages={
	lock_busy:'另一项操作仍在进行，等待操作锁超时。请核对当前任务后重试。',
	source_download:'规则下载失败，已停止应用。请检查该订阅的 HTTPS 地址与网络。',
	source_format:'下载内容未通过规则格式校验，原有选择未被替换。',
	country_data:'国内分类库下载或校验失败，未能开启自动分流。',
	adapter:'代理配置应用或恢复未完成，请检查 AdZero 的恢复记录。',
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
export function stage(value){if(index(stages,value)>=0)write('stage',value);};
export function failure(value){
	let dir=getenv('ADZERO_JOB_CONTEXT');if(!dir||messages[trim(fs.readfile(dir+'/reason')??'')])return;
	if(messages[value])write('reason',value);
};
