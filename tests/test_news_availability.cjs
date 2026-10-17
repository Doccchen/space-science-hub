'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const makeButton=()=>({disabled:false,textContent:'',title:'',attributes:{},setAttribute(name,value){this.attributes[name]=value}});
const button=makeButton(),events={},window={},news={classList:{contains:()=>false}};
let answer={enabled:false,message:'新闻科普暂未开放。'},fail=false,calls=0;
const document={hidden:false,getElementById:()=>news,querySelectorAll:()=>[button],addEventListener(name,fn){events[name]=fn}};
const context={window,document,AbortSignal,setInterval(){},fetch:async()=>{calls++;if(fail)throw Error('offline');return {ok:true,json:async()=>answer}}};
vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../web/news-agent-availability.js'),'utf8'),context);
(async()=>{
 await window.newsAgentAvailability.refresh();
 assert.equal(calls,1); // The initial load and simultaneous refresh share one request.
 assert.equal(button.disabled,true);assert.equal(button.textContent,'新闻科普暂未开放。');
 answer={enabled:true,message:'基于当前新闻提问。'};
 await window.newsAgentAvailability.refresh();
 assert.equal(button.disabled,false);assert.equal(button.textContent,'科普解读与提问');assert.equal(button.attributes['aria-disabled'],'false');
 const fresh=makeButton();window.newsAgentAvailability.decorate(fresh);assert.equal(fresh.disabled,false);
 answer={enabled:false,message:'新闻科普暂未开放。'};
 await window.newsAgentAvailability.refresh();assert.equal(button.disabled,true);
 fail=true;await window.newsAgentAvailability.refresh();assert.equal(button.disabled,true);assert.equal(button.textContent,'新闻科普状态暂不可用');
 fail=false;answer={enabled:true};await window.newsAgentAvailability.refresh();assert.equal(button.disabled,false);
 answer={enabled:'true'};await window.newsAgentAvailability.refresh();assert.equal(button.disabled,true);
 assert.equal(calls,6);console.log('News availability transitions, new rows and failure recovery passed.');
})().catch(error=>{console.error(error);process.exitCode=1});
