'use strict';
(() => {
  const agentStyle = document.createElement('link'); agentStyle.rel = 'stylesheet'; agentStyle.href = '/assets/news-agent.css'; document.head.append(agentStyle);
  const make = (tag, text, cls) => { const node = document.createElement(tag); if (text) node.textContent = text; if (cls) node.className = cls; return node; };
  const dialog = make('dialog', '', 'news-reader'); dialog.setAttribute('aria-labelledby', 'reader-title');
  const bar = make('div', '', 'reader-bar'), label = make('span', '新闻阅读'), close = make('button', '×');
  close.className='reader-close';close.type='button';close.setAttribute('aria-label', '关闭阅读'); bar.append(label, close);
  const body = make('div', '', 'reader-body'); dialog.append(bar, body); document.body.append(dialog);
  let activeId = null, trigger = null, generation = 0, controller = null, scroll = 0, previousOverflow = '', pushed = false, closing = false, triggerWasButton = false;
  history.scrollRestoration = 'manual';
  function hide() {
    const closingId = activeId;
    generation++; controller?.abort(); activeId = null;
    if (dialog.open) dialog.close();
    document.body.style.overflow = previousOverflow;
    if (visiblePage === 'news') window.scrollTo({top: scroll, behavior: 'instant'});
    if (visiblePage === 'news') {
      const origin = trigger?.isConnected ? trigger : document.querySelector('[data-article-id="' + closingId + '"] '+(triggerWasButton?'.link-button':'h2 a'));
      (origin || document.querySelector('.news-results-bar'))?.focus({preventScroll: true});
    }
    trigger = null; body.replaceChildren();
    closing = false;
  }
  function closeReader() {
    if (!dialog.open || closing) return;
    closing = true; generation++; controller?.abort();
    if (pushed && history.state?.newsReader) { pushed = false; history.back(); }
    else { history.replaceState(null, '', '#news'); route(); }
  }
  close.addEventListener('click', closeReader);
  dialog.addEventListener('cancel', event => { event.preventDefault(); closeReader(); });
  dialog.addEventListener('keydown', event => {
    if (event.key !== 'Tab') return;
    const targets = [...dialog.querySelectorAll('button:not([disabled]),a[href],textarea:not([disabled]),input:not([disabled]),summary')].filter(node => node.getClientRects().length);
    const first = targets[0], last = targets.at(-1);
    if(document.activeElement?.id==='reader-title'){event.preventDefault();(event.shiftKey?last:first)?.focus();}
    else if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) { event.preventDefault(); first?.focus(); }
  });
  function focusTitle() {
    const title=body.querySelector('#reader-title');
    if(title){title.tabIndex=-1;title.focus({preventScroll:true});}
  }
  function returnButton() {
    const button=make('button','返回新闻列表','reader-return');button.type='button';button.addEventListener('click',closeReader);return button;
  }
  function link(url) {
    const node = make('a', '查看发布方原文 ↗');
    try { const parsed = new URL(url); if (['https:', 'http:'].includes(parsed.protocol) && !parsed.username && !parsed.password) node.href = parsed.href; } catch { /* invalid metadata */ }
    node.target = '_blank'; node.rel = 'noopener noreferrer'; return node;
  }
  function blockNode(block, articleId, version, number) {
    let node;
    if (block.type === 'heading') node = make('h' + (block.level || 2), block.text);
    else if (block.type === 'paragraph') node = make('p', block.text);
    else if (block.type === 'list') { node = make(block.ordered ? 'ol' : 'ul'); block.items.forEach(item => node.append(make('li', item))); }
    else if (block.type === 'table') {
      node = make('div', '', 'reader-table'); const table = make('table'); if (block.caption) table.append(make('caption', block.caption));
      const tbody = make('tbody'); block.rows.forEach(row => { const tr = make('tr'); row.forEach(cell => tr.append(make('td', cell))); tbody.append(tr); }); table.append(tbody); node.append(table);
    } else return null;
    node.id = 'reading-' + articleId + '-' + version.replaceAll(':', '-') + '-' + block.block_id;
    node.dataset.blockId = block.block_id;
    if (block.type === 'paragraph') node.title = '本站展示第' + number + '段（当前版本）';
    return node;
  }
  async function load(id) {
    controller?.abort(); controller = new AbortController(); const currentController = controller, request = ++generation;
    const timeout = setTimeout(() => currentController.abort(), 15000);
    body.replaceChildren(make('h1', '正在读取新闻…')); body.firstChild.id = 'reader-title';
    body.scrollTop=0;focusTitle();
    delete body.dataset.contentVersion;
    try {
      const fetchJSON = async path => { const response = await fetch(path, {cache: 'no-store', signal: currentController.signal}); if (!response.ok) throw new Error(String(response.status)); return response.json(); };
      const [detail, content] = await Promise.all([fetchJSON('/api/news/' + id), fetchJSON('/api/news/' + id + '/content')]);
      if (request !== generation || !dialog.open) return;
      const previous=window.newsList?.item(id) || {id:Number(id),title:'新闻正文'};
      const item=window.NewsPresentation.mergeItem(previous,detail);
      if(!item)throw new Error('invalid_article');
      const publicItem = {...item, reading_mode: content.reading_mode, read_scope: content.read_scope,
        availability:content.availability,source_reading_policy:content.source_reading_policy,
        summary: content.reading_mode === 'full_text' ? (content.blocks.find(block => block.type === 'paragraph')?.text || '').slice(0, 600) : ''};
      document.dispatchEvent(new CustomEvent('readingchange', {detail: publicItem}));
      const shouldFocus=document.activeElement?.id==='reader-title';
      const title = make('h1', item.title); title.id = 'reader-title';title.tabIndex=-1;
      const scope = {full_text: '本站全文 · 原始语言', link_only: '原文阅读 · 正文未开放', unavailable: '暂不可用'}[content.read_scope];
      const date = item.published_time_status === 'timezone_missing' ? (item.published_raw || '') + '（来源未标时区）' :
        (item.published_calendar_date || (item.published_at ? new Date(item.published_at).toLocaleString('zh-CN', {hour12: false}) : '日期未提供'));
      const language = {en:'英文',zh:'中文',ja:'日文',es:'西班牙文',fr:'法文',de:'德文'}[content.language] || '原始语言';
      body.replaceChildren(make('p', scope, 'reader-scope'), title, make('p', [item.source_name, date, language].join(' · '), 'reader-meta'));
      if (content.credit) body.append(make('p', '内容署名：' + content.credit, 'reader-meta'));
      let paragraphs = 0;
      const figures = position => (content.assets || []).filter(asset => asset.block_index === position).forEach(asset => {
        const figure = make('figure', '', 'reader-figure'), image = make('img');
        image.src = asset.url; image.alt = asset.caption; image.width = asset.width; image.height = asset.height; image.loading = 'lazy';
        image.addEventListener('error', () => { image.remove(); figure.prepend(make('p', '图片暂不可用，请查看原文。')); });
        figure.append(image, make('figcaption', asset.caption + ' · ' + asset.credit)); body.append(figure);
      });
      figures(0);
      content.blocks.forEach((block, index) => { if (block.type === 'paragraph') paragraphs++; const node = blockNode(block, id, content.content_version, paragraphs); if (node) body.append(node); figures(index+1); });
      const footer = make('div', '', 'reader-notice'); footer.append(make('p', content.notes), make('p', content.assets?.length ? '仅展示已审核图片；其他图片请到原文查看。' : '图片请到原文查看。'), link(item.original_url));
      body.append(footer,returnButton()); body.dataset.contentVersion = content.content_version;
      try {
        const agent = await import('/assets/news-agent.js');
        if (request === generation && dialog.open) agent.mount(body, item);
      } catch { if (request === generation && dialog.open) body.append(make('p', '新闻科普入口暂不可用。')); }
      if(shouldFocus)focusTitle();
    } catch (error) {
      if (request !== generation || !dialog.open) return;
      const title = make('h1', error.message === '404' ? '这篇新闻不存在' : '新闻读取失败'); title.id = 'reader-title';
      const retry = make('button', '重试', 'secondary'); retry.addEventListener('click', () => load(id));
      title.tabIndex=-1;body.replaceChildren(title, make('p', '关闭后仍可继续浏览当前列表。'), retry,returnButton());focusTitle();
    } finally { clearTimeout(timeout); }
  }
  function route() {
    const match = /^#news\/article\/([1-9]\d*)$/.exec(location.hash);
    if (match) {
      showPage('news'); const id = match[1];
      if (!dialog.open) { closing=false;scroll = window.scrollY; previousOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden'; dialog.showModal(); }
      if (activeId !== id) { activeId = id; load(id); }
    } else {
      const page = location.hash.slice(1) || 'news'; showPage(page);
      if (dialog.open) hide(); pushed = false;
    }
  }
  window.newsReader = {open(id, origin) {
    trigger = origin; pushed = true;
    triggerWasButton=origin?.tagName==='BUTTON';
    history.pushState({newsReader: true}, '', '#news/article/' + id); route();
  }};
  window.addEventListener('hashchange', route); window.addEventListener('popstate', route);
  // Recheck permissions after tab suspension / back-forward cache; never retain body offline.
  document.addEventListener('visibilitychange', () => { if (dialog.open) { if (document.hidden) { generation++; controller?.abort(); body.replaceChildren(); } else load(activeId); } });
  window.addEventListener('pagehide', () => { generation++; controller?.abort(); body.replaceChildren(); });
  window.addEventListener('pageshow', event => { if (event.persisted && dialog.open) load(activeId); });
  setInterval(async () => {
    if (!dialog.open || document.hidden || !body.dataset.contentVersion) return;
    const id = activeId, request = generation;
    try {
      const response = await fetch('/api/news/' + id, {cache: 'no-store', signal: AbortSignal.timeout(10000)});
      if (!response.ok) throw new Error('Permission check failed');
      const content = await response.json();
      if (request === generation && dialog.open && content.content_version !== body.dataset.contentVersion) load(id);
    } catch {
      if (request === generation && dialog.open) { const title = make('h1', '展示范围暂时无法确认'); title.id = 'reader-title'; title.tabIndex=-1;body.replaceChildren(title, make('p', '请重试，或关闭后继续浏览列表。')); delete body.dataset.contentVersion; const retry = make('button', '重试', 'secondary'); retry.addEventListener('click', () => load(id)); body.append(retry,returnButton()); }
    }
  }, 30000);
  route();
})();
