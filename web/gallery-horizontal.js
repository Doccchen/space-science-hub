'use strict';
// A single photo, direct horizontal dragging, and short crossfades. No 3D scene.
(() => {
  const stage=document.querySelector('.gallery-stage'),page=document.getElementById('gallery');
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  let rail,entries=[],choose,open,current=null,selected=0,frame=0,gesture=null,offset=0,suppress=false,wheel=0,lastWheel=0;
  const animations=new Set();
  function drag(value){offset=value;if(rail)rail.style.transform=`translateX(${value}px)`;}
  function stop(){
    cancelAnimationFrame(frame);frame=0;gesture=null;drag(0);stage.classList.remove('is-dragging');
    animations.forEach(animation=>animation.cancel());animations.clear();
    rail?.querySelectorAll('.gallery-exhibit:not(.is-selected)').forEach(node=>node.remove());
  }
  function select(value,prepared,immediate=false){
    const previousIndex=selected;
    stop();selected=value;
    if(!prepared)return;
    const previous=current;
    current=document.createElement('button');current.type='button';current.className='gallery-exhibit is-selected';
    current.dataset.index=value;current.style.setProperty('--photo-ratio',String(entries[value].width/entries[value].height));
    current.style.setProperty('--mobile-focus',entries[value].object_position_mobile || '50% 50%');
    current.setAttribute('aria-label',entries[value].label+'，点击查看完整影像');
    const photo=prepared.cloneNode(true);photo.className='gallery-exhibit-photo';current.append(photo);
    current.addEventListener('click',open);rail.append(current);
    if(previous){previous.classList.remove('is-selected');previous.inert=true;previous.setAttribute('aria-hidden','true');}
    const next=(value-previousIndex+entries.length)%entries.length;
    const direction=next===1?1:next===entries.length-1?-1:0;
    if(!immediate && !reduced.matches && !document.hidden){
      const reveal=current.animate([{opacity:0,transform:`translate(-50%,-50%) translateX(${direction*24}px)`},{opacity:1,transform:'translate(-50%,-50%) translateX(0px)'}],{duration:480,easing:'cubic-bezier(.16,1,.3,1)'});
      animations.add(reveal);reveal.finished.then(()=>{animations.delete(reveal);previous?.remove();},()=>previous?.remove());
      if(previous){const fade=previous.animate([{opacity:1},{opacity:0}],{duration:320,easing:'ease-out'});animations.add(fade);fade.finished.then(()=>animations.delete(fade),()=>{});}
    }else previous?.remove();
  }
  function mount(slides,onChoose,onOpen){
    entries=slides;choose=onChoose;open=onOpen;page.dataset.galleryMode='horizontal';
    rail=document.createElement('div');rail.className='gallery-rail';stage.prepend(rail);
    stage.addEventListener('pointerdown',event=>{
      if(page.classList.contains('gallery-viewing') || event.button!==0)return;
      gesture={id:event.pointerId,x:event.clientX,y:event.clientY,dragging:false};
    });
    stage.addEventListener('pointermove',event=>{
      if(!gesture || event.pointerId!==gesture.id)return;
      const dx=event.clientX-gesture.x,dy=event.clientY-gesture.y;
      if(!gesture.dragging && Math.abs(dx)<8)return;
      if(!gesture.dragging && Math.abs(dy)>Math.abs(dx)*1.2){gesture=null;return;}
      gesture.dragging=true;stage.classList.add('is-dragging');
      try{stage.setPointerCapture(event.pointerId);}catch{}
      if(!reduced.matches){cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{frame=0;drag(Math.max(-180,Math.min(180,dx*.45)));});}
    });
    function release(event,cancelled=false){
      if(!gesture || event.pointerId!==gesture.id)return;
      const dx=event.clientX-gesture.x,dy=event.clientY-gesture.y,dragged=gesture.dragging;
      stop();
      if(dragged){suppress=true;setTimeout(()=>{suppress=false;},0);}
      if(!cancelled && Math.abs(dx)>55 && Math.abs(dx)>Math.abs(dy)*1.4)choose((selected+(dx<0?1:-1)+entries.length)%entries.length);
    }
    stage.addEventListener('pointerup',event=>release(event));stage.addEventListener('pointercancel',event=>release(event,true));
    stage.addEventListener('click',event=>{if(suppress){event.preventDefault();event.stopImmediatePropagation();}},true);
    stage.addEventListener('wheel',event=>{
      if(event.ctrlKey || page.classList.contains('gallery-viewing') || page.classList.contains('hidden'))return;
      const delta=(Math.abs(event.deltaX)>Math.abs(event.deltaY)?event.deltaX:event.deltaY)*(event.deltaMode===1?16:event.deltaMode===2?innerHeight:1);
      if(!delta)return;event.preventDefault();const now=performance.now();if(now-lastWheel>500)wheel=0;if(now-lastWheel<320)return;
      wheel+=delta;if(Math.abs(wheel)<65)return;lastWheel=now;choose((selected+(wheel>0?1:-1)+entries.length)%entries.length);wheel=0;
    },{passive:false});
    reduced.addEventListener('change',stop);
  }
  window.GalleryDisplay={mount,select,stop};
  window.galleryScene={snapshot:()=>({mode:'horizontal',selected,offset,frame,transform:rail?.style.transform || 'none',dragging:!!gesture?.dragging})};
})();
