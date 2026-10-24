'use strict';
import { lan_valid } from './dns-handoff-lib.uc';
import { effective } from './routing-lib.uc';
export const table='adzero_dns_guard';
export const marker='AdZero strict DNS v1';
export function rules(lan,profile,ready,bootstrap){
	if(!lan_valid(lan))die('严格模式需要可确认的单个 IPv4 LAN。');
	let p=effective(profile),lines=[];
	if(bootstrap)for(let family in ['ip','ip6']){
		let ips=filter(p.domestic,v=>(index(v,':')>=0)==(family=='ip6'));
		if(length(ips))push(lines,family+' daddr { '+join(', ',ips)+' } meta l4proto { udp, tcp } th dport 53 accept');
	}
	let lanif=sprintf('%J',lan.device),orig='meta l4proto { udp, tcp } ct direction original ct original proto-dst 53';
	return 'table inet '+table+' {\n comment "'+marker+'"\n'+
		' chain capture { type nat hook prerouting priority -110; policy accept;\n iifname '+lanif+' meta nfproto ipv4 meta l4proto { udp, tcp } th dport 53 redirect to :53\n }\n'+
		' chain input { type filter hook input priority -5; policy accept;\n iifname '+lanif+' meta l4proto { udp, tcp } th dport 853 drop\n'+
		' iifname '+lanif+' meta nfproto ipv6 '+orig+' drop\n'+
		' iifname '+lanif+' meta l4proto tcp ct direction original ct original proto-dst 53 tcp dport != 53 reject with tcp reset\n'+
		' iifname '+lanif+' '+orig+' th dport != 53 drop\n'+(ready?'':' iifname '+lanif+' '+orig+' drop\n')+' }\n'+
		' chain forward { type filter hook forward priority -5; policy accept;\n iifname '+lanif+' '+orig+' drop\n iifname '+lanif+' meta l4proto { udp, tcp } th dport 853 drop\n }\n'+
		' chain output { type filter hook output priority -5; policy accept;\n oifname "lo" accept\n '+join('\n ',lines)+'\n meta l4proto { udp, tcp } th dport { 53, 853 } drop\n }\n}\n';
};
