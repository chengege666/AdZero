'use strict';
import * as fs from 'fs';
import * as lib from './routing-lib.uc';
import * as progress from './progress-lib.uc';
const root=getenv('ADZERO_ADAPTER_ROOT')??'',dir=root+'/etc/adzero/routing-data';
let action=shift(ARGV);if(action=='--')action=shift(ARGV);
function quote(s){return "'"+replace(s,/'/g,"'\\''")+"'";}
function command(args){
	let p=fs.popen(join(' ',map(args,quote))+' 2>/dev/null','r');if(!p)die('Cannot run rule validation');
	let text=p.read('all'),rc=p.close();if(rc!=0)die('国内规则库下载或校验失败，请检查网络。');return text;
}
function mkdir(path){let info=fs.lstat(path);if(info?.type=='directory')return;if(info)die('Unexpected routing cache path');mkdir(fs.dirname(path));if(!fs.mkdir(path,0700))die('Cannot create routing cache');}
function clear_temporary(path){let info=fs.lstat(path);if(!info)return;if(info.type!='file'||!fs.unlink(path))die('Unexpected routing cache temporary file');}
function atomic(path,value){
	if(fs.lstat(path)?.type=='link')die('Refusing routing cache symlink');
	let tmp=path+'.new';clear_temporary(tmp);let f=fs.open(tmp,'wx',0600);if(!f)die('Routing cache has an incomplete write');
	let count=f.write(value),ok=f.close();if(count!=length(value)||!ok||!fs.rename(tmp,path)){fs.unlink(tmp);die('Cannot save routing data');}
}
try{
	if(action!='prepare')die('Usage: routing-data prepare');
	let fixture=getenv('ADZERO_ROUTING_DATA_FIXTURE');
	if(root&&fixture){
		let data=json(fs.readfile(fixture));
		data.domains=lib.domain_list(data.domain_raw);data.cidrs=lib.cidr_list(data.cidr_raw);delete data.domain_raw;delete data.cidr_raw;
		print(sprintf('%J',data));exit(0);
	}
	mkdir(dir);
	let data={schema:1,sources:lib.sources};
	for(let source in lib.sources){
		let path=dir+'/'+source.name+'.raw',valid=false;
		if(fs.lstat(path)?.type=='link')die('Refusing routing source symlink');
		if(fs.stat(path)?.type=='file')valid=split(command(['sha256sum',path]),' ')[0]==source.sha256;
		if(!valid){
			progress.stage('downloading');
			let tmp=path+'.download';clear_temporary(tmp);
			try{
				command(['curl','--fail','--location','--proto','=https','--proto-redir','=https','--connect-timeout','10','--max-time','90','--max-filesize','5000000','--output',tmp,source.url]);
				if(split(command(['sha256sum',tmp]),' ')[0]!=source.sha256)die('国内规则库校验不一致。');
				if(!fs.rename(tmp,path))die('Cannot commit routing source');
			}catch(e){fs.unlink(tmp);die(e);}
		}
		let raw=fs.readfile(path,5000001);
		progress.stage('validating');
		data[source.name]=source.name=='domains'?lib.domain_list(raw):lib.cidr_list(raw);
	}
	let text=sprintf('%J',data);
	if(fs.readfile(dir+'/snapshot.json')!=text)atomic(dir+'/snapshot.json',text);
	print(text);
}catch(e){progress.failure('country_data');fs.stderr.write('AdZero routing data: '+e.message+'\n');exit(1);}
