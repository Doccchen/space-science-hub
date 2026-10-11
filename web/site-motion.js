'use strict';
(() => {
 const preference=matchMedia('(prefers-reduced-motion: reduce)');
 const entered=new WeakSet(),messages=new WeakSet(),details=new WeakSet(),dialogs=new WeakMap();
 let frame=0,scanFrame=0,lastPage='',pageAnimation=null;
 document.body.classList.add('site-motion');
 const nav=document.querySelector('header nav'),marker=document.createElement('span');marker.className='motion-nav-rule';nav.append(marker);
 const animate=(node,keyframes,duration)=>{if(!preference.matches&&node&&typeof node.animate==='function')return node.animate(keyframes,{duration,easing:'cubic-bezier(.16,1,.3,1)'});return null;};
 const observer=new IntersectionObserver(entries=>{
  for(const entry of entries)if(entry.isIntersecting){
   entry.target.classList.add('motion-seen');observer.unobserve(entry.target);
   if(entry.target.matches('.about-section'))animate(entry.target.querySelector('h2'),[{opacity:.75,transform:'translateY(5px)'},{opacity:1,transform:'translateY(0)'}],360);
  }
 },{threshold:.12});
 function watch(node){if(entered.has(node))return;entered.add(node);if(preference.matches)node.classList.add('motion-seen');else observer.observe(node);}
 function scan(){
  scanFrame=0;
  document.querySelectorAll('#news .news-article,#about .about-section').forEach(watch);
  document.querySelectorAll('#home .ai-message').forEach(node=>{
   if(messages.has(node))return;messages.add(node);
   animate(node,node.dataset.role==='user'?[{opacity:.8,transform:'translateX(8px)'},{opacity:1,transform:'translateX(0)'}]:[{opacity:.85,transform:'translateY(7px)'},{opacity:1,transform:'translateY(0)'}],node.dataset.role==='user'?200:320);
  });
  document.querySelectorAll('#home .ai-sources').forEach(node=>{
   if(details.has(node))return;details.add(node);
   node.addEventListener('toggle',()=>{if(node.open)animate(node.querySelector('.ai-source-list'),[{opacity:.75,transform:'translateY(3px)'},{opacity:1,transform:'translateY(0)'}],220)});
  });
  document.querySelectorAll('dialog.news-reader').forEach(dialog=>{
   const wasOpen=dialogs.get(dialog);if(dialog.open&&!wasOpen)animate(dialog,[{opacity:.88,transform:'translateY(9px)'},{opacity:1,transform:'translateY(0)'}],280);
   dialogs.set(dialog,dialog.open);
  });
 }
 function queueScan(){if(!scanFrame)scanFrame=requestAnimationFrame(scan);}
 function update(){
  frame=0;const active=nav.querySelector('.active'),rect=active?.getBoundingClientRect(),navRect=nav.getBoundingClientRect();
  const cover=document.querySelector('#news:not(.hidden) .space-cover'),coverRect=cover?.getBoundingClientRect();
  const drift=coverRect&&!preference.matches&&innerWidth>700?Math.max(0,Math.min(1,-coverRect.top/Math.max(1,coverRect.height)))*12:0;
  if(rect)marker.style.transform='translate3d('+(rect.left-navRect.left)+'px,0,0)';
  cover?.style.setProperty('--cover-drift',drift+'px');
 }
 function queue(){if(!frame)frame=requestAnimationFrame(update);}
 function pageChanged(event){
  const page=event?.detail||document.querySelector('main.page:not(.hidden)')?.id;
  if(page==='library'){location.href='/assets/resource-navigation.html';return;}
  if(page&&page!==lastPage){
   pageAnimation?.cancel();const main=document.getElementById(page);
   pageAnimation=animate(main,[{opacity:.92,transform:'translateY(4px)'},{opacity:1,transform:'translateY(0)'}],240);
   if(page==='news')animate(document.getElementById('space-cover-title'),[{clipPath:'inset(0 0 10% 0)',transform:'translateY(6px)'},{clipPath:'inset(0)',transform:'translateY(0)'}],500);
   lastPage=page;
  }
  document.querySelectorAll('#about .about-section').forEach(watch);queueScan();queue();
 }
 document.addEventListener('pagechange',pageChanged);
 // Snapshot navigation keeps existing routes; resource navigation uses its approved standalone page.
 document.addEventListener('click',event=>{const button=event.target.closest('[data-page="library"]');if(button){event.preventDefault();event.stopImmediatePropagation();location.href='/assets/resource-navigation.html'}},true);
 new MutationObserver(queueScan).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['open','data-ai-available']});
 addEventListener('scroll',queue,{passive:true});addEventListener('resize',queue,{passive:true});
 preference.addEventListener('change',()=>{pageAnimation?.cancel();document.querySelectorAll('.news-article,.about-section').forEach(n=>n.classList.add('motion-seen'));queue()});
 pageChanged();document.fonts?.ready.then(queue);
})();
