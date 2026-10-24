'use strict';
import * as fs from 'fs';
// All readers and writers use the same device profile. These are resident-set
// safeguards, never a lifetime quota or a per-click allowance.
export function limits(root){
	root??=getenv('ADZERO_SOURCES_ROOT')??getenv('ADZERO_ADAPTER_ROOT')??getenv('ADZERO_BACKEND_ROOT')??getenv('ADZERO_POLICY_ROOT')??'';
	let raw=fs.readfile(root+'/proc/meminfo')??'',m=match(raw,/MemTotal:[[:space:]]+([0-9]+)/),memory=m?int(m[1]):0;
	let total=500000,source=500000,bytes=25000000,tier='compact';
	if(memory>=3145728){total=4000000;source=2000000;bytes=64000000;tier='large';}
	else if(memory>=1572864){total=2000000;source=1000000;bytes=48000000;tier='standard';}
	else if(memory>=524288){total=1000000;source=750000;bytes=32000000;tier='medium';}
	return {tier,memory_kib:memory,source_domains:source,total_domains:total,candidate_domains:total*2,source_bytes:bytes,output_bytes:tier=='compact'?25000000:bytes*2,cache_file_bytes:tier=='compact'?32000000:bytes*3};
};
// Match only native subtree optimization. Hosts exports are exact records;
// never remove a child there or invent a parent to shrink the count.
export function effective(values,allowed,mode){
	let allow={},count=0,subtree=index(['dnsmasq.servers','smartdns.domainset','unbound.adb_list'],mode)>=0;
	for(let n in type(allowed)=='array'?allowed:allowed==null?[]:[allowed])if(type(n)=='string')allow[lc(n)]=true;
	for(let n in values){
		let omit=false;
		for(let p=n;index(p,'.')>=0;p=substr(p,index(p,'.')+1)){
			if(allow[p]||subtree&&p!=n&&values[p]){omit=true;break;}
		}
		if(!omit)count++;
	}return count;
};
