'use strict';
(() => {
 const section=document.querySelector('.featured-gallery'),data=document.getElementById('history-slides');
 if(!section||!data)return;
 let slides;try{slides=JSON.parse(data.textContent)}catch{return;}
 if(!Array.isArray(slides)||!slides.length)return;
 const grid=document.getElementById('image-thumbnails'),toggle=document.getElementById('image-gallery-toggle');
 const hero=section.querySelector('.cover-open'),heroImage=section.querySelector('.space-cover-image');
 const viewer=document.getElementById('cover-lightbox'),image=document.getElementById('cover-lightbox-image');
 const close=document.getElementById('cover-lightbox-close'),original=document.getElementById('cover-lightbox-original');
 const source=document.getElementById('gallery-viewer-source'),credit=document.getElementById('gallery-viewer-credit'),license=document.getElementById('gallery-viewer-license');
 const status=document.getElementById('gallery-viewer-status'),retry=document.getElementById('gallery-viewer-retry');
 const prev=document.getElementById('gallery-viewer-prev'),next=document.getElementById('gallery-viewer-next');
 if(!grid||!toggle||!hero||!viewer||!image||!close)return;
 const featured=Math.max(0,slides.findIndex(s=>s.id==='landspace-horizon'));
 const compact=slides.map((_,i)=>i).filter(i=>i!==featured).slice(0,6);
 let expanded=false,current=featured,request=0,deadline,returnTo=hero,overflow='';
 const safe=url=>{try{const u=new URL(url,location.href);return ['https:','http:'].includes(u.protocol)&&!u.username&&!u.password?u.href:''}catch{return ''}};
 function sources(slide){
  const small=typeof innerWidth==='number'&&innerWidth<=760;
  return [...new Set((small?[slide.mobile_image,slide.image,slide.fallback_image,slide.mobile_fallback_image]:[slide.image,slide.mobile_image,slide.fallback_image,slide.mobile_fallback_image]).filter(Boolean))];
 }
 function load(){
  clearTimeout(deadline);const version=++request,urls=sources(slides[current]);
  status.textContent='正在加载图片…';status.hidden=false;retry.hidden=true;
  function attempt(i){
   if(version!==request||!viewer.open)return;
   if(i>=urls.length){status.textContent='图片暂时无法加载，可点击重试。';retry.hidden=false;return;}
   const candidate=new Image();let settled=false;candidate.decoding='async';
   const failed=()=>{if(settled||version!==request)return;settled=true;clearTimeout(deadline);candidate.onload=candidate.onerror=null;candidate.src='';attempt(i+1);};
   candidate.onload=()=>{if(settled||version!==request||!viewer.open)return;settled=true;clearTimeout(deadline);image.src=urls[i];image.hidden=false;status.hidden=true;};
   candidate.onerror=failed;deadline=setTimeout(failed,7000);candidate.src=urls[i];
  }
  attempt(0);
 }
 function display(index,placeholder){
  current=(index+slides.length)%slides.length;const s=slides[current];
  image.alt=s.alt;image.hidden=!placeholder;if(placeholder)image.src=placeholder;
  viewer.setAttribute('aria-label','完整图片：'+s.label);
  source.href=safe(s.source_url);credit.textContent=[s.date,s.credit].filter(Boolean).join(' / ');
  license.href=safe(s.license_url);license.textContent=s.license;
  original.href=safe(s.fallback_image||s.image);load();
 }
 function open(index,trigger,placeholder){
  returnTo=trigger||document.activeElement;overflow=document.body.style.overflow;document.body.style.overflow='hidden';
  viewer.showModal();display(index,placeholder);close.focus({preventScroll:true});
 }
 function draw(){
  grid.replaceChildren();grid.classList.toggle('is-expanded',expanded);
  const indices=expanded?slides.map((_,i)=>i):compact;
  indices.forEach(i=>{
   const s=slides[i],button=document.createElement('button'),thumb=document.createElement('img');
   button.type='button';button.className='gallery-thumb';button.setAttribute('aria-label','查看大图：'+s.label);button.setAttribute('aria-haspopup','dialog');
   thumb.src=s.thumbnail||s.mobile_image||s.image;thumb.alt='';thumb.width=s.width;thumb.height=s.height;thumb.loading='lazy';thumb.decoding='async';
   let fallback=false;
   thumb.addEventListener('error',()=>{if(!fallback){fallback=true;thumb.src=s.mobile_fallback_image||s.fallback_image||s.image;}else{button.classList.add('thumbnail-unavailable');thumb.hidden=true;const hint=document.createElement('span');hint.textContent='点击查看图片';button.append(hint);}});
   button.append(thumb);button.addEventListener('click',()=>open(i,button,thumb.complete&&thumb.naturalWidth?thumb.currentSrc||thumb.src:''));grid.append(button);
  });
  toggle.setAttribute('aria-expanded',String(expanded));toggle.textContent=expanded?'收起影像':'查看全部影像（'+slides.length+'）';
 }
 toggle.addEventListener('click',()=>{expanded=!expanded;draw();});
 hero.addEventListener('click',()=>open(featured,hero,heroImage.currentSrc||heroImage.src));
 close.addEventListener('click',()=>viewer.close());
 viewer.addEventListener('click',event=>{if(event.target===viewer)viewer.close();});
 viewer.addEventListener('close',()=>{request++;clearTimeout(deadline);document.body.style.overflow=overflow;returnTo?.focus({preventScroll:true});});
 retry.addEventListener('click',load);prev.addEventListener('click',()=>display(current-1));next.addEventListener('click',()=>display(current+1));
 viewer.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();display(current+(event.key==='ArrowLeft'?-1:1));}});
 document.addEventListener('pagechange',event=>{if(event.detail!=='news'&&viewer.open)viewer.close();});
 let heroFallback=0;heroImage.addEventListener('error',()=>{const urls=sources(slides[featured]);if(heroFallback<urls.length){heroImage.removeAttribute('srcset');heroImage.src=urls[heroFallback++];}});
 draw();
})();
