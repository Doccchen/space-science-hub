/* Observable carousel behavior: matching attribution, async races, errors and pause conditions. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{
 constructor(){this.children=[];this.events={};this.dataset={};this.attrs={};this.style={};const names=new Set();this.classList={contains:name=>names.has(name),add:name=>names.add(name),remove:name=>names.delete(name)};}
 addEventListener(name,fn){this.events[name]=fn;} setAttribute(name,value){this.attrs[name]=value;}
 append(node){this.children.push(node);} replaceChildren(){this.children=[];}
 contains(node){return node===this;} closest(){return true;}
 trigger(name,event={}){this.events[name]?.(event);}
 querySelector(){return this.children[0];}
 cloneNode(){const copy=new Element();copy.dataset={...this.dataset};copy.style={...this.style};copy.src=this.src;copy.alt=this.alt;copy.children=this.children.map(child=>child.cloneNode());return copy;}
 remove(){this.removed=true;}
 animate(frames,options){const finished={then(fn){this.complete=fn;return this;},catch(){return this;}};this.animation={frames,options,finished,cancel(){}};return this.animation;}
}
const slides=JSON.parse(fs.readFileSync(path.join(__dirname,'../web/history-slides.json'),'utf8'));
const ids=Object.fromEntries(['history-slides','space-cover-title','cover-label','cover-description','cover-source','cover-credit','cover-license','cover-announcement','cover-dots','cover-controls','news'].map(id=>[id,new Element()]));
ids['history-slides'].textContent=JSON.stringify(slides);
const cover=new Element(),image=new Element(),visual=new Element(),copy=new Element(),events={},timers=new Map(),pending=[];let timerId=0;
visual.append(image);cover.querySelector=selector=>selector==='.cover-visual'?visual:selector==='.space-cover-copy'?copy:image;
cover.insertBefore=node=>cover.append(node);
const motion={matches:false,addEventListener(name,fn){this.change=fn;}};
const document={hidden:false,activeElement:null,getElementById:id=>ids[id],querySelector:()=>cover,
 createElement:()=>new Element(),createTextNode:text=>({text}),addEventListener:(name,fn)=>events[name]=fn};
const context={document,URL,matchMedia:()=>motion,Image:class{constructor(){pending.push(this);}},
 setTimeout(fn,ms){const id=++timerId;timers.set(id,{fn,ms});return id;},clearTimeout(id){timers.delete(id);}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/history-carousel.js'),'utf8'),context);
const autoTimers=()=>[...timers.values()].filter(t=>t.ms===8000);
assert.equal(autoTimers().length,1);
ids['cover-dots'].children[1].trigger('click');assert.equal(image.src,slides[0].image);assert.equal(autoTimers().length,0);
pending.at(-1).onload();assert.equal(image.src,slides[1].image);assert.equal(ids['cover-credit'].textContent,slides[1].date+' / '+slides[1].credit);
assert.equal(ids['cover-license'].href,slides[1].license_url);
const fading=cover.children.at(-1);assert.equal(fading.dataset.slide,'earthrise');assert.equal(fading.children[0].src,slides[0].image);
assert.equal(fading.animation.options.duration,750);assert.equal(fading.removed,undefined);
fading.animation.finished.complete();assert.equal(fading.removed,true);
// A slower previous request cannot overwrite a more recently selected image or its license.
ids['cover-dots'].children[2].trigger('click');const stale=pending.at(-1);
ids['cover-dots'].children[3].trigger('click');pending.at(-1).onload();stale.onload();
assert.equal(image.src,slides[3].image);assert.equal(ids['cover-license'].textContent,'CC BY-SA 4.0');
// Failed candidates leave the visible photo, description and attribution untouched.
ids['cover-dots'].children[4].trigger('click');pending.at(-1).onerror();
assert.equal(image.src,slides[3].image);assert.equal(ids['cover-credit'].textContent,slides[3].date+' / '+slides[3].credit);
assert.equal(ids['cover-dots'].children[4].disabled,true);
// If a timed request is already loading when the pointer enters, it must not change the image.
autoTimers()[0].fn();const hoveringRequest=pending.at(-1);
cover.trigger('mouseenter');assert.equal(autoTimers().length,0);hoveringRequest.onload();assert.equal(image.src,slides[3].image);
cover.trigger('mouseleave');assert.equal(autoTimers().length,1);
cover.trigger('focusin',{target:{matches:()=>false}});cover.trigger('mouseleave');assert.equal(autoTimers().length,1);
cover.trigger('focusin');assert.equal(autoTimers().length,0);
document.activeElement=null;cover.trigger('focusout');[...timers.values()].find(t=>t.ms===0).fn();assert.equal(autoTimers().length,1);
document.hidden=true;events.visibilitychange();assert.equal(autoTimers().length,0);
document.hidden=false;events.visibilitychange();assert.equal(autoTimers().length,1);
// Navigating away invalidates an outstanding image load, then resumes on returning.
ids['cover-dots'].children[2].trigger('click');const leaving=pending.at(-1);events.pagechange({detail:'library'});leaving.onload();
assert.equal(image.src,slides[3].image);assert.equal(autoTimers().length,0);
events.pagechange({detail:'news'});assert.equal(autoTimers().length,1);
motion.matches=true;motion.change();assert.equal(autoTimers().length,0);
motion.matches=false;motion.change();assert.equal(autoTimers().length,1);
console.log('Carousel attribution/race/error and hover/focus/manual/visibility/page/reduced-motion regressions passed.');
