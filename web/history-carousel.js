'use strict';
(() => {
 const cover=document.querySelector('.space-cover'), data=document.getElementById('history-slides');
 if(!cover||!data)return;
 let slides;
 try{slides=JSON.parse(data.textContent)}catch{return;}
 if(!Array.isArray(slides)||slides.length<2)return;
 const image=cover.querySelector('.space-cover-image'), title=document.getElementById('space-cover-title');
 const visual=cover.querySelector('.cover-visual'), copy=cover.querySelector('.space-cover-copy');
 const label=document.getElementById('cover-label'), description=document.getElementById('cover-description');
 const link=document.getElementById('cover-source'), credit=document.getElementById('cover-credit');
 const license=document.getElementById('cover-license');
 const count=document.getElementById('cover-count');
 const announce=document.getElementById('cover-announcement'), dots=document.getElementById('cover-dots');
 const motion=matchMedia('(prefers-reduced-motion: reduce)');
 let current=0, request=0, timer, hovering=false, focused=false, visible=true;
 let active=!document.getElementById('news').classList.contains('hidden'), loading=false;
 const failed=new Set(), buttons=[];
 let outgoing=null, fadeAnimation=null, copyAnimation=null;
 const safeLink=url=>{try{const u=new URL(url);return ['http:','https:'].includes(u.protocol)&&!u.username&&!u.password?u.href:null}catch{return null}};
 function canPlay(){return !hovering&&!focused&&visible&&active&&!document.hidden&&!motion.matches&&!loading&&slides.length-failed.size>1;}
 function schedule(){clearTimeout(timer);if(canPlay())timer=setTimeout(()=>move(1,false),8000);}
 function controls(){
  count.textContent=String(current+1).padStart(2,'0')+' / '+String(slides.length).padStart(2,'0');
  buttons.forEach((button,index)=>{button.setAttribute('aria-pressed',String(index===current));button.disabled=failed.has(index);});
  cover.setAttribute('aria-busy',String(loading));
 }
 function clearFade(){
  if(fadeAnimation)fadeAnimation.cancel();
  if(copyAnimation)copyAnimation.cancel();
  if(outgoing)outgoing.remove();
  outgoing=null;fadeAnimation=null;copyAnimation=null;
 }
 function render(index,manual){
  const blend=index!==current&&!motion.matches&&visual&&typeof visual.animate==='function';
  clearFade();
  if(blend){
   outgoing=visual.cloneNode(true);outgoing.classList.add('cover-visual-outgoing');outgoing.setAttribute('aria-hidden','true');
   outgoing.querySelector('.space-cover-image').alt='';cover.insertBefore(outgoing,visual);
  }
  const slide=slides[index];current=index;
  image.src=slide.image;image.alt=slide.alt;image.style.objectPosition=slide.position;cover.dataset.framing=slide.framing;cover.dataset.slide=slide.id;
  if(visual){visual.dataset.framing=slide.framing;visual.dataset.slide=slide.id;}
  title.replaceChildren();slide.title.forEach((line,i)=>{if(i)title.append(document.createElement('br'));title.append(document.createTextNode(line));});
  label.textContent=slide.label;label.previousElementSibling.textContent=String(index+1).padStart(2,'0');description.textContent=slide.description;
  link.href=safeLink(slide.source_url)||'#';credit.textContent=slide.date+' / '+slide.credit;
  license.textContent=slide.license;license.href=safeLink(slide.license_url)||'#';
  if(manual)announce.textContent='第 '+(index+1)+' 张，共 '+slides.length+' 张：'+slide.label;
  if(blend){
   const layer=outgoing;
   fadeAnimation=layer.animate([{opacity:1},{opacity:0}],{duration:750,easing:'cubic-bezier(.22,.61,.36,1)',fill:'forwards'});
   fadeAnimation.finished.then(()=>{layer.remove();if(outgoing===layer){outgoing=null;fadeAnimation=null;}}).catch(()=>{});
   if(copy&&typeof copy.animate==='function')copyAnimation=copy.animate([{opacity:0,transform:'translateY(6px)'},{opacity:1,transform:'translateY(0)'}],{duration:500,easing:'cubic-bezier(.22,.61,.36,1)'});
  }
  controls();schedule();
 }
 function show(index,manual=true){
  if(index===current&&!failed.has(index)){schedule();return;}
  const version=++request, candidate=new Image();loading=true;controls();clearTimeout(timer);
  candidate.onload=()=>{if(version!==request)return;loading=false;if(!manual&&!canPlay()){controls();schedule();return;}render(index,manual);};
  candidate.onerror=()=>{if(version!==request)return;loading=false;failed.add(index);announce.textContent='这张图像暂时无法显示，已保留当前影像。';controls();schedule();};
  candidate.src=slides[index].image;
 }
 function move(step,manual=true){
  let index=current;
  for(let i=0;i<slides.length;i++){index=(index+step+slides.length)%slides.length;if(!failed.has(index)&&index!==current){show(index,manual);return;}}
 }
 slides.forEach((slide,index)=>{const button=document.createElement('button');button.type='button';button.setAttribute('aria-label','显示第 '+(index+1)+' 张：'+slide.label);button.addEventListener('click',()=>show(index));dots.append(button);buttons.push(button);});
 cover.addEventListener('mouseenter',()=>{hovering=true;schedule();});cover.addEventListener('mouseleave',()=>{hovering=false;schedule();});
 cover.addEventListener('focusin',event=>{focused=event.target?.matches?.(':focus-visible')??true;schedule();});cover.addEventListener('focusout',()=>{setTimeout(()=>{focused=cover.contains(document.activeElement)&&(document.activeElement?.matches?.(':focus-visible')??true);schedule();},0);});
 cover.addEventListener('keydown',event=>{if(!event.target.closest('.cover-controls'))return;if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();move(event.key==='ArrowLeft'?-1:1);}});
 document.addEventListener('visibilitychange',schedule);
 document.addEventListener('pagechange',event=>{active=event.detail==='news';if(!active){request++;loading=false;clearFade();}controls();schedule();});
 motion.addEventListener('change',()=>{if(motion.matches)clearFade();controls();schedule();});
 if(typeof IntersectionObserver!=='undefined'){new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;schedule();},{threshold:.15}).observe(cover);}
 image.addEventListener('error',()=>{cover.classList.add('cover-image-error');});image.addEventListener('load',()=>cover.classList.remove('cover-image-error'));
 render(0,false);document.getElementById('cover-controls').hidden=false;
})();
