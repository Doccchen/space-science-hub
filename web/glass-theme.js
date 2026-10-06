'use strict';
(() => {
  const root = document.documentElement, key = 'space-reduce-transparency';
  const preference = matchMedia('(prefers-reduced-transparency: reduce)');
  let saved = null;
  try { saved = localStorage.getItem(key); } catch { /* Display preferences work without storage. */ }
  const controls = [];
  function apply(value) {
    root.dataset.reduceTransparency = String(value);
    controls.forEach(control => { control.checked = value; });
  }
  ['news', 'library'].forEach(id => {
    const label = document.createElement('label'), input = document.createElement('input');
    label.className = 'theme-preference'; input.type = 'checkbox';
    label.append(input, document.createTextNode('减少透明效果'));
    document.getElementById(id).querySelector('.page-title').append(label); controls.push(input);
    input.addEventListener('change', () => {
      saved = String(input.checked); apply(input.checked);
      try { localStorage.setItem(key, saved); } catch { /* Keep the session preference. */ }
    });
  });
  apply(saved === null ? preference.matches : saved === 'true');
  preference.addEventListener('change', event => { if (saved === null) apply(event.matches); });
  function syncPage() {
    const active = [...document.querySelectorAll('main.page')].find(page => !page.classList.contains('hidden'));
    document.body.dataset.themePage = active?.id || 'news';
  }
  document.addEventListener('pagechange', syncPage);
  window.addEventListener('hashchange', syncPage);
  syncPage();
})();
