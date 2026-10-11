const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const web=path.resolve(__dirname,'../web');
const read=n=>fs.readFileSync(path.join(web,n),'utf8');
for(const n of ['ai-ui.js','news-ui.js'])new vm.Script(read(n),{filename:n});
const atlas=read('resource-navigation.html');
for(const m of atlas.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g))new vm.Script(m[1]);
for(const n of ['index.html','resource-navigation.html'])assert.equal((read(n).match(/href="\/assets\/design-system.css/g)||[]).length,1);
const css=read('design-system.css');
const colors=Object.fromEntries([...css.matchAll(/--(ui-[\w-]+):\s*(#[0-9a-f]{6})/g)].map(m=>[m[1],m[2]]));
function luminance(hex){return hex.slice(1).match(/../g).map(x=>parseInt(x,16)/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4).reduce((v,x,i)=>v+x*[.2126,.7152,.0722][i],0);}
for(const [a,b] of [['primary','on-primary'],['surface','on-surface'],['surface','muted'],['secondary-container','on-secondary'],['error-container','error'],['disabled','on-disabled']]){
 const [x,y]=[luminance(colors['ui-'+a]),luminance(colors['ui-'+b])];const ratio=(Math.max(x,y)+.05)/(Math.min(x,y)+.05);assert(ratio>=4.5,a+' contrast '+ratio);console.log(a+': '+ratio.toFixed(2)+':1');
}
// Exercise existing availability handling without contacting a provider.
class Node {
 constructor(){this.dataset={};this.children=[];this.value='';this.textContent='';this.listeners={};this.classList={contains:()=>false};}
 setAttribute(k,v){this[k]=v} addEventListener(k,fn){this.listeners[k]=fn} querySelectorAll(){return []} focus(){} replaceChildren(){this.children=[]}
}
const nodes=new Map();const get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id)};
let fail=true,calls=0;
const events={};
const context={document:{getElementById:get,querySelectorAll:()=>[],addEventListener:(k,fn)=>events[k]=fn},location:{hash:'#home'},AbortSignal,fetch:async()=>{calls++;if(fail)throw Error('offline');return {ok:true,status:200,json:async()=>({enabled:true,message:'可以提问',history_retention_seconds:600})}},setInterval(){},setTimeout,clearTimeout,window:{},console};
vm.runInNewContext(read('ai-ui.js'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 await flush();assert.equal(get('ai-send').disabled,true);assert.equal(get('ai-input-hint').hidden,true);assert(!read('index.html').includes('ai-status-retry'));
 fail=false;events.pagechange({detail:'home'});await flush();assert.equal(get('ai-input-hint').hidden,false);assert.equal(get('ai-question').disabled,false);
 get('ai-question').value='发动机如何产生推力？';get('ai-question').listeners.input();assert.equal(get('ai-send').disabled,false);assert.equal(calls,2);
 console.log('Syntax, asset references, color contrast and existing AI availability checks passed.');
})().catch(e=>{console.error(e);process.exitCode=1});
