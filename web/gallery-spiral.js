'use strict';
// CSS perspective is the render layer. One world moves; photographs remain planes.
(() => {
  const stage = document.querySelector('.gallery-stage');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let camera, world, cards = [], steps = [], entries = [], choose, open;
  let selected=0, progress=0, radius=380, rise=130, frame=0, gesture=null, suppressClick=false;
  let wheel=0,lastWheel=0;
  const angle=60;
  function geometry() {
    const mobile=innerWidth<=700;
    const ratio=entries[selected]?.width/entries[selected]?.height || 1.6;
    document.getElementById('gallery').style.setProperty('--photo-ratio',String(ratio));
    const width=mobile?innerWidth*.88:Math.min(innerWidth*.70,innerHeight*.76*ratio);
    radius=width*1.08;
    rise=mobile?Math.min(150,innerHeight*.17):Math.min(220,innerHeight*.24);
    cards.forEach((card,i)=>{card.style.transform=`translate(-50%,-50%) rotateY(${i*angle}deg) translate3d(0,${-i*rise}px,${radius}px)`;});
    steps.forEach(({node,i})=>{node.style.transform=`translate(-50%,-50%) rotateY(${i*angle/6}deg) translate3d(0,${-i*rise/6+120}px,${radius*.67}px) rotateX(90deg)`;});
    render(progress);
  }
  function render(value) {
    progress=value;
    world.style.transform=`translateZ(${-radius}px) translateY(${value*rise}px) rotateY(${-value*angle}deg)`;
    cards.forEach((card,i)=>{
      const distance=i-value, visible=Math.abs(distance)<3.1 && Math.cos(distance*angle*Math.PI/180)>.05;
      card.hidden=!visible; card.inert=!visible;
      card.style.opacity=visible?String(Math.max(.2,1-Math.abs(distance)*.22)):'0';
      card.setAttribute('aria-pressed',String(i===selected));
      card.classList.toggle('is-selected',i===selected);
      card.setAttribute('aria-label','第 '+(i+1)+' 张：'+entries[i].label+'，点击'+(i===selected?'查看完整影像':'前往该展位'));
    });
    steps.forEach(({node,i})=>{node.hidden=Math.abs(i/6-value)>3.8;});
  }
  function select(value, prepared, immediate=false) {
    immediate=immediate || Math.abs(value-selected)>2 || reduced.matches;
    selected=value;
    geometry();
    if (prepared) {
      const image=prepared.cloneNode(true);image.className='spiral-card-photo';
      cards[value].querySelector('picture,img')?.replaceWith(image);
    }
    if(immediate)world.classList.add('is-immediate');
    render(value);
    if(immediate)requestAnimationFrame(()=>world?.classList.remove('is-immediate'));
    document.getElementById('gallery-level').textContent='LEVEL '+String(value+1).padStart(2,'0');
  }
  function mount(slides, onChoose, onOpen) {
    entries=slides;choose=onChoose;open=onOpen;
    camera=document.createElement('div');camera.className='spiral-camera';
    world=document.createElement('div');world.className='spiral-world';camera.append(world);
    const axis=document.createElement('div');axis.className='spiral-axis';axis.setAttribute('aria-hidden','true');world.append(axis);
    for(let i=-18;i<slides.length*6+18;i++){
      const node=document.createElement('span');node.className='spiral-step';node.setAttribute('aria-hidden','true');world.append(node);steps.push({node,i});
    }
    slides.forEach((slide,i)=>{
      const card=document.createElement('button');card.className='spiral-card';card.type='button';
      card.dataset.index=i;
      card.style.setProperty('--photo-ratio',String(slide.width/slide.height));
      card.style.setProperty('--mobile-focus',slide.object_position_mobile || '50% 50%');
      card.setAttribute('aria-label','第 '+(i+1)+' 张：'+slide.label+'，点击'+(i===selected?'查看完整影像':'前往该展位'));
      const photo=new Image();photo.src=slide.thumbnail;photo.alt=slide.alt;photo.width=320;photo.height=Math.round(320*slide.height/slide.width);photo.draggable=false;
      const caption=document.createElement('span');caption.className='spiral-card-caption';
      const label=document.createElement('span');label.textContent=String(i+1).padStart(2,'0')+' / '+slide.label;
      const cue=document.createElement('span');cue.className='spiral-card-cue';cue.textContent='查看全图 ↗';
      caption.append(label,cue);card.append(photo,caption);
      card.addEventListener('click',()=>i===selected?open():choose(i));
      world.append(card);cards.push(card);
    });
    stage.prepend(camera);geometry();
    stage.addEventListener('pointerdown',event=>{
      if(document.getElementById('gallery').classList.contains('gallery-viewing') || event.button!==0) return;
      gesture={id:event.pointerId,x:event.clientX,y:event.clientY,start:progress,dragging:false};
    });
    stage.addEventListener('pointermove',event=>{
      if(!gesture || event.pointerId!==gesture.id || reduced.matches) return;
      const dx=event.clientX-gesture.x,dy=event.clientY-gesture.y;
      if(!gesture.dragging && Math.abs(dx)<8) return;
      if(!gesture.dragging && Math.abs(dy)>Math.abs(dx)*1.2){gesture=null;return;}
      gesture.dragging=true;world.classList.add('is-dragging');stage.classList.add('is-dragging');
      try{stage.setPointerCapture(event.pointerId);}catch{}
      const value=Math.max(0,Math.min(entries.length-1,gesture.start-dx/(innerWidth<=700?105:160)));
      cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{frame=0;render(value);});
    });
    function release(event,cancelled=false) {
      if(!gesture || event.pointerId!==gesture.id)return;
      const dragged=gesture.dragging;
      cancelAnimationFrame(frame);frame=0;
      const dx=event.clientX-gesture.x;
      const target=Math.round(Math.max(0,Math.min(entries.length-1,gesture.start-dx/(innerWidth<=700?105:160))));
      gesture=null;world.classList.remove('is-dragging');stage.classList.remove('is-dragging');
      if(dragged){suppressClick=true;setTimeout(()=>{suppressClick=false;},0);render(selected);if(!cancelled)choose(target);}
      else if(reduced.matches && event.pointerType==='touch' && Math.abs(dx)>55)choose(Math.max(0,Math.min(entries.length-1,selected+(dx<0?1:-1))));
    }
    stage.addEventListener('pointerup',event=>release(event));
    stage.addEventListener('pointercancel',event=>release(event,true));
    stage.addEventListener('click',event=>{if(suppressClick){event.preventDefault();event.stopImmediatePropagation();}},true);
    stage.addEventListener('wheel',event=>{
      if(event.ctrlKey || document.getElementById('gallery').classList.contains('gallery-viewing') || document.getElementById('gallery').classList.contains('hidden'))return;
      const delta=(Math.abs(event.deltaY)>=Math.abs(event.deltaX)?event.deltaY:event.deltaX)*(event.deltaMode===1?16:event.deltaMode===2?innerHeight:1);
      if(!delta)return;event.preventDefault();
      const now=performance.now();if(now-lastWheel>500)wheel=0;
      if(now-lastWheel<320)return;
      wheel+=delta;
      if(Math.abs(wheel)<65)return;
      const next=Math.max(0,Math.min(entries.length-1,selected+(wheel>0?1:-1)));
      wheel=0;lastWheel=now;if(next!==selected)choose(next);
    },{passive:false});
    addEventListener('resize',geometry);
    reduced.addEventListener('change',()=>{stop();geometry();});
  }
  function stop() {
    cancelAnimationFrame(frame);frame=0;gesture=null;
    if(!world)return;
    world.classList.remove('is-dragging');stage.classList.remove('is-dragging');select(selected,null,true);
  }
  window.GallerySpiral={mount,select,stop};
  // Read-only geometric evidence for real input tests; no perpetual clock.
  window.galleryScene={snapshot:()=>({selected,progress,frame,angle,rise,radius,
    transform:world?.style.transform,visible:cards.filter(card=>!card.hidden).length,
    steps:steps.filter(step=>!step.node.hidden).length,dragging:!!gesture?.dragging})};
})();
