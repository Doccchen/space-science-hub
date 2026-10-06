'use strict';
// Shared navigation; each page owns its controls.
let visiblePage = 'news';
function showPage(page) {
  if (!document.getElementById(page)?.classList.contains('page')) page = 'news';
  const changed = visiblePage !== page; visiblePage = page;
  document.querySelectorAll('.page').forEach(node => node.classList.toggle('hidden', node.id !== page));
  document.querySelectorAll('header nav [data-page]').forEach(node => node.classList.toggle('active', node.dataset.page === page));
  if (changed) window.scrollTo({top: 0, behavior: 'instant'});
  document.dispatchEvent(new CustomEvent('pagechange', {detail: page}));
}
function navigatePage(page) { if (location.hash === '#' + page) showPage(page); else location.hash = page; }
document.querySelectorAll('[data-page]').forEach(node => node.addEventListener('click', () => navigatePage(node.dataset.page)));
document.getElementById('home-link').addEventListener('click', event => { event.preventDefault(); navigatePage('news'); });