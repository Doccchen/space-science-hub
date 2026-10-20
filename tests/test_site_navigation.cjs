const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(initial=''){
 const events=[],scrolls=[],pushes=[],replacements=[];let fragment=initial;
 const cl=(initial=[])=>{const set=new Set(initial);return{contains:x=>set.has(x),toggle(x,on){on?set.add(x):set.delete(x)}}};
 const pages=['news','home','about','library'].map(id=>({id,classList:cl(id==='news'?['page']:['page','hidden'])}));
 const link=page=>({dataset:{page},classList:cl(),attributes:{},handlers:{},setAttribute(k,v){this.attributes[k]=v},removeAttribute(k){delete this.attributes[k]},addEventListener(k,f){this.handlers[k]=f}});
 const nodes=['news','home','about','library'].map(link),brand={addEventListener(k,f){this[k]=f}};
 const location={href:'https://zhihang.example/'};Object.defineProperty(location,'hash',{get:()=>fragment,set(){throw Error('Native fragment navigation must not be used')}});
 const history={state:{kept:true},replaceState(s,t,u){this.state=s;fragment=u;replacements.push(u)},pushState(s,t,u){this.state=s;fragment=u;pushes.push(u)}};
 const document={getElementById:id=>id==='home-link'?brand:pages.find(x=>x.id===id),querySelectorAll:s=>s==='.page'?pages:nodes,dispatchEvent:e=>events.push(e)};
 const context={document,location,history,window:{scrollTo(...v){scrolls.push(v)}},CustomEvent:class{constructor(type,data){this.type=type;Object.assign(this,data)}}};
 vm.createContext(context);vm.runInContext(fs.readFileSync('web/studio.js','utf8'),context);
 return{context,pages,nodes,brand,scrolls,pushes,replacements,events,location,history};
}
const old=setup('#home');assert.deepEqual(old.replacements,['#page/home']);assert.equal(old.history.state.kept,true);
assert.equal(vm.runInContext('navigationPage()',old.context),'home');
let prevented=false;old.nodes[1].handlers.click({preventDefault(){prevented=true}});
assert(prevented);assert.equal(old.pages[1].classList.contains('hidden'),false);assert.equal(old.nodes[1].attributes['aria-current'],'page');assert.deepEqual(old.scrolls,[]);
old.nodes[2].handlers.click({preventDefault(){}});assert.deepEqual(old.pushes,['#page/about']);assert.equal(old.nodes[1].attributes['aria-current'],undefined);
old.nodes[0].handlers.click({preventDefault(){}});assert.equal(old.location.hash,'#page/news');assert.deepEqual(old.scrolls,[]);
const visible=old.pages.map(p=>p.classList.contains('hidden'));
old.nodes[3].handlers.click({preventDefault(){}});assert.equal(old.location.href,'/assets/resource-navigation.html');assert.deepEqual(old.pages.map(p=>p.classList.contains('hidden')),visible);
for(const hash of ['#page/news','#page/home','#page/about','#news','#home','#about']){const s=setup(hash);assert(['news','home','about'].includes(vm.runInContext('navigationPage()',s.context)));assert.deepEqual(s.scrolls,[])}
const headers=['web/index.html','web/resource-navigation.html','reader_web/index.html'].map(n=>fs.readFileSync(n,'utf8').match(/<header class="site-header">[\s\S]*?<\/header>/)[0]);
for(const h of headers){for(const text of ['航天新闻','研究助手','资源导航','关于本站','brand-wordmark'])assert(h.includes(text));for(const url of ['/#page/news','/assets/research.html','/assets/resource-navigation.html','/#page/about'])assert(h.includes('href="'+url+'"'))}
const normalize=h=>h.replace(/ data-page="[^"]+"/g,'').replace(/ class="active" aria-current="page"/g,'');assert.equal(normalize(headers[0]),normalize(headers[1]));assert.equal(normalize(headers[0]),normalize(headers[2]));
const motion=fs.readFileSync('web/site-motion.js','utf8');assert(!motion.includes('pageAnimation'));assert(!motion.includes('motion-nav-rule'));
console.log('Navigation: identical headers, logical routes, legacy links, active/ARIA state and no automatic scrolling passed.');
