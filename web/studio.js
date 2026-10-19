'use strict';
// Logical page fragments never match content IDs, so the browser cannot anchor-scroll.
let visiblePage = 'news';
function navigationPage(hash = location.hash) {
  return /^#(?:page\/)?(news|home|about|library)$/.exec(hash)?.[1] || 'news';
}
if (/^#(news|home|about|library)$/.test(location.hash)) {
  history.replaceState(history.state, '', '#page/' + navigationPage());
}
function showPage(page) {
  if (page === 'library') { location.href = '/assets/resource-navigation.html'; return; }
  if (!document.getElementById(page)?.classList.contains('page')) page = 'news';
  const changed = visiblePage !== page; visiblePage = page;
  document.querySelectorAll('.page').forEach(node => node.classList.toggle('hidden', node.id !== page));
  document.querySelectorAll('.site-header [data-page]').forEach(node => {
    const active = node.dataset.page === page;
    node.classList.toggle('active', active);
    if (active) node.setAttribute('aria-current', 'page'); else node.removeAttribute('aria-current');
  });
  if (changed) document.dispatchEvent(new CustomEvent('pagechange', {detail: page}));
}
function navigatePage(page) {
  if (page === 'library') { location.href = '/assets/resource-navigation.html'; return; }
  if (location.hash !== '#page/' + page) history.pushState(null, '', '#page/' + page);
  showPage(page);
}
document.querySelectorAll('[data-page]').forEach(node => node.addEventListener('click', event => {
  if (node.tagName === 'A' && (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button > 0)) return;
  event.preventDefault(); navigatePage(node.dataset.page);
}));
document.getElementById('home-link').addEventListener('click', event => {
  if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button > 0) return;
  event.preventDefault(); navigatePage('news');
});
