'use strict';
import * as fs from 'fs';
// Content-addressed recovery data: never embed megabytes of provider bytes in
// every metadata write. Legacy schema-1 base64 journal entries remain readable.
export function store(directory,limit,atomic){
	let uid=fs.stat('/proc/self').uid;
	function private_file(path){let s=fs.lstat(path);return s?.type=='file'&&s.uid==uid&&!(s.mode&0077)&&s.size<=limit;}
	function folder(create){
		let s=fs.lstat(directory);
		if(!s&&create){fs.mkdir(directory,0700);s=fs.lstat(directory);}
		if(!s)return false;
		if(s.type!='directory'||s.uid!=uid||(s.mode&0077))die('Invalid provider recovery directory');
		return true;
	}
	function valid(ref){return ref?.schema==1&&match(ref.sha256??'',/^[a-f0-9]{64}$/)&&type(ref.size)=='int'&&ref.size>=0&&ref.size<=limit;}
	function digest(path){
		let s=fs.lstat(path);if(s?.type!='file'||s.uid!=uid||(s.mode&0022)||s.size>limit)return null;
		let p=fs.popen('sha256sum '+"'"+replace(path,/'/g,"'\\''")+"'"+' 2>/dev/null','r');if(!p)return null;
		let raw=p.read('all'),rc=p.close(),hash=split(raw??'',' ')[0];return rc==0&&match(hash,/^[a-f0-9]{64}$/)?hash:null;
	}
	function matches(path,ref){
		if(type(ref)=='string')return b64enc(fs.readfile(path))==ref;
		if(ref==null)return fs.lstat(path)==null;
		return valid(ref)&&fs.lstat(path)?.size==ref.size&&digest(path)==ref.sha256;
	}
	function read(ref){
		if(ref==null)return null;
		if(type(ref)=='string')return b64dec(ref);
		if(!valid(ref)||!folder(false))die('Invalid provider recovery reference');
		let path=directory+'/'+ref.sha256;
		if(!private_file(path)||!matches(path,ref))die('Provider recovery snapshot missing or changed');
		let raw=fs.readfile(path,limit+1);if(raw==null||length(raw)!=ref.size)die('Cannot read provider recovery snapshot');return raw;
	}
	function put(raw){
		if(raw==null)return null;
		if(length(raw)>limit)die('Provider recovery capacity exceeded');
		folder(true);
		let temp=directory+'/pending-'+trim(fs.readfile('/proc/sys/kernel/random/uuid')??'');
		atomic(temp,raw,0600);
		let hash=digest(temp);if(!hash){fs.unlink(temp);die('Cannot fingerprint provider recovery snapshot');}
		let ref={schema:1,sha256:hash,size:length(raw)},path=directory+'/'+hash;
		if(fs.lstat(path)){
			if(!matches(path,ref)){fs.unlink(temp);die('Provider recovery snapshot changed');}
			fs.unlink(temp);
		}else if(!fs.rename(temp,path)){fs.unlink(temp);die('Cannot save provider recovery snapshot');}
		return ref;
	}
	function gc(journals){
		if(!folder(false))return;
		let keep={};
		for(let journal in journals??[])for(let f in journal?.files??[])for(let ref in [f.before,f.after,f.previous_after])if(valid(ref))keep[ref.sha256]=true;
		for(let name in fs.lsdir(directory)??[])if(match(name,/^[a-f0-9]{64}$/)&&!keep[name]&&private_file(directory+'/'+name))fs.unlink(directory+'/'+name);
		fs.rmdir(directory); // succeeds only when no referenced snapshots remain
	}
	return {put,read,matches,gc};
};
