'use strict';
(() => {
  const page = document.getElementById('gallery');
  if (!page) return;
  const stage = page.querySelector('.gallery-stage'), copy = page.querySelector('.gallery-copy');
  const status = document.getElementById('gallery-status'), retry = document.getElementById('gallery-retry');
  const preference = matchMedia('(prefers-reduced-motion: reduce)'), fine = matchMedia('(pointer: fine)');
  const index = document.getElementById('gallery-index'), count = document.getElementById('gallery-count');
  const explore = document.getElementById('gallery-explore'), exit = document.getElementById('gallery-exit');
  const zoom = document.getElementById('gallery-zoom');
  let slides = [], current = -1, requested = 0, generation = 0, active = false;
  let frame = 0, picture = null, movement = null, gesture = null, panX = 0, panY = 0, enlarged = false;
  const imageAnimations = new Set();
  const cache = new Map();
  function announce(message, failed = false) {
    status.textContent = message; retry.hidden = !failed;
    page.classList.toggle('gallery-error', failed);
  }
  function resetMotion() {
    cancelAnimationFrame(frame); frame = 0;
    stage.style.setProperty('--drift-x', '0px'); stage.style.setProperty('--drift-y', '0px');
    for (const animation of imageAnimations) animation.cancel();
    imageAnimations.clear();
    page.querySelectorAll('.gallery-photo:not(.is-current)').forEach(node => node.remove());
  }
  function resetZoom() {
    enlarged = false; panX = panY = 0; page.classList.remove('gallery-zoomed');
    stage.style.setProperty('--pan-x', '0px'); stage.style.setProperty('--pan-y', '0px');
    zoom.textContent = '放大细节 +'; zoom.setAttribute('aria-pressed', 'false');
  }
  function viewing(value, focus = true) {
    resetMotion(); resetZoom();
    page.classList.toggle('gallery-viewing', value); document.body.classList.toggle('gallery-viewing', value);
    explore.setAttribute('aria-expanded', String(value)); exit.hidden = !value; zoom.hidden = !value;
    document.querySelector('body > header').inert = value;
    copy.inert = value; index.inert = value;
    if (focus) (value ? exit : explore).focus({preventScroll: true});
  }
  function loadImage(slide) {
    // Only adjacent images are prefetched, after the selected image succeeds.
    if (cache.has(slide.id)) return cache.get(slide.id);
    const task = new Promise((resolve, reject) => {
      const node = document.createElement('picture'); node.className = 'gallery-photo';
      const source = document.createElement('source'); source.type = 'image/webp';
      source.srcset = slide.mobile_image+' '+slide.variants[2].width+'w, '+slide.image+' '+slide.width+'w'; source.sizes = '100vw';
      const image = new Image(); image.alt = slide.alt; image.width = slide.width; image.height = slide.height;
      image.decoding = 'async'; image.fetchPriority = slide === slides[0] ? 'high' : 'low';
      image.sizes = '100vw'; image.srcset = slide.mobile_fallback_image+' '+slide.variants[3].width+'w, '+slide.fallback_image+' '+slide.width+'w';
      let fallback = false, settled = false;
      const timeout = setTimeout(() => finish(new Error('图片超时')), 8000);
      function finish(error) {
        if (settled) return; settled = true; clearTimeout(timeout);
        image.onload = image.onerror = null;
        error ? reject(error) : resolve(node);
      }
      image.onload = () => image.decode().then(() => finish(), () => finish(new Error('图片解码失败')));
      image.onerror = () => {
        if (!fallback) { fallback = true; source.remove(); image.removeAttribute('srcset'); image.src = slide.mobile_fallback_image; }
        else finish(new Error('图片不可用'));
      };
      node.append(source, image); image.src = slide.fallback_image;
    }).catch(error => { cache.delete(slide.id); throw error; });
    cache.set(slide.id, task); return task;
  }
  async function select(next) {
    if (!slides.length || !active) return;
    requested = (next + slides.length) % slides.length;
    const selected = requested, ticket = ++generation, slide = slides[selected];
    page.setAttribute('aria-busy', 'true'); announce('正在准备影像…');
    try {
      const prepared = await loadImage(slide);
      if (ticket !== generation || !active) return;
      resetMotion(); resetZoom();
      const previous = picture;
      picture = prepared.cloneNode(true); picture.classList.add('is-current');
      if (previous) { previous.classList.remove('is-current'); previous.setAttribute('aria-hidden', 'true'); }
      stage.append(picture);
      current = selected; page.dataset.slide = slide.id;
      const title = document.getElementById('gallery-title'); title.replaceChildren();
      slide.title.forEach(line => { const span = document.createElement('span'); span.textContent = line; title.append(span); });
      document.getElementById('gallery-label').textContent = slide.label;
      document.getElementById('gallery-description').textContent = slide.description;
      document.getElementById('gallery-credit').textContent = slide.credit;
      document.getElementById('gallery-source').href = slide.source_url;
      document.getElementById('gallery-original').href = slide.original_image_url;
      count.textContent = String(current+1).padStart(2, '0')+' / '+String(slides.length).padStart(2, '0');
      [...index.children].forEach((button, i) => button.setAttribute('aria-pressed', String(i === current)));
      announce(slide.label+'，第 '+(current+1)+' 张，共 '+slides.length+' 张');
      if (!document.hidden && !preference.matches && typeof picture.animate === 'function') {
        const reveal = picture.animate([{opacity:0}, {opacity:1}], {duration:600, easing:'ease-out'});
        imageAnimations.add(reveal);
        reveal.finished.then(() => { previous?.remove(); imageAnimations.delete(reveal); }, () => previous?.remove());
        const text = copy.animate([{opacity:0, transform:'translateY(8px)'}, {opacity:1, transform:'translateY(0)'}], {duration:500, delay:100, easing:'ease-out'});
        imageAnimations.add(text); text.finished.then(() => imageAnimations.delete(text), () => {});
      } else previous?.remove();
      document.dispatchEvent(new CustomEvent('galleryready'));
      for (const n of [(current+1)%slides.length, (current+slides.length-1)%slides.length]) loadImage(slides[n]).catch(() => {});
    } catch {
      if (ticket !== generation || !active) return;
      announce(current < 0 ? '影像暂未加载成功，可重试或进入航天新闻。' : '这张影像暂不可用，已保留当前画面。请重试。', true);
      document.dispatchEvent(new CustomEvent('galleryfailed'));
    } finally { if (ticket === generation) page.setAttribute('aria-busy', 'false'); }
  }
  async function start() {
    if (!slides.length) {
      const ticket = ++generation;
      try {
        const response = await fetch('/assets/gallery-slides.json?v=20261017-restored', {signal:AbortSignal.timeout(8000)});
        if (!response.ok) throw new Error('manifest');
        const data = await response.json();
        if (ticket !== generation || !active) return;
        if (!Array.isArray(data) || (!data.length || data.length > 40)) throw new Error('manifest');
        slides = data;
        slides.forEach((slide, i) => {
          const button = document.createElement('button'); button.type = 'button';
          button.setAttribute('aria-label', '观看 '+slide.label); button.setAttribute('aria-pressed', 'false');
          const image = new Image(); image.src = slide.thumbnail; image.alt = ''; image.loading = 'lazy'; image.width=320; image.height=Math.round(320*slide.height/slide.width);
          const preview = document.createElement('span'); preview.className = 'gallery-index-preview'; preview.append(image, document.createTextNode(slide.label));
          const number = document.createElement('span'); number.textContent=String(i+1).padStart(2, '0');
          button.append(number, preview); button.addEventListener('click', () => select(i)); index.append(button);
        });
      } catch { if (ticket === generation && active) { announce('影像目录暂不可用，可重试或进入航天新闻。', true); document.dispatchEvent(new CustomEvent('galleryfailed')); } return; }
    }
    select(current < 0 ? 0 : current);
  }
  function pageChanged() {
    const value = !page.classList.contains('hidden');
    document.body.classList.toggle('gallery-active', value);
    if (value === active) return;
    active = value;
    if (active) { if (current < 0) start(); }
    else { ++generation; page.setAttribute('aria-busy', 'false'); resetMotion(); viewing(false, false); }
  }
  document.getElementById('gallery-prev').addEventListener('click', () => select(requested-1));
  document.getElementById('gallery-next').addEventListener('click', () => select(requested+1));
  retry.addEventListener('click', () => slides.length ? select(requested) : start());
  explore.addEventListener('click', () => viewing(true)); exit.addEventListener('click', () => viewing(false));
  zoom.addEventListener('click', () => {
    resetMotion(); enlarged = !enlarged; panX=panY=0;
    page.classList.toggle('gallery-zoomed', enlarged); zoom.setAttribute('aria-pressed', String(enlarged));
    zoom.textContent = enlarged ? '还原全图 −' : '放大细节 +';
    stage.style.setProperty('--pan-x', '0px'); stage.style.setProperty('--pan-y', '0px');
  });
  function applyPan() {
    const image = picture?.querySelector('img'); if (!image) return;
    const rect=stage.getBoundingClientRect(), scale=Math.min(rect.width/image.width,rect.height/image.height);
    const maxX=Math.max(0,(image.width*scale*2-rect.width)/2), maxY=Math.max(0,(image.height*scale*2-rect.height)/2);
    panX=Math.max(-maxX,Math.min(maxX,panX)); panY=Math.max(-maxY,Math.min(maxY,panY));
    stage.style.setProperty('--pan-x', panX+'px'); stage.style.setProperty('--pan-y', panY+'px');
  }
  stage.addEventListener('pointerdown', event => {
    if (!active || (!enlarged && event.pointerType === 'mouse')) return;
    gesture = {id:event.pointerId, x:event.clientX, y:event.clientY, px:panX, py:panY};
    try { try { stage.setPointerCapture(event.pointerId); } catch {} } catch { /* Synthetic or cancelled pointer. */ }
  });
  stage.addEventListener('pointermove', event => {
    if (!active) return;
    if (gesture && enlarged) { panX=gesture.px+event.clientX-gesture.x; panY=gesture.py+event.clientY-gesture.y; applyPan(); return; }
    if (preference.matches || !fine.matches || enlarged || document.hidden || page.classList.contains('gallery-viewing')) return;
    movement={x:(event.clientX/innerWidth-.5)*12, y:(event.clientY/innerHeight-.5)*12};
    if (!frame) frame=requestAnimationFrame(() => { frame=0; stage.style.setProperty('--drift-x', movement.x+'px'); stage.style.setProperty('--drift-y', movement.y+'px'); });
  });
  stage.addEventListener('pointerup', event => {
    if (!gesture || event.pointerId !== gesture.id) return;
    const dx=event.clientX-gesture.x, dy=event.clientY-gesture.y;
    if (!enlarged && Math.abs(dx)>55 && Math.abs(dx)>Math.abs(dy)*1.4) select(requested+(dx<0?1:-1));
    gesture=null;
  });
  stage.addEventListener('pointercancel', () => { gesture=null; });
  stage.addEventListener('pointerleave', () => { if (!gesture) resetMotion(); });
  document.addEventListener('keydown', event => {
    if (!active || document.getElementById('gallery-welcome').open || event.altKey || event.ctrlKey || event.metaKey || event.target.closest('input,textarea,select,[contenteditable]')) return;
    if (event.key === 'Escape' && page.classList.contains('gallery-viewing')) { event.preventDefault(); viewing(false); }
    else if (enlarged && ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) {
      event.preventDefault(); panX+=event.key==='ArrowLeft'?40:event.key==='ArrowRight'?-40:0; panY+=event.key==='ArrowUp'?40:event.key==='ArrowDown'?-40:0; applyPan();
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); select(requested+(event.key === 'ArrowLeft'?-1:1)); }
  });
  preference.addEventListener('change', resetMotion);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { ++generation; resetMotion(); page.setAttribute('aria-busy', 'false'); }
    else if (active && current < 0) start();
  });
  addEventListener('pagehide', () => { ++generation; resetMotion(); });
  document.addEventListener('pagechange', pageChanged); pageChanged();
})();
