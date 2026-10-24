'use strict';
// A NaiLink native-listener fallback survives an enhancement-worker crash.
// Called only by adapter transactions, with intent stored in adapter.json.
import * as fs from 'fs';
import { lan_valid } from './dns-handoff-lib.uc';
import { release } from './dns-cleanup.uc';
let action=shift(ARGV);if(action=='--')action=shift(ARGV);
function quote(s){return "'"+replace(''+s,/'/g,"'\\''")+"'";}
function run(argv){let p=fs.popen(join(' ',map(argv,quote))+' 2>&1','r');if(!p)return {code:-1};let output=p.read('all'),code=p.close();return {code,output};}
try{
	let context=json(fs.readfile(shift(ARGV),4097));if(!lan_valid(context?.lan)||context.port!=5355)die('native_context');
	if(action=='cleanup')release(context,run,true);
	else if(action=='install'){
		let tables=run(['nft','-j','list','tables']);if(tables.code!=0)die('native_nft');
		let exists=length(filter(json(tables.output).nftables??[],e=>e.table?.family=='inet'&&e.table.name=='adzero_dns_native'));
		if(exists){let t=run(['nft','-j','list','table','inet','adzero_dns_native']);if(t.code!=0||length(filter(json(t.output).nftables??[],e=>e.table?.comment=='AdZero native DNS bridge v1'))!=1)die('native_ownership');}
		let script=(exists?'delete table inet adzero_dns_native\n':'')+'add table inet adzero_dns_native { comment "AdZero native DNS bridge v1"; }\nadd chain inet adzero_dns_native input_dns { type nat hook prerouting priority -100; policy accept; }\n'+
			'add rule inet adzero_dns_native input_dns iifname "'+context.lan.device+'" ip saddr '+context.lan.address+'/'+context.lan.mask+' ip daddr '+context.lan.address+' meta l4proto { tcp, udp } th dport 53 redirect to :5355\n';
		let path='/tmp/adzero-native-'+fs.readlink('/proc/self')+'.nft',f=fs.open(path,'wx',0600);if(!f)die('native_write');let ok=f.write(script)==length(script),closed=f.close();
		let result=ok&&closed?run(['nft','-f',path]):null;fs.unlink(path);if(result?.code!=0)die('native_install');
	}else die('native_action');
}catch(e){fs.stderr.write('AdZero native DNS: native bridge operation failed; recovery record retained\n');exit(1);}
