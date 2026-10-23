'use strict';
import { lan_valid } from './dns-handoff-lib.uc';
const table='adzero_dns_enhance',marker='AdZero DNS enhance v1';
function decode(result){
	if(result?.code!=0)die('无法核对 DNS 增强防火墙状态，恢复记录已保留。');
	try{let value=json(result.output);if(type(value?.nftables)=='array')return value;}catch(e){}
	die('DNS 增强防火墙状态无效，恢复记录已保留。');
}
// The executor reports exit status and combined output. No broad conntrack
// flush: a private intent record binds cleanup to our exact LAN destination.
export function release(prior,execute){
	if(prior!=null&&!lan_valid(prior.lan))die('DNS 增强恢复记录无效，未清理连接。');
	let tables=decode(execute(['nft','-j','list','tables']));
	if(length(filter(tables.nftables,e=>e.table?.family=='inet'&&e.table.name==table))){
		let current=decode(execute(['nft','-j','list','table','inet',table]));
		if(length(filter(current.nftables,e=>e.table?.family=='inet'&&e.table.name==table&&e.table.comment==marker))!=1)
			die('DNS 增强表已由其他配置管理，未执行删除。');
		if(prior==null)die('缺少 DNS 增强恢复记录，未移除接管。');
		if(execute(['nft','delete','table','inet',table])?.code!=0)die('DNS 增强接管未能移除，恢复记录已保留。');
	}
	// A firewall reload may already have removed the table. NAT bindings
	// survive that removal, so the saved intent still needs to be retired.
	if(prior==null)return;
	for(let protocol in ['udp','tcp']){
		let result=execute(['conntrack','-D','-f','ipv4','-p',protocol,'--orig-dst',prior.lan.address,'--dport','53',
			'--reply-src',prior.lan.address,'--reply-port-src','5354','--zone','0']);
		// conntrack returns 1 for an empty selection. Other failures, including
		// permissions/missing tools, must not be reported as completed cleanup.
		if(result?.code!=0&&!(result?.code==1&&match(trim(result.output??''),/^conntrack v[^\r\n:]+: 0 flow entries have been deleted[.]$/)))
			die('DNS 增强旧会话未能清理，恢复记录已保留。');
	}
};
