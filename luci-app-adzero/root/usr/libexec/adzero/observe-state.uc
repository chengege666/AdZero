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
export function recent_request(request,generation,now){return request?.schema==1&&request.enabled===true&&match(request.nonce??'',/^[a-f0-9]{32}$/)&&request.generation==generation&&request.deadline>now&&request.deadline<=now+301;};
export function snapshot(){
	let value=read(directory+'/status.json',16384),now=monotime();
	if(!value||value.schema!=1||value.updated>now||now-value.updated>12)return {available:false,reason:value?'stopped':'not_started',verification:{state:'idle'}};
	if(!match(value.pid??'',/^[1-9][0-9]*$/)||index(split(fs.readfile('/proc/'+value.pid+'/cmdline')??'','\x00'),root+'/usr/libexec/adzero/observe.uc')<0)return {available:false,reason:'stopped',verification:{state:'idle'}};
	let request=read(directory+'/recent.json',2048);
	if(!recent_request(request,value.generation,now)||value.recent_token!=request.nonce)value.recent={enabled:false,remaining:0,items:[]};
	delete value.recent_token;
	return value;
};

// The recovery journal places provider data before its top-level stage. That
// field can be megabytes into the file; a prefix regex is not a JSON reader.
// Keep only small metadata, and decode private data once per atomic replacement.
export function adapter_context(reader){
	reader??=fs.readfile;
	let cached_key=null,cached=null;
	function identity(s){return join('|',[s?.inode??0,s?.mtime??0,s?.ctime??0,s?.size??0,s?.mode??0,s?.uid??-1]);}
	return function(){
		let path=root+'/etc/adzero/adapter.json',s=fs.lstat(path);
		if(!s){cached_key=null;cached=null;return {present:false};}
		let key=identity(s);
		if(key==cached_key)return cached;
		let value={present:true,reason:'adapter_state_invalid'};
		if(s.type=='file'&&s.uid==fs.stat('/proc/self')?.uid&&!(s.mode&0077)&&s.size>0&&s.size<=67108864){
			try{
				let raw=reader(path,67108865);
				if(raw!=null&&length(raw)==s.size){
					let data=json(raw);
					if(data?.schema==1&&type(data.plugin)=='string'&&length(data.plugin)&&type(data.files)=='array'&&type(data.stage)=='string')
						value={present:true,plugin:data.plugin,stage:data.stage,domains:type(data.count)=='int'&&data.count>=0?data.count:null,routing_mode:data.split?.mode??'inactive',runtime_supported:data.runtime_supported===true,runtime_samples:data.runtime_samples??[],runtime_retry_exhausted:(data.runtime_retries??0)>=3,reason:data.stage=='configured_unverified'?null:'adapter_pending'};
				}
			}catch(e){}
		}
		if(identity(fs.lstat(path))!=key)return {present:true,reason:'adapter_changing'};
		cached_key=key;cached=value;return value;
	};
};
