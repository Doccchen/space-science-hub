'use strict';
// An always reachable menu and UI switch replace permanent gallery chrome.
(() => {
  const page=document.getElementById('gallery'), dialog=document.getElementById('gallery-menu');
  const menu=document.getElementById('gallery-menu-toggle'), toggle=document.getElementById('gallery-ui-toggle');
  const details=document.getElementById('gallery-details-toggle'), tools=page.querySelector('.gallery-tools');
  const copy=page.querySelector('.gallery-copy'), provenance=page.querySelector('.gallery-provenance');
  const reduced=matchMedia('(prefers-reduced-motion: reduce)'), fine=matchMedia('(pointer: fine)');
  let timer=0, chrome=false, opener=null;
  function show(value) {
    clearTimeout(timer);chrome=value;page.classList.toggle('gallery-ui-hidden',!value);tools.inert=!value;
    toggle.setAttribute('aria-expanded',String(value));toggle.textContent=value?'收起界面 −':'显示界面 +';
  }
  function idle() {
    clearTimeout(timer);
    if(!chrome || reduced.matches || !fine.matches || dialog.open || page.classList.contains('gallery-details-open'))return;
    timer=setTimeout(()=>{
      if(!tools.contains(document.activeElement))show(false);
    },5000);
  }
  function information(value) {
    page.classList.toggle('gallery-details-open',value);copy.inert=!value;provenance.inert=!value;
    details.setAttribute('aria-expanded',String(value));details.textContent=value?'收起影像说明':'影像说明与出处';
  }
  function closeMenu(restore=true) {
    if(!dialog.open)return;dialog.close();menu.setAttribute('aria-expanded','false');
    if(restore)opener?.focus({preventScroll:true});
  }
  menu.addEventListener('click',()=>{
    if(page.classList.contains('gallery-viewing')){document.getElementById('gallery-exit').click();return;}
    opener=menu;dialog.showModal();menu.setAttribute('aria-expanded','true');
  });
  dialog.addEventListener('cancel',event=>{event.preventDefault();closeMenu();});
  document.getElementById('gallery-menu-close').addEventListener('click',()=>closeMenu());
  dialog.querySelectorAll('a[href]').forEach(link=>link.addEventListener('click',()=>closeMenu(false)));
  details.addEventListener('click',()=>{information(!page.classList.contains('gallery-details-open'));closeMenu();});
  document.getElementById('gallery-details-close').addEventListener('click',()=>{information(false);menu.focus({preventScroll:true});});
  document.getElementById('gallery-menu-index').addEventListener('click',()=>{closeMenu(false);show(true);document.querySelector('#gallery-index [aria-pressed=true]')?.focus({preventScroll:true});});
  document.getElementById('gallery-menu-replay').addEventListener('click',()=>{closeMenu(false);document.getElementById('gallery-replay').click();});
  toggle.addEventListener('click',()=>{show(!chrome);idle();});
  page.addEventListener('pointermove',event=>{if(event.pointerType==='mouse' && chrome)idle();});
  page.addEventListener('pointerdown',idle);
  document.addEventListener('galleryselected',()=>{page.classList.add('gallery-has-explored');idle();});
  document.addEventListener('galleryviewchange',event=>{
    information(false);show(false);menu.textContent=event.detail?'返回画廊 ×':'菜单 +';
    menu.setAttribute('aria-label',event.detail?'退出完整影像，返回画廊':'打开网站导航与影像菜单');
  });
  document.addEventListener('pagechange',()=>{closeMenu(false);information(false);show(false);});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(timer);});
  addEventListener('pagehide',()=>clearTimeout(timer));
  reduced.addEventListener('change',()=>{clearTimeout(timer);if(reduced.matches)show(true);});
  document.addEventListener('keydown',event=>{
    if(page.classList.contains('hidden') || dialog.open || document.getElementById('gallery-welcome').open)return;
    if(event.key==='Escape' && page.classList.contains('gallery-details-open'))information(false);
  });
  show(reduced.matches);information(false);
})();
