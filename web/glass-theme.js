'use strict';
(() => {
  // Retire this site's former manual preference; system preferences now own fallback.
  document.documentElement.removeAttribute('data-reduce-transparency');
  try { localStorage.removeItem('space-reduce-transparency'); } catch { /* Storage can be unavailable. */ }
  function syncPage() {
    const active = [...document.querySelectorAll('main.page')].find(page => !page.classList.contains('hidden'));
    document.body.dataset.themePage = active?.id || 'news';
  }
  document.addEventListener('pagechange', syncPage);
  window.addEventListener('hashchange', syncPage);
  syncPage();
})();