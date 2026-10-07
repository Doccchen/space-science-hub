/* DOM event regressions without a browser, production data or provider requests. */
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element {
  constructor(tag='div') {
    this.tagName=tag;this.children=[];this.listeners={};this.dataset={};this.attributes={};this.hidden=false;this.disabled=false;this.value='';
    const names=new Set();this.classList={add:name=>names.add(name),remove:name=>names.delete(name),contains:name=>names.has(name),toggle:(name,on)=>{if(on)names.add(name);else names.delete(name);}};
  }
  append(...nodes){nodes.forEach(n=>{if(n.tagName==='#fragment'){this.append(...[...n.children]);return;}if(n.parent)n.remove();n.parent=this;this.children.push(n);});}
  replaceChildren(...nodes){this.children=[];this.append(...nodes);}
  add(node){this.append(node);}
  addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}
  trigger(name,event={}){for(const fn of this.listeners[name]||[])fn(event);}
  setAttribute(name,value){this.attributes[name]=value;}
  querySelectorAll(selector){
    const [first,...rest]=selector.split(' ');
    const matches=c=>first.startsWith('.')?(c.className||'').split(' ').includes(first.slice(1)):c.tagName===first;
    return this.children.flatMap(c=>[...(matches(c)?(rest.length?c.querySelectorAll(rest.join(' ')):[c]):[]),...c.querySelectorAll(selector)]);
  }
  querySelector(selector){return this.querySelectorAll(selector)[0];}
  get lastElementChild(){return this.children.at(-1);}
  get options(){return this.children.filter(el=>el.tagName==='option');}
  get selectedOptions(){return this.options.filter(el=>el.value===this.value);}
  replaceWith(node){const parent=this.parent,index=parent.children.indexOf(this);this.remove();parent.children.splice(index,0,node);node.parent=parent;}
  dispatchEvent(event){this.trigger(event.type,event);}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);}
  focus(){this.focused=true;}
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const read=name=>fs.readFileSync(path.join(__dirname,'../web',name),'utf8');
async function aiAvailability(){
  const ids=Object.fromEntries(['ai-form','ai-question','ai-send','ai-new','ai-thread','ai-welcome','ai-feedback','ai-waiting',
    'ai-counter','ai-starters','ai-welcome-copy','ai-service-text','ai-status-dot','ai-retention','home','ai-complete'].map(id=>[id,new Element()]));
  const starter=new Element('button');starter.dataset.aiQuestion='示例问题';ids['ai-starters'].append(starter);
  let status={enabled:false,message:'知识库问答暂未开放。',history_retention_seconds:3600},fail=false;const requests=[],ticks=[];
  const document={getElementById:id=>ids[id],querySelectorAll:()=>[starter],addEventListener(){},createElement:tag=>new Element(tag)};
  const context={document,window:{scrollTo(){}},location:{hash:'#home'},matchMedia:()=>({matches:false}),AbortSignal,
    fetch:async url=>{requests.push(url);assert.equal(url,'/api/ai/status');if(fail)throw new Error('offline');return {ok:true,json:async()=>status};},
    setInterval:fn=>ticks.push(fn),setTimeout(){},clearTimeout(){}};
  vm.runInNewContext(read('ai-ui.js'),context);await flush();
  assert.equal(ids['ai-question'].disabled,true);assert.equal(ids['ai-starters'].hidden,true);
  assert.equal(ids['ai-welcome-copy'].textContent,status.message);
  starter.trigger('click');assert.equal(ids['ai-question'].value,'');
  status={...status,enabled:true,message:'可以提问'};ticks[0]();await flush();
  assert.equal(ids['ai-question'].disabled,false);assert.equal(ids['ai-starters'].hidden,false);
  starter.trigger('click');assert.equal(ids['ai-question'].value,'示例问题');assert.equal(ids['ai-send'].disabled,false);
  fail=true;ticks[0]();await flush();
  assert.equal(ids['ai-question'].disabled,true);assert.equal(ids['ai-starters'].hidden,true);
  assert.match(ids['ai-welcome-copy'].textContent,/状态暂不可用/);
  assert.equal(ids['ai-question'].value,'示例问题');assert.ok(requests.every(url=>url==='/api/ai/status'));
  fail=false;ticks[0]();await flush();assert.equal(ids['ai-feedback'].textContent,'');assert.equal(ids['ai-question'].disabled,false);
  console.log('AI disabled/enabled/offline transitions preserve drafts and never submit questions');
}
async function resourceCovers(){
  const ids=Object.fromEntries(['library-list','resource-message','resource-search','resource-category','resource-prev','resource-next',
    'resource-page','resource-pagination','resource-retry','empty-library','library-count','resource-empty-title','resource-empty-copy'].map(id=>[id,new Element()]));
  const events={};
  const items=[1,2,3].map(id=>({id:'book-'+id,title:'书籍 '+id,authors:[],size_bytes:1024,format:'PDF',category:'工程',
    cover_url:id<3?'/assets/resource-covers/book-'+id+'.jpg':null,download_url:'/api/resources/book-'+id+'/download'}));
  const document={getElementById:id=>ids[id],createElement:tag=>new Element(tag),addEventListener:(name,fn)=>{events[name]=fn;}};
  const context={document,window:{location:{hash:'#library'}},AbortController,URLSearchParams,
    Option:function(text,value){const el=new Element('option');el.textContent=text;el.value=value;return el;},
    fetch:async url=>{assert.ok(url.startsWith('/api/resources?'));return {ok:true,json:async()=>({pages:1,total:3,categories:['工程'],items})};},
    showPage:page=>events.pagechange({detail:page}),setTimeout(){},clearTimeout(){}};
  vm.runInNewContext(read('resources-ui.js'),context);await flush();
  assert.equal(ids['library-list'].children.length,3);
  const covers=ids['library-list'].children.map(card=>card.children[0]);
  assert.equal(covers[0].classList.contains('is-loading'),true);
  assert.equal(covers[0].children[0].children[0].textContent,'正在载入封面');
  covers[0].children[1].trigger('load');assert.equal(covers[0].children[0].hidden,true);
  assert.equal(covers[0].classList.contains('is-loading'),false);
  covers[1].children[1].trigger('error');assert.equal(covers[1].querySelectorAll('img').length,0);
  assert.equal(covers[1].children[0].children[0].textContent,'PDF');
  assert.equal(covers[2].classList.contains('is-loading'),false);
  assert.equal(covers[2].children[0].children[0].textContent,'PDF');
  items.forEach((item,i)=>assert.equal(ids['library-list'].children[i].querySelectorAll('a')[0].href,item.download_url));
  console.log('Resource loading/error/no-cover states keep stable download URLs');
}
async function newsSources(){
  const registry=[];const make=tag=>{const el=new Element(tag);registry.push(el);return el;};
  const page=make('main');page.id='news';const toolbar=make('div');toolbar.className='library-toolbar';toolbar.append(make('span'),make('span'));page.append(toolbar);
  const sources=['nasa','cnsa','cmse','esa','arianespace','spacex','extra'].map(id=>({id,name:id,enabled:id!=='spacex',
    region:'international',publisher_kind:'agency',last_success_at:'2026-10-07T00:00:00Z',last_error:id==='nasa'}));
  const requests=[];
  const context={document:{getElementById:id=>registry.find(el=>el.id===id),createElement:make,createDocumentFragment:()=>make('#fragment'),
      createTextNode:text=>{const el=make('#text');el.textContent=text;return el;},addEventListener(){}},
    window:{scrollTo(){}},matchMedia:()=>({matches:false,addEventListener(){}}),AbortSignal,URLSearchParams,URL,Event,
    fetch:async url=>{requests.push(url);return {ok:true,json:async()=>url==='/api/news/sources'?{items:sources,geographic_regions:[]}:
      {items:[{id:1,title:'保留原文标题',source_name:'nasa',original_url:'https://example.org/1',lang:'en',reading_mode:'link_only',published_at:'2026-10-07T00:00:00Z'}],
        page:1,page_size:20,total:1,total_pages:1,snapshot:1}};}};
  vm.runInNewContext(read('news-ui.js'),context);await flush();
  const groups=registry.filter(el=>el.className==='news-source-options');
  const radios=()=>groups.flatMap(group=>group.querySelectorAll('input'));
  assert.equal(radios().length,sources.length+1);
  assert.deepEqual(groups[0].querySelectorAll('input').map(el=>el.value),['','nasa','cnsa','cmse','esa']);
  const archived=groups[1].querySelectorAll('input').find(el=>el.value==='spacex');assert.ok(archived);
  archived.checked=true;archived.trigger('change');await flush();
  assert.ok(requests.some(url=>url.startsWith('/api/news?')&&new URLSearchParams(url.split('?')[1]).get('source')==='spacex'));
  assert.ok(groups[0].querySelectorAll('input').some(el=>el.value==='spacex'&&el.checked));
  assert.equal(radios().length,sources.length+1);
  assert.equal(registry.find(el=>el.className==='news-update-details').classList.contains('has-warning'),false);
  const linkRows=registry.filter(el=>el.className==='news-article');
  assert.equal(linkRows.at(-1).querySelectorAll('a').length,1);
  assert.equal(linkRows.at(-1).querySelectorAll('a')[0].href,'https://example.org/1');
  console.log('News progressive source filters retain inactive history, selection and original links');
}
(async()=>{await aiAvailability();await resourceCovers();await newsSources();})().catch(error=>{console.error(error);process.exitCode=1;});
