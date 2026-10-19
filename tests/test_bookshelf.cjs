const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element{
 constructor(tag){this.tagName=tag;this.children=[];this.events={};this.attributes={};this.dataset={};this.classList={add(){}};this.textContent='';this.isConnected=true;this.style={setProperty(k,v){this[k]=v;}};this.open=false;}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=nodes;}
 setAttribute(k,v){this.attributes[k]=v;}
 addEventListener(k,v){this.events[k]=v;}
 focus(){document.activeElement=this;}
 showModal(){this.open=true;}
 close(){this.open=false;}
 remove(){this.removed=true;}
 fire(k,e={}){this.events[k]?.(e);}
}
const body=new Element('body'),search=new Element('input');
const document={body,activeElement:search,createElement:t=>new Element(t),getElementById:id=>id==='search'?search:null};
const listeners={},location={href:'https://zhihang.example/assets/resource-navigation.html'},stack=[location.href];
const history={pushState(s,t,u){stack.push(String(u));location.href=String(u)},replaceState(s,t,u){location.href=String(u);stack[stack.length-1]=location.href},back(){if(stack.length>1)stack.pop();location.href=stack.at(-1);listeners.popstate?.();}};
const window={addEventListener(k,v){listeners[k]=v;}};
const context=vm.createContext({window,document,location,history,URL,requestAnimationFrame:f=>f()});
vm.runInContext(fs.readFileSync('web/professional-books.js','utf8'),context);
vm.runInContext(fs.readFileSync('web/bookshelf.js','utf8'),context);
assert.equal(window.ZhihangBooks.length,27);
const find=(n,tag)=>n.tagName===tag?n:n.children.map(c=>find(c,tag)).find(Boolean);
for(const book of window.ZhihangBooks){
 const slot=window.ZhihangShelf.book(book),button=slot.children[0];
 assert.equal(button.attributes['aria-label'],'查看《'+book.name+'》图书详情');
 button.fire('click');const dialog=body.children[0];assert(dialog.open);
 assert.equal(find(dialog,'h2').textContent,book.name);
 assert.equal(new URL(location.href).searchParams.get('book'),book.id);
 dialog.children[0].fire('click');assert(!dialog.open);assert.equal(document.activeElement,button);
 assert.equal(new URL(location.href).searchParams.get('book'),null);
}
console.log('27 real book titles, correct details/deep links and close/focus restoration passed.');
