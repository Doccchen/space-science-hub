const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const fixtureSource=fs.readFileSync('tests/test_frontend_availability.cjs','utf8');
const Element=vm.runInNewContext(fixtureSource.slice(fixtureSource.indexOf('class Element'),fixtureSource.indexOf('const flush='))+';Element');
Element.prototype.insertBefore=function(node){this.append(node);};
Element.prototype.removeAttribute=function(name){delete this.attributes[name];};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function launch(saved){
 const ids={};for(const match of fs.readFileSync('web/research.html','utf8').matchAll(/id="([^"]+)"/g))ids[match[1]]=new Element();
 ids['storage-note'].nextElementSibling=new Element();
 const workspace=new Element(),bottom=new Element(),modes=['knowledge','papers'].map(mode=>{const e=new Element('button');e.dataset.mode=mode;return e;});
 let stored=JSON.stringify(saved),resolveAnswer;const calls=[];
 const context={document:{getElementById:id=>ids[id],createElement:tag=>new Element(tag),querySelector:s=>s==='.workspace'?workspace:bottom,querySelectorAll:s=>s.startsWith('.mode-switch')?modes:[],addEventListener(){},createTextNode:text=>Object.assign(new Element('#text'),{textContent:text})},
 localStorage:{getItem:()=>stored,setItem:(key,value)=>{stored=value;}},location:{search:''},crypto:require('node:crypto').webcrypto,URL,URLSearchParams,AbortController,AbortSignal,Date,
 setTimeout:()=>1,clearTimeout(){},fetch:async(url,options={})=>{calls.push({url,options});let data=url.endsWith('/config')?{source_count:4}:url.endsWith('/status')?{enabled:true}:url.endsWith('/conversations')?{conversation_id:'session-test'}:url.endsWith('/analyze')?{topics:[]}:{};
 if(url.endsWith('/ask'))data=await new Promise(resolve=>{resolveAnswer=resolve;});return {ok:true,json:async()=>data};}};
 context.window={};vm.runInNewContext(fs.readFileSync('web/article-renderer.js','utf8'),context);
 vm.runInNewContext(fs.readFileSync('web/research.js','utf8'),context);await flush();
 const text=()=>{const walk=e=>[e.textContent||'',...e.children.map(walk)].join(' ');return walk(ids.messages);};
 return {ids,modes,text,stored:()=>JSON.parse(stored),calls,answer:()=>resolveAnswer({answer:'迟到的知识回答',sources:[],remaining_rounds:2}),flush};
}
const knowledge={id:'knowledge',title:'知识研究',mode:'knowledge',draft:'知识草稿',session:'old-session',updated:Date.now(),messages:[{role:'user',text:'知识问题'},{type:'answer',text:'知识回答'}]};
const papers={id:'papers',title:'论文研究',mode:'papers',draft:'论文草稿',updated:Date.now(),messages:[]};
(async()=>{
 const app=await launch({selected:'knowledge',works:[knowledge,papers]});
 assert.match(app.text(),/知识回答/);app.modes[1].onclick();
 assert.doesNotMatch(app.text(),/知识回答/,'切换到论文查找后必须隐藏知识回答');assert.equal(app.ids.question.value,'论文草稿');
 app.ids.question.value='新的论文草稿';app.ids.question.oninput();app.modes[0].onclick();assert.equal(app.ids.question.value,'知识草稿');assert.match(app.text(),/知识回答/);
 app.ids.question.value='继续知识提问';app.ids.question.oninput();const pending=app.ids.composer.onsubmit({preventDefault(){}});await flush();app.modes[1].onclick();assert.equal(app.ids.question.disabled,false);assert.equal(app.ids.question.value,'新的论文草稿');app.answer();await pending;assert.doesNotMatch(app.text(),/迟到的知识回答/);app.modes[0].onclick();assert.match(app.text(),/迟到的知识回答/);
 const restored=await launch(app.stored());assert.match(restored.text(),/迟到的知识回答/);restored.modes[1].onclick();assert.equal(restored.ids.question.value,'新的论文草稿');
 const mixed=await launch({selected:'legacy',works:[{...knowledge,id:'legacy',mode:'papers',draft:'旧论文草稿',messages:[{role:'user',text:'旧知识问题'},{type:'answer',text:'旧知识回答'},{role:'user',text:'旧论文问题'},{type:'error',text:'旧检索错误'}]}]});
 // An error has no provider marker; retain it in the last active mode.
 mixed.modes[0].onclick();assert.match(mixed.text(),/旧知识回答/);assert.doesNotMatch(mixed.text(),/旧论文问题/);assert.equal(mixed.stored().works.find(w=>w.mode==='knowledge').session,'old-session');
 mixed.modes[1].onclick();assert.match(mixed.text(),/旧论文问题/);assert.equal(mixed.ids.question.value,'旧论文草稿');
 const fresh=await launch(null);fresh.modes[0].onclick();assert.equal(fresh.ids['welcome-title'].textContent,'今天，想了解什么？');fresh.ids['quick-new'].onclick();assert.equal(fresh.stored().works.find(w=>w.id===fresh.stored().selected).mode,'knowledge');fresh.modes[1].onclick();assert.equal(fresh.ids['welcome-title'].textContent,'我们要研究什么？');
 console.log('PASS: mode-specific content, drafts, late responses and reload');
})().catch(error=>{console.error(error);process.exitCode=1;});
