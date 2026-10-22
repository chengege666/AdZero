'use strict';
import * as fs from 'fs';
export const root=getenv('ADZERO_OBSERVER_ROOT')??'';
export const directory=root+'/tmp/adzero-observe';
export function monotime(){return +(split(fs.readfile(root+'/proc/uptime')??fs.readfile('/proc/uptime')??'0',' ')[0]);};
export function read(path,limit){let s=fs.lstat(path),parent=fs.lstat(directory),uid=fs.stat('/proc/self')?.uid;if(parent?.type!='directory'||(parent.mode&0077)||parent.uid!=uid||s?.type!='file'||s.size>limit||(s.mode&0077)||s.uid!=uid)return null;try{return json(fs.readfile(path,limit+1));}catch(e){return null;}};
export function atomic(path,data){
	let stat=fs.lstat(directory),uid=fs.stat('/proc/self')?.uid;
	if(!stat){if(!fs.mkdir(directory,0700))die('state_directory');stat=fs.stat(directory);}
	if(stat.type!='directory'||(stat.mode&0077)||stat.uid!=uid)die('state_directory');
	let nonce=trim(fs.readfile('/proc/sys/kernel/random/uuid')??'');if(!match(nonce,/^[a-f0-9-]{36}$/))die('state_nonce');
	let temp=directory+'/'+nonce,f=fs.open(temp,'wx',0600),raw=sprintf('%J',data);if(!f)die('state_open');
	let size=f.write(raw),closed=f.close();if(size!=length(raw)||!closed||!fs.rename(temp,path)){fs.unlink(temp);die('state_write');}
};
export function snapshot(){
	let value=read(directory+'/status.json',16384),now=monotime();
	if(!value||value.schema!=1||value.updated>now||now-value.updated>12)return {available:false,reason:value?'stopped':'not_started',verification:{state:'idle'}};
	if(!match(value.pid??'',/^[1-9][0-9]*$/)||index(split(fs.readfile('/proc/'+value.pid+'/cmdline')??'','\x00'),root+'/usr/libexec/adzero/observe.uc')<0)return {available:false,reason:'stopped',verification:{state:'idle'}};
	return value;
};
