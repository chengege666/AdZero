'use strict';
// Disposable, content-addressed proof of the strict processed-rules import.
// A miss or any cache error always falls back to the original strict parser.
import * as fs from 'fs';
import { domains } from './adapter-lib.uc';
const digest_re=/^[a-f0-9]{64}$/, uuid_re=/^[a-f0-9-]{36}$/;
const modes=['dnsmasq.servers','dnsmasq.addnhosts','smartdns.domainset','unbound.adb_list'];
function data_path(dir,source,mode){return dir+'/'+source+'-'+index(modes,mode)+'.json';}
function quote(s){return "'"+replace(s,/'/g,"'\\''")+"'";}
function digest(path,limit){
	let s=fs.lstat(path);if(s?.type!='file'||!s.size||s.size>limit)return null;
	let p=fs.popen('sha256sum '+quote(path)+' 2>/dev/null','r');if(!p)return null;
	let out=p.read('all'),code=p.close(),hash=split(out??'',' ')[0];
	return code==0&&match(hash,digest_re)?hash:null;
}
function directory(root){
	let parent=root+'/tmp',path=parent+'/adzero-rules-cache';
	if(!fs.stat(parent))fs.mkdir(parent,0700);
	if(!fs.lstat(path))fs.mkdir(path,0700);
	let s=fs.lstat(path),uid=fs.stat('/proc/self')?.uid;
	return s?.type=='directory'&&!(s.mode&0077)&&uid!=null&&s.uid==uid?path:null;
}
function read_cache(dir,source,mode){
	try{
		if(!dir||fs.lstat(dir+'/proof.json')?.type!='file'||fs.stat(dir+'/proof.json').size>2048)return null;
		let proof=json(fs.readfile(dir+'/proof.json'));
		if(proof?.schema!=1||proof.source!=source||proof.mode!=mode||!match(proof.sha256??'',digest_re))return null;
		let path=data_path(dir,source,mode);
		if(digest(path,32000000)!=proof.sha256)return null;
		let list=json(fs.readfile(path));
		if(type(list)!='array'||length(list)!=proof.count||!length(list)||length(list)>500000)return null;
		return list;
	}catch(e){return null;}
}
function save_cache(dir,source,mode,list){
	if(!dir)return;
	let nonce=trim(fs.readfile('/proc/sys/kernel/random/uuid')??'');if(!match(nonce,uuid_re))return;
	let data_path=dir+'/'+nonce+'.data',proof_path=dir+'/'+nonce+'.proof';
	let prior=null;try{prior=json(fs.readfile(dir+'/proof.json'));}catch(e){}
	try{
		let text=sprintf('%J',list),f=fs.open(data_path,'wx',0600);if(!f)return;
		let count=f.write(text),closed=f.close();if(count!=length(text)||!closed)die('cache_write');
		// Hash the private temporary file, never a shared path another writer
		// could replace before the proof is committed.
		let hash=digest(data_path,32000000);if(!hash)die('cache_digest');
		text=sprintf('%J',{schema:1,source,mode,count:length(list),sha256:hash});
		f=fs.open(proof_path,'wx',0600);if(!f)die('cache_open');
		count=f.write(text);closed=f.close();if(count!=length(text)||!closed)die('cache_write');
		let target=dir+'/'+source+'-'+index(modes,mode)+'.json';
		// Different source/mode writers never replace a reader's data file.
		if(!fs.rename(data_path,target)||!fs.rename(proof_path,dir+'/proof.json'))die('cache_commit');
		if(match(prior?.source??'',digest_re)&&index(modes,prior.mode)>=0){
			let old=dir+'/'+prior.source+'-'+index(modes,prior.mode)+'.json';if(old!=target)fs.unlink(old);
		}
	}catch(e){} // Cache availability is never a prerequisite for filtering.
	fs.unlink(data_path);fs.unlink(proof_path);
}
export function load(path,mode,root){
	if(index(modes,mode)<0)die('Unsupported rule export mode');
	let source=digest(path,25000000),dir=null;
	try{dir=source?directory(root??''):null;}catch(e){}
	let cached=source?read_cache(dir,source,mode):null;
	if(cached!=null&&digest(path,25000000)==source)return cached;
	let list=domains(fs.readfile(path,25000001),mode);
	// Do not attach a proof to content replaced while it was being parsed.
	if(source&&digest(path,25000000)==source)save_cache(dir,source,mode,list);
	return list;
};
export function fingerprint(path){return digest(path,25000000);};
