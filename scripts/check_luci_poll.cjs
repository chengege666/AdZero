#!/usr/bin/env node
/* Execute production view tests with the exact scheduler from a supplied SDK. */
'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path'),crypto=require('crypto');
const input=process.argv[2];
if(!input)throw Error('Usage: node scripts/check_luci_poll.cjs /path/to/luci.js');
const raw=fs.readFileSync(input,'utf8'),start=raw.indexOf('const Poll = Class.singleton('),end=raw.indexOf('\n\t/**',raw.indexOf('\n\t});',start)+7);
if(start<0||end<start)throw Error('Unsupported SDK scheduler layout');
const snippet=raw.slice(start,end);
if(!snippet.includes('this.step();')||!snippet.includes('Promise.resolve(e.fn()).finally'))throw Error('SDK scheduler missing expected native semantics');
global.adzeroNativePollFactory=function(document){
  const callbacks=new Map();let next=1;
  const window={setInterval(fn){const id=next++;callbacks.set(id,fn);return id;},clearInterval(id){callbacks.delete(id);}};
  const context={Class:{singleton:x=>x},env:{pollinterval:5},window,document:{dispatchEvent(){}},CustomEvent:class{},Promise};
  const poll=vm.runInNewContext(snippet+'\nPoll;',context);
  poll.tick=0; // luCI initializes the poller before a view is loaded.
  return {...poll,native:poll,add:poll.add.bind(poll),remove:poll.remove.bind(poll),async tick(){poll.step();for(let i=0;i<12;i++)await Promise.resolve();}};
};
process.argv.length=2;
require(path.resolve(__dirname,'../tests/test_view.cjs'));
console.log('SDK LuCI scheduler SHA-256: '+crypto.createHash('sha256').update(snippet).digest('hex'));
