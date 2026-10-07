'use strict';
(() => {
  const byId = id => document.getElementById(id);
  const grid = byId('library-list'), message = byId('resource-message');
  const search = byId('resource-search'), category = byId('resource-category');
  let page = 1, pages = 0, started = false, timer, listRequest;
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function size(bytes) {
    return bytes >= 1048576 ? (bytes / 1048576).toFixed(1) + ' MiB' : Math.ceil(bytes / 1024) + ' KiB';
  }
  function cover(item) {
    const box = node('div', undefined, 'resource-cover');
    const fallback = node('div', undefined, 'resource-cover-fallback');
    const coverLabel=node('span', item.cover_url ? '正在载入封面' : 'PDF');fallback.append(coverLabel);
    box.append(fallback);
    if (item.cover_url) {
      box.classList.add('is-loading');
      const image = document.createElement('img');
      image.alt = item.title + '封面'; image.width = 400; image.height = 600;
      image.loading = 'lazy'; image.decoding = 'async';
      image.addEventListener('load', () => {fallback.hidden = true;box.classList.remove('is-loading');});
      image.addEventListener('error', () => {image.remove();box.classList.remove('is-loading');coverLabel.textContent='PDF';}, {once: true});
      image.src = item.cover_url; box.append(image);
    }
    return box;
  }
  function download(item) {
    const link = node('a', '下载 PDF ↓', 'resource-download');
    link.href = item.download_url;
    link.setAttribute('aria-label', '下载' + item.title + ' PDF');
    return link;
  }
  function card(item) {
    const box = node('div', undefined, 'resource-card');
    const title = node('h2', item.title, 'resource-title');
    const actions = node('div', undefined, 'resource-actions'); actions.append(download(item));
    box.append(cover(item), title, node('p', [item.authors.join('、'), item.edition].filter(Boolean).join(' · '), 'resource-authors'),
      node('p', [item.category, item.format, size(item.size_bytes)].filter(Boolean).join(' · '), 'resource-meta'), actions);
    return box;
  }
  function pagination() {
    byId('resource-prev').disabled = page <= 1;
    byId('resource-next').disabled = page >= pages;
    byId('resource-page').textContent = pages ? page + ' / ' + pages : '';
    byId('resource-pagination').hidden = pages < 2;
  }
  async function load() {
    if (listRequest) listRequest.abort();
    const request = new AbortController(); listRequest = request;
    grid.setAttribute('aria-busy', 'true');
    message.textContent = '正在读取资料…'; byId('resource-retry').hidden = true;
    byId('empty-library').hidden = true; byId('resource-pagination').hidden = true;
    grid.replaceChildren();
    const query = new URLSearchParams({q: search.value.trim(), category: category.value, page, page_size: 12});
    try {
      const response = await fetch('/api/resources?' + query, {signal: request.signal});
      if (!response.ok) throw new Error('目录暂不可用');
      const data = await response.json();
      if (request !== listRequest) return;
      pages = data.pages;
      if (pages && page > pages) {page = pages; return load();}
      byId('library-count').textContent = data.total + ' 份资料';
      const selected = category.value;
      category.replaceChildren(new Option('全部分类', ''));
      data.categories.forEach(name => category.add(new Option(name, name)));
      category.value = selected;
      grid.replaceChildren(...data.items.map(card));
      message.textContent = '';
      byId('empty-library').hidden = data.items.length !== 0;
      byId('resource-empty-title').textContent = search.value.trim() || selected ? '没有找到相符资料' : '资料正在整理';
      byId('resource-empty-copy').textContent = search.value.trim() || selected ? '试试其他书名、作者或分类。' : '整理完成的电子书将在这里展示书名与下载入口。';
      pagination();
    } catch (error) {
      if (error.name !== 'AbortError' && request === listRequest) {
        message.textContent = '资料暂时无法读取，请重试。';
        byId('library-count').textContent = '暂不可用'; byId('resource-retry').hidden = false;
      }
    } finally {
      if (request === listRequest) grid.setAttribute('aria-busy', 'false');
    }
  }
  search.addEventListener('input', () => {clearTimeout(timer); timer = setTimeout(() => {page = 1; load();}, 250);});
  category.addEventListener('change', () => {clearTimeout(timer); page = 1; load();});
  byId('resource-prev').addEventListener('click', () => {if (page > 1) {page--; load();}});
  byId('resource-next').addEventListener('click', () => {if (page < pages) {page++; load();}});
  byId('resource-retry').addEventListener('click', load);
  document.addEventListener('pagechange', event => {
    if (event.detail === 'library' && !started) {started = true; load();}
  });
  if (window.location.hash === '#library') showPage('library');
})();
