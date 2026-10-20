const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element {
 constructor(tag){this.tagName=tag;this.children=[];this.events={};this.attributes={};this.value='';this.checked=false;this.hidden=false;this.dataset={};this.textContent='';}
 append(...nodes){this.children.push(...nodes)}
 replaceChildren(...nodes){this.children=nodes}
 setAttribute(k,v){this.attributes[k]=v}
 addEventListener(k,v){this.events[k]=v}
 querySelectorAll(){return this.children.filter(c=>c.tagName==='button')}
 focus(){this.focused=true}
 async fire(type){return this.events[type]?.({preventDefault(){}})}
 requestSubmit(){return this.fire('submit')}
 dispatchEvent(e){return this.fire(e.type)}
}
const ids=['analyze-form','search-form','analyze','search','news-input','query','status','topics-panel','analysis-results','cancel-request','retry-request','results-panel','topics','analysis-note','year','kind','oa','papers','result-count','more','source-status','result-query','external-links','results-title','privacy'];
const elements=Object.fromEntries(ids.map(id=>[id,new Element(id)]));
const document={getElementById:id=>elements[id],createElement:tag=>new Element(tag),querySelectorAll:selector=>selector.includes('#topics')?elements.topics.children:[]};
let fail=false, hold=false, honorAbort=false, analyzed=0,searched=0,timerId=0;
const pending=[],timers=new Map();
const fetch=async(url,options)=>{
 if(hold)return new Promise((resolve,reject)=>{pending.push({url,options,resolve});if(honorAbort)options.signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'})));});
 if(fail)throw new Error('Failed to fetch');
 if(url.endsWith('analyze')){analyzed++;return{ok:true,json:async()=>({topics:[{name:'绳网回收',query:'tether net capture dynamics'},{name:'动力学',query:'capture dynamics'}],method:'关键词识别',notice:'请确认'})}}
 searched++;return{ok:true,json:async()=>({papers:[
 {title:'<img src=x onerror=alert(1)>',authors:['A'],year:2024,type:'期刊论文',sources:['Crossref'],doi:'10.0000/test',url:'https://example.org/paper',fulltext:'',relation:'主题线索',reason:'关键词匹配',abstract:'source abstract'},
 {title:'Net capture',authors:[],year:2023,type:'预印本',sources:['arXiv'],url:'javascript:alert(1)',fulltext:'https://example.org/public',relation:'主题线索',reason:'关键词匹配'}],sources:[{source:'Crossref',state:'ok',count:1},{source:'Semantic Scholar',state:'error',message:'来源限流'}],links:[{name:'test',url:'javascript:alert(1)'}],query:JSON.parse(options.body).query})};
};
vm.runInNewContext(fs.readFileSync('reader_web/reader.js','utf8'),{document,fetch,URL,URLSearchParams,location:{search:''},AbortController,Event,setTimeout(fn){const id=++timerId;timers.set(id,fn);return id},clearTimeout:id=>timers.delete(id),Option:class extends Element{constructor(t,v){super('option');this.textContent=t;this.value=v}}});
(async()=>{
 const markup=fs.readFileSync('reader_web/index.html','utf8');
 assert(!/<section id="topics-panel"[^>]*\shidden(?:\s|>)/.test(markup),'Manual search must be available before analysis');
 elements.query.value='known technical term';await elements['search-form'].fire('submit');
 assert.equal(analyzed,0);assert.equal(searched,1);
 elements['news-input'].value='绳网回收';
 await elements['analyze-form'].fire('submit');
 assert.equal(analyzed,1);assert.equal(elements.query.value,'tether net capture dynamics');assert.equal(elements['topics-panel'].hidden,false);
 await elements.topics.children[1].fire('click');assert.equal(elements.query.value,'capture dynamics');
 await elements['search-form'].fire('submit');assert.equal(searched,2);assert.equal(elements.papers.children.length,2);
 assert.match(elements.status.textContent,/部分来源/);assert.equal(elements['external-links'].children.length,0);
 const title=elements.papers.children[0].children[1].children.find(c=>c.tagName==='h3');
 assert.equal(title.children[0].textContent,'<img src=x onerror=alert(1)>');
 elements.oa.checked=true;await elements.oa.fire('change');assert.equal(elements.papers.children.length,1);
 elements.year.value='2024';await elements.year.fire('change');assert.match(elements.papers.children[0].textContent,/没有论文/);
 fail=true;await elements['search-form'].fire('submit');assert.match(elements.status.textContent,/无法连接/);assert.equal(elements.search.disabled,false);assert.equal(elements['results-panel'].hidden,true);
 assert(!elements.status.textContent.includes('本地服务'));assert.equal(elements['retry-request'].hidden,false);assert.equal(elements['external-links'].children.length,3);
 fail=false;await elements['retry-request'].fire('click');await new Promise(setImmediate);assert.equal(elements['results-panel'].hidden,false);
 fail=true;await elements['analyze-form'].fire('submit');assert.equal(elements['topics-panel'].hidden,false);assert.equal(elements.query.disabled,false);
 await elements['news-input'].fire('input');assert.equal(elements['analysis-results'].hidden,true);assert.equal(elements['topics-panel'].hidden,false);
 fail=false;hold=true;elements.query.value='old query';const oldRun=elements['search-form'].fire('submit');
 assert.equal(elements.query.disabled,true);await elements['cancel-request'].fire('click');
 assert(pending.at(-1).options.signal.aborted);assert.equal(elements.query.disabled,false);assert.equal(elements.query.value,'old query');assert.equal(elements.query.focused,true);
 hold=false;elements.query.value='new query';await elements['search-form'].fire('submit');
 const status=elements.status.textContent;
 pending.at(-1).resolve({ok:true,json:async()=>({query:'stale',papers:[],sources:[],links:[]})});await oldRun;
 assert.equal(elements['result-query'].textContent,'本次检索：new query');assert.equal(elements.status.textContent,status);assert.equal(elements.papers.children.length,2);
 hold=true;honorAbort=true;const timedRun=elements['search-form'].fire('submit');[...timers.values()].at(-1)();await timedRun;
 assert.match(elements.status.textContent,/超时/);assert.equal(elements.query.disabled,false);assert.equal(elements['retry-request'].hidden,false);assert.equal(timers.size,0);
 console.log('Paper finder: direct search, analysis failure recovery, cancel/abort, stale-response isolation, timeout/retry, safe links and filters passed.');
})().catch(e=>{console.error(e);process.exitCode=1});
