'use strict';
// Narrow adapter for adblock-fast list downloads, scoped to ctl's child PATH.
import * as fs from 'fs';
import { cursor } from 'uci';
import * as cache from './source-cache.uc';
import { url } from './source-lib.uc';
let action=shift(ARGV);if(action=='--')action=shift(ARGV);
try{
	if(getenv('ADZERO_SOURCE_REPLAY')!='1')exit(1);
	let root=getenv('ADZERO_SOURCES_ROOT')??'',address=null,output=null,maxsize=25000000;
	for(let i=0;i<length(ARGV);i++){
		let a=ARGV[i];
		if(index(['-f','--silent'],a)>=0)continue;
		if(index(['--max-filesize','--retry','--connect-timeout','--speed-limit','--speed-time','--max-time'],a)>=0){if(!match(ARGV[++i]??'',/^[0-9]+$/))exit(1);if(a=='--max-filesize')maxsize=int(ARGV[i]);continue;}
		if(a=='-o'){if(output)exit(1);output=ARGV[++i];continue;}
		if(a=='--'||substr(a,0,1)=='-'||address)exit(1);address=url(a);
	}
	// Do not intercept HEAD/version/config checks or unrelated descendant curl.
	if(!address||!match(output??'',/^\/tmp\/adblock-fast_tmp\.[A-Za-z0-9]+$/))exit(1);
	let c=cursor(root+'/etc/config'),selected=false;
	if(c.get('adblock-fast','config','curl_additional_param'))exit(1);
	c.foreach('adblock-fast','file_url',s=>{if(s.enabled!='0'&&s.url==address)selected=true;});if(!selected)exit(1);
	let path=root+output,s=fs.lstat(path);
	if(s?.type!='file'||s.uid!=fs.stat('/proc/self')?.uid||(s.mode&0077))exit(1);
	if(action=='replay'){
		let snap=cache.load(address,root);if(!snap)exit(1);
		let raw=fs.readfile(snap.path,25000001);if(!raw||length(raw)>25000000||length(raw)>maxsize)exit(1);
		let f=fs.open(path,'w');if(!f)exit(1);let written=f.write(raw),closed=f.close();exit(written==length(raw)&&closed?0:1);
	}
	if(action=='store'){cache.save(address,fs.readfile(path,25000001),root);exit(0);}
}catch(e){}
exit(1);
