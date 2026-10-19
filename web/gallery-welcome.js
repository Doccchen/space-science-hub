'use strict';
(() => {
  const dialog=document.getElementById('gallery-welcome'), page=document.getElementById('gallery');
  const key='zhihang.gallery.welcome.seen', preference=matchMedia('(prefers-reduced-motion: reduce)');
  let seen=false, storage=true, timer=0, animation=null, prior=null;
  try { seen=localStorage.getItem(key)==='true'; localStorage.setItem(key+'.probe','1'); localStorage.removeItem(key+'.probe'); }
  catch { storage=false; }
  function finish(record=false) {
    clearTimeout(timer); animation?.cancel(); animation=null;
    if (record) { seen=true; try { localStorage.setItem(key,'true'); } catch { storage=false; } }
    if (dialog.open) { dialog.close(); if (!page.classList.contains('hidden')) prior?.focus({preventScroll:true}); }
  }
  function play(force=false) {
    if (document.hidden || page.classList.contains('hidden') || dialog.open || preference.matches || (!force && (seen || !storage))) return;
    prior=document.activeElement; dialog.showModal();
    // Hard deadline also covers failed image requests and animation exceptions.
    timer=setTimeout(() => finish(true), 2400);
    try {
      animation=dialog.querySelector('.welcome-mark').animate(
        [{opacity:0,transform:'scale(.94)'},{opacity:1,transform:'scale(1)',offset:.35},{opacity:1,transform:'scale(1)',offset:.8},{opacity:0,transform:'scale(1.04)'}],
        {duration:2100,easing:'ease-in-out'});
      animation.finished.then(() => finish(true), () => {});
    } catch { finish(false); }
  }
  document.getElementById('gallery-skip').addEventListener('click', () => finish(true));
  dialog.addEventListener('cancel', event => { event.preventDefault(); finish(true); });
  document.getElementById('gallery-replay').addEventListener('click', () => play(true));
  document.addEventListener('pagechange', () => { if (page.classList.contains('hidden')) finish(false); else play(); });
  document.addEventListener('galleryfailed', () => finish(false));
  preference.addEventListener('change', () => { if (preference.matches) finish(false); });
  addEventListener('storage', event => { if (event.key===key && event.newValue==='true') seen=true; });
  addEventListener('pagehide', () => finish(false));
  document.addEventListener('visibilitychange', () => { if (document.hidden) finish(false); else play(); });
  play();
})();
