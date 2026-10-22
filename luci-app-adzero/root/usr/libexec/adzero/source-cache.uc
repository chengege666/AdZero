'use strict';
// Disposable HTTPS subscription snapshots. A bad/missing snapshot is a miss,
// never a reason to skip the downloader or the final backend verification.
import * as fs from 'fs';
const limit=25000000;
let memory=match(fs.readfile('/proc/meminfo')??'',/MemTotal:\s+([0-9]+)/);
const budget=memory?min(96000000,int(memory[1])*128):16000000;
function quote(s){return "'"+replace(s,/'/g,"'\\''")+"'";}
function hash(path){
	let s=fs.lstat(path);if(s?.type!='file'||s.size>32000000||!s.size)return null;
	let p=fs.popen('sha256sum '+quote(path)+' 2>/dev/null','r');if(!p)return null;
	let out=p.read('all'),code=p.close(),digest=split(out??'',' ')[0];
	return code==0&&match(digest??'',/^[a-f0-9]{64}$/)?digest:null;
}
function directory(root){
	let parent=(root??'')+'/tmp',dir=parent+'/adzero-source-cache';
	if(!fs.stat(parent))fs.mkdir(parent,0700);
	if(!fs.lstat(dir))fs.mkdir(dir,0700);
	let s=fs.lstat(dir),uid=fs.stat('/proc/self')?.uid;
	return s?.type=='directory'&&!(s.mode&0077)&&s.uid==uid?dir:null;
}
function key(dir,address){
	// Hash URL via a private file, never place a subscription token in argv.
	let id=trim(fs.readfile('/proc/sys/kernel/random/uuid')??'');
	if(!match(id,/^[a-f0-9-]{36}$/))return null;
	let path=dir+'/'+id+'.key',f=fs.open(path,'wx',0600);if(!f)return null;
	let ok=f.write(address)==length(address);ok=f.close()&&ok;
	let value=ok?hash(path):null;fs.unlink(path);return value;
}
function private_file(path,max){let s=fs.lstat(path);return s?.type=='file'&&s.size>0&&s.size<=max&&!(s.mode&0077)&&s.uid==fs.stat('/proc/self')?.uid;}
export function load(address,root){
	try{
		let dir=directory(root);if(!dir)return null;
		let id=key(dir,address);if(!id||!private_file(dir+'/'+id+'.proof',1024))return null;
		let proof=json(fs.readfile(dir+'/'+id+'.proof')),path=dir+'/'+id+'.body';
		if(proof?.schema!=1||!private_file(path,limit)||hash(path)!=proof.body)return null;
		return {dir,id,path,proof};
	}catch(e){return null;}
};
export function parsed(snapshot,kind){
	try{
		let p=snapshot?.proof,path=snapshot.dir+'/'+snapshot.id+'.parsed';
		if(p.kind!=kind||!p.parsed||!private_file(path,32000000)||hash(path)!=p.parsed)return null;
		let value=json(fs.readfile(path));
		if(type(value?.names)!='array'||!length(value.names)||length(value.names)>500000)return null;
		return value;
	}catch(e){return null;}
};
export function invalidate(address,root){
	try{let dir=directory(root),id=dir?key(dir,address):null;if(id)fs.unlink(dir+'/'+id+'.proof');}catch(e){}
};
export function save(address,raw,root,kind,result){
	let temps=[];
	try{
		if(type(raw)!='string'||!length(raw)||length(raw)>limit)return;
		let dir=directory(root);if(!dir)return;
		let id=key(dir,address);if(!id)return;
		let used=0;for(let n in fs.lsdir(dir)??[])used+=fs.lstat(dir+'/'+n)?.size??0;
		// Optional bounded RAM cache. No eviction of a file another downloader
		// may be reading. Full cache simply uses the original strict path.
		let parsed=result?sprintf('%J',result):null;
		if(used+length(raw)+(parsed?length(parsed):0)>budget)return;
		let nonce=trim(fs.readfile('/proc/sys/kernel/random/uuid')??'');if(!match(nonce,/^[a-f0-9-]{36}$/))return;
		function put(suffix,text){
			let path=dir+'/'+nonce+suffix,f=fs.open(path,'wx',0600);if(!f)die('cache_open');push(temps,path);
			let written=f.write(text),closed=f.close();if(written!=length(text)||!closed)die('cache_write');return path;
		}
		let body=put('.body',raw),proof={schema:1,body:hash(body),kind:kind??null};
		if(!proof.body)die('cache_digest');
		if(parsed){let data=put('.parsed',parsed);proof.parsed=hash(data);if(!proof.parsed||!fs.rename(data,dir+'/'+id+'.parsed'))die('cache_parsed');}
		let meta=put('.proof',sprintf('%J',proof));
		if(!fs.rename(body,dir+'/'+id+'.body'))die('cache_commit');
		fs.rename(meta,dir+'/'+id+'.proof');
	}catch(e){} // Never make cache storage a filtering prerequisite.
	for(let path in temps)fs.unlink(path);
};
