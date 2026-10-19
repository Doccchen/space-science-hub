const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element{
 constructor(){this.children=[];this.events={};this.attrs={};this.style={};this.open=false;this.hidden=false;this.src='';this.complete=false;this.naturalWidth=0;const names=new Set();this.classList={add:n=>names.add(n),contains:n=>names.has(n),toggle(n,on){on?names.add(n):names.delete(n)}};}
 append(n){this.children.push(n)}replaceChildren(...n){this.children=n}addEventListener(n,f){this.events[n]=f}setAttribute(n,v){this.attrs[n]=v}removeAttribute(n){delete this.attrs[n]}
 fire(n,e={}){this.events[n]?.(e)}showModal(){this.open=true}close(){this.open=false;this.fire('close')}focus(){document.activeElement=this}
}
const markup=fs.readFileSync('web/index.html','utf8'),slides=JSON.parse(markup.match(/<script[^>]*id="history-slides"[^>]*>([\s\S]*?)<\/script>/)[1]);
const ids=Object.fromEntries(['history-slides','image-thumbnails','image-gallery-toggle','cover-lightbox','cover-lightbox-image','cover-lightbox-close','cover-lightbox-original','gallery-viewer-source','gallery-viewer-credit','gallery-viewer-license','gallery-viewer-status','gallery-viewer-retry','gallery-viewer-prev','gallery-viewer-next'].map(n=>[n,new Element()]));ids['history-slides'].textContent=JSON.stringify(slides);
const section=new Element(),hero=new Element(),heroImage=new Element(),pending=[],timers=new Map(),events={};let timerId=0;
heroImage.src=slides[6].image;section.querySelector=s=>s==='.cover-open'?hero:heroImage;
const document={body:{style:{overflow:''}},activeElement:null,getElementById:id=>ids[id],querySelector:()=>section,createElement:()=>new Element(),addEventListener:(n,f)=>events[n]=f};
vm.runInNewContext(fs.readFileSync('web/space-gallery.js','utf8'),{document,URL,location:{href:'https://zhihang.example/'},Image:class{constructor(){pending.push(this)}},setTimeout(f,ms){const id=++timerId;timers.set(id,{f,ms});return id},clearTimeout:id=>timers.delete(id)});
const grid=ids['image-thumbnails'];assert.equal(grid.children.length,6);assert.equal(pending.length,0);assert.equal(timers.size,0,'The gallery must not start autoplay timers');
ids['image-gallery-toggle'].fire('click');assert.equal(grid.children.length,12);assert.equal(ids['image-gallery-toggle'].attrs['aria-expanded'],'true');assert(grid.classList.contains('is-expanded'));
ids['image-gallery-toggle'].fire('click');assert.equal(grid.children.length,6);assert.equal(ids['image-gallery-toggle'].attrs['aria-expanded'],'false');
const trigger=grid.children[0],thumb=trigger.children[0];thumb.complete=true;thumb.naturalWidth=320;trigger.fire('click');assert(ids['cover-lightbox'].open);assert.equal(document.body.style.overflow,'hidden');assert.equal(ids['cover-lightbox-image'].src,thumb.src);
const stale=pending.at(-1);ids['gallery-viewer-next'].fire('click');const newer=pending.at(-1);stale.onload();assert.equal(ids['cover-lightbox-image'].hidden,true);
newer.onerror();const fallback=pending.at(-1);assert.notEqual(fallback.src,newer.src);fallback.onload();assert.equal(ids['cover-lightbox-image'].hidden,false);assert.equal(ids['cover-lightbox-image'].src,slides[1].mobile_image);assert.equal(ids['gallery-viewer-credit'].textContent,[slides[1].date,slides[1].credit].filter(Boolean).join(' / '));
ids['gallery-viewer-next'].fire('click');const stalled=pending.at(-1);[...timers.values()][0].f();assert.notEqual(pending.at(-1),stalled);pending.at(-1).onload();
ids['cover-lightbox-close'].fire('click');assert(!ids['cover-lightbox'].open);assert.equal(document.activeElement,trigger);assert.equal(document.body.style.overflow,'');assert.equal(timers.size,0);
hero.fire('click');pending.at(-1).onload();assert.equal(ids['cover-lightbox-image'].src,slides[6].image);assert.equal(ids['cover-lightbox-original'].href,'https://zhihang.example'+slides[6].fallback_image);
events.pagechange({detail:'home'});assert(!ids['cover-lightbox'].open);assert.equal(timers.size,0);
assert(!markup.includes('/assets/history-carousel.js?'));assert(markup.includes('/assets/space-gallery.js?'));assert(!markup.includes('id="cover-dots"'));console.log('Gallery: fixed hero, 6/12 expansion, no autoplay, modal attribution/fallback/race/timeout and focus restoration passed.');
