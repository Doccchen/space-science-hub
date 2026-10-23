'use strict';
(() => {
  const get = id => document.getElementById(id), make = (tag, text) => { const node = document.createElement(tag); node.textContent = text; return node; };
  const title = get('guide-title'), content = get('guide-body'), status = get('guide-status'), retry = get('guide-retry');
  let items = null, controller, generation = 0;
  async function fetchFile(path, signal, json = false) {
    const response = await fetch(path, {signal, cache: 'no-cache'});
    if (!response.ok) throw new Error('load_failed');
    return json ? response.json() : response.text();
  }
  async function load(moveFocus = false) {
    document.title = '知航';
    controller?.abort(); controller = new AbortController(); const signal = controller.signal, request = ++generation;
    const timeout = setTimeout(() => controller?.signal === signal && controller.abort(), 15000);
    title.textContent = '正在加载指南…'; content.replaceChildren(); get('guide-meta').textContent = ''; status.textContent = '正在读取文档。'; retry.hidden = true; get('guide-actions').hidden = true;
    document.querySelector('.guide-article').setAttribute('aria-busy', 'true');
    try {
      if (!items) {
        const manifest = await fetchFile('/assets/guides/index.json', signal, true);
        if (!Array.isArray(manifest.items) || !manifest.items.length || !manifest.items.every(item => /^[a-z0-9-]+$/.test(item.id) && /^[a-z0-9-]+\.md$/.test(item.file) && typeof item.title === 'string')) throw new Error('invalid_manifest');
        if (request !== generation) return;
        items = manifest.items;
        get('guide-index').replaceChildren(...items.map(item => { const li = make('li', ''), a = make('a', item.title); a.href = '#' + item.id; li.append(a); return li; }));
      }
      const id = location.hash.slice(1) || items[0].id, item = items.find(item => item.id === id);
      get('guide-index').querySelectorAll('a').forEach(a => { if (a.hash === '#' + id) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
      if (!item) { title.textContent = '未找到这篇指南'; status.textContent = '请从阅读目录选择一篇文档。'; return; }
      const text = await fetchFile('/assets/guides/' + item.file, signal);
      if (request !== generation) return;
      if (!text.trim()) throw new Error('empty_document');
      // Only editorially maintained local guide images; publisher images use their own review flow.
      const allowImage = url => { const parsed = new URL(url); return parsed.origin === location.origin && /^\/assets\/guides\/images\/[a-z0-9-]+\.(?:png|jpe?g|webp)$/i.test(parsed.pathname) && !parsed.search; };
      content.append(ArticleRenderer.markdown(text, {allowImage})); title.textContent = item.title;
      get('guide-meta').textContent = '知航平台指南 · 更新于 ' + item.updated + ' · ' + item.summary;
      status.textContent = ''; get('guide-actions').hidden = false;
      get('guide-copy').href = '#' + item.id;
      if (moveFocus) title.focus();
    } catch (error) {
      if (request !== generation) return;
      title.textContent = '指南读取失败'; status.textContent = '暂时无法读取文档，请重试。'; retry.hidden = false;
    } finally {
      clearTimeout(timeout);
      if (request === generation) document.querySelector('.guide-article').setAttribute('aria-busy', 'false');
    }
  }
  retry.addEventListener('click', () => load(true));
  window.addEventListener('hashchange', () => load(true));
  get('guide-copy').addEventListener('click', async event => {
    event.preventDefault(); const href = new URL(get('guide-copy').href).href;
    try { await navigator.clipboard.writeText(href); status.textContent = '本篇链接已复制。'; }
    catch { status.textContent = '请从浏览器地址栏复制本篇链接。'; if (location.href !== href) history.replaceState(null, '', href); }
  });
  load();
})();
