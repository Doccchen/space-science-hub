'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const node = (tag, text, cls) => { const el = document.createElement(tag); if (text) el.textContent = text; if (cls) el.className = cls; return el; };
  let papers = [], shown = 8, busy = false;
  function link(text, url) {
    const el = node('a', text);
    try { const parsed = new URL(url); if (!['https:', 'http:'].includes(parsed.protocol) || parsed.username || parsed.password) return null; el.href = parsed.href; } catch { return null; }
    el.target = '_blank'; el.rel = 'noopener noreferrer'; return el;
  }
  function loading(value, message = '') {
    busy = value;
    ['analyze', 'search', 'news-input', 'query'].forEach(id => { $(id).disabled = value; });
    document.querySelectorAll('[data-example],#topics button').forEach(el => { el.disabled = value; });
    $('status').textContent = message;
    $('analyze-form').setAttribute('aria-busy', String(value));
    $('search-form').setAttribute('aria-busy', String(value));
  }
  async function api(path, body) {
    const response = await fetch('/api/reader/' + path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body), signal: AbortSignal.timeout(65000)});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '输入内容格式不正确，请调整后再试。');
    return data;
  }
  function errorMessage(error) { return error.name === 'TimeoutError' ? '检索等待超时，请稍后再试。' : error.message === 'Failed to fetch' ? '暂时无法连接检索服务，请确认本地服务已启动。' : error.message; }
  function resetResults() { $('results-panel').hidden = true; papers = []; }
  $('news-input').addEventListener('input', () => { $('topics-panel').hidden = true; resetResults(); $('status').textContent = ''; });
  $('query').addEventListener('input', resetResults);
  document.querySelectorAll('[data-example]').forEach(button => button.addEventListener('click', () => {
    $('news-input').value = button.dataset.example; $('news-input').dispatchEvent(new Event('input')); $('news-input').focus();
  }));
  $('analyze-form').addEventListener('submit', async event => {
    event.preventDefault(); if (busy) return;
    resetResults(); $('topics-panel').hidden = true;
    loading(true, '正在识别技术主题…');
    try {
      const result = await api('analyze', {text: $('news-input').value.trim()});
      $('topics').replaceChildren();
      result.topics.forEach((topic, index) => {
        const button = node('button', topic.name); button.type = 'button'; button.setAttribute('aria-pressed', String(index === 0));
        button.addEventListener('click', () => {
          $('topics').querySelectorAll('button').forEach(el => el.setAttribute('aria-pressed', String(el === button)));
          $('query').value = topic.query; resetResults(); $('query').focus();
        });
        $('topics').append(button);
      });
      $('query').value = result.topics[0].query;
      $('analysis-note').textContent = result.method + ' · ' + result.notice;
      $('topics-panel').hidden = false; loading(false); $('query').focus();
    } catch (error) { loading(false, errorMessage(error)); }
  });
  function render() {
    const selected = papers.filter(p => (!$('year').value || String(p.year) === $('year').value) && (!$('kind').value || p.type === $('kind').value) && (!$('oa').checked || p.fulltext));
    $('papers').replaceChildren();
    $('result-count').textContent = `${selected.length} 篇候选文献`;
    selected.slice(0, shown).forEach((paper, index) => {
      const article = node('article', '', 'paper'), content = node('div');
      article.append(node('span', String(index + 1).padStart(2, '0'), 'paper-number'), content);
      content.append(node('span', `${paper.type} · ${paper.sources.join(' / ')}`, 'tag'));
      const title = node('h3'); title.append(link(paper.title, paper.url) || node('span', paper.title)); content.append(title);
      content.append(node('p', [(paper.authors || []).join('、') || '作者信息未提供', paper.year || '年份未提供', paper.venue].filter(Boolean).join(' · '), 'metadata'));
      if (paper.doi) content.append(node('p', 'DOI: ' + paper.doi, 'metadata'));
      content.append(node('p', paper.relation + ' · ' + paper.reason, 'reason'));
      if (paper.abstract) { const details = node('details'); details.append(node('summary', '查看来源摘要'), node('p', paper.abstract)); content.append(details); }
      else content.append(node('p', '来源未提供摘要，请到原文页面核对内容。', 'metadata'));
      const links = node('div', '', 'paper-links');
      const original = link('查看论文原始页面 ↗', paper.url); if (original) links.append(original);
      const fulltext = link('公开全文入口 ↗', paper.fulltext);
      if (fulltext) links.append(fulltext); else links.append(node('span', '暂未提供公开全文链接'));
      content.append(links); $('papers').append(article);
    });
    if (!selected.length) $('papers').append(node('p', papers.length ? '当前筛选条件下没有论文，请放宽筛选。' : '本次没有获得论文记录。请调整检索词，或使用下方来源网站继续查找。', 'empty'));
    $('more').hidden = selected.length <= shown;
  }
  $('search-form').addEventListener('submit', async event => {
    event.preventDefault(); if (busy) return;
    resetResults(); loading(true, '正在检索四个来源，通常需要几秒到几十秒…');
    try {
      const result = await api('search', {query: $('query').value.trim()});
      papers = result.papers; shown = 8;
      $('source-status').replaceChildren(...result.sources.map(source => node('span', source.source + ' · ' + (source.state === 'ok' ? `${source.count} 条${source.cached ? '（缓存）' : ''}` : source.message), source.state === 'error' ? 'failed' : '')));
      $('year').replaceChildren(new Option('全部年份', ''), ...[...new Set(papers.map(p => p.year).filter(Boolean))].sort((a,b) => b-a).map(year => new Option(String(year), String(year))));
      $('kind').value = ''; $('oa').checked = false;
      $('result-query').textContent = '本次检索：' + result.query;
      $('external-links').replaceChildren(...result.links.map(item => link(item.name + ' ↗', item.url)).filter(Boolean));
      $('results-panel').hidden = false; render();
      const failures = result.sources.filter(source => source.state !== 'ok').length;
      loading(false, failures === 4 ? '所有来源暂不可用，本次未获得论文。可稍后重试或前往来源网站检索。' : failures ? '部分来源暂不可用，以下显示其他来源返回的结果。' : '检索完成，请结合摘要核对相关性。');
      $('results-title').focus();
    } catch (error) { loading(false, errorMessage(error)); }
  });
  ['year','kind','oa'].forEach(id => $(id).addEventListener('change', () => { shown = 8; render(); }));
  $('more').addEventListener('click', () => { shown += 8; render(); });
  async function boot() {
    // Disclose model processing before any user-triggered analysis, including configuration failures.
    $('privacy').textContent = '点击识别后，输入可能发送至已配置的百炼模型提取技术；检索词将发送至论文来源。不会建立个人记录。';
    const news = new URLSearchParams(location.search).get('news');
    if (!news || !/^[1-9]\d*$/.test(news)) return;
    loading(true, '正在带入新闻内容…');
    try {
      const responses = await Promise.all([fetch('/api/news/' + news, {cache: 'no-store', signal: AbortSignal.timeout(15000)}), fetch('/api/news/' + news + '/content', {cache: 'no-store', signal: AbortSignal.timeout(15000)})]);
      if (!responses[0].ok) throw new Error('新闻暂不可用，请手动粘贴新闻或输入技术名称。');
      const detail = await responses[0].json();
      let paragraphs = '';
      if (responses[1].ok) { const content = await responses[1].json(); paragraphs = (content.blocks || []).map(block => block.text || (block.items || []).join(' ')).join('\n'); }
      const text = [detail.title, paragraphs].filter(Boolean).join('\n\n');
      $('news-input').value = text.slice(0, 6000);
      loading(false, '已带入新闻' + (text.length > 6000 ? '前 6000 字' : '内容') + '，请识别并确认技术主题后检索。');
    } catch (error) { loading(false, errorMessage(error)); }
  }
  boot();
})();
