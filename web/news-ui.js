'use strict';
(() => {
  const page = document.getElementById('news'), toolbar = page.querySelector('.library-toolbar');
  page.querySelector('.news-empty')?.remove(); toolbar.lastElementChild.id = 'news-update';
  const element = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text) node.textContent = text; return node; };
  const filters = element('div', 'news-filters'); filters.setAttribute('role', 'group'); filters.setAttribute('aria-label', '按新闻类别筛选');
  const selectLabel = element('label', '', '来源 '), select = element('select'); select.id = 'news-source'; select.setAttribute('aria-label', '来源'); selectLabel.htmlFor = select.id; selectLabel.append(select);
  const resultLabel = element('p', 'news-message'), status = element('p', 'news-message'), list = element('div', 'real-news'); status.setAttribute('role', 'status');
  const more = element('button', 'secondary load-more', '加载更多'); more.hidden = true;
  toolbar.after(filters, selectLabel, resultLabel, status, list, more);
  const categories = [['', '全部'], ['domestic_agency', '国内机构'], ['commercial', '商业航天'], ['international_agency', '国际机构']], buttons = [];
  let source = '', category = '', cursor = null, generation = 0, busy = false, sources = [], displayedKey = null;
  const key = () => JSON.stringify([category, source]);
  function matches(item) {
    return !category || (category === 'commercial' ? item.publisher_kind === 'company' :
      item.publisher_kind === 'agency' && item.region === (category === 'domestic_agency' ? 'domestic' : 'international'));
  }
  function formatDate(date, precision) {
    if (!date) return '未提供发布时间';
    if (precision === 'day') return new Date(date).toLocaleDateString('zh-CN', {timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'});
    return new Date(date).toLocaleString('zh-CN', {year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false});
  }
  const kind = item => item.publisher_kind === 'company' ? '企业动态' : '官方机构';
  const language = item => ({zh: '中文原文', en: '英文原文', es: '西班牙文原文'}[item.lang] || '原始语言');
  const summaryKind = item => ({source_summary: '来源摘要节选', body_excerpt: '正文节选', none: '未提供摘要'}[item.summary_kind] || '来源摘要节选');
  function originalLink(item, label) {
    const link = element('a', '', label);
    try { const url = new URL(item.original_url); if (['http:', 'https:'].includes(url.protocol) && !url.username && !url.password) link.href = url.href; }
    catch { /* Invalid source links are never inserted as executable URLs. */ }
    link.target = '_blank'; link.rel = 'noopener noreferrer'; return link;
  }
  function renderItem(item) {
    const row = element('article', 'news-article'); row.dataset.articleId = item.id;
    const meta = element('div', 'news-meta', [item.source_name, formatDate(item.published_at, item.published_precision), kind(item), language(item), item.source_enabled === 0 ? '采集已停用 · 历史内容' : ''].filter(Boolean).join(' · '));
    const heading = element('h2'); heading.append(originalLink(item, item.title));
    const summary = element('p', '', item.summary || '来源未提供摘要，请查看原文。');
    const bottom = element('div', 'news-row-bottom'), action = element('button', 'link-button', '查看新闻详情 →');
    action.addEventListener('click', () => openDetail(item)); bottom.append(element('span', '', summaryKind(item)), action);
    row.append(meta, heading, summary, bottom); return row;
  }
  const detail = element('dialog', 'news-detail'); document.body.append(detail);
  function openDetail(item) {
    detail.replaceChildren(); const top = element('div', 'dialog-heading'), close = element('button', '', '×');
    close.setAttribute('aria-label', '关闭新闻详情'); close.addEventListener('click', () => detail.close()); top.append(element('h2', '', '新闻详情'), close);
    const meta = element('p', 'source-disclaimer', [item.source_name, kind(item), formatDate(item.published_at, item.published_precision), language(item)].join(' · '));
    const origin = element('p', 'source-disclaimer', '原文内容来源/署名：' + (item.content_source || '未提供'));
    const boundary = element('p', 'news-detail-boundary', '此处展示' + summaryKind(item) + '，不是完整报道。企业新闻中的自述来自发布方。科普 Agent 尚未接入这篇新闻。');
    detail.append(top, element('h3', '', item.title), meta, origin, element('p', '', item.summary || '来源未提供摘要。'), boundary, originalLink(item, '阅读发布方原文 ↗')); detail.showModal();
  }
  async function getJSON(path) {
    const response = await fetch(path, {signal: AbortSignal.timeout(15000)});
    if (!response.ok) throw new Error('HTTP ' + response.status); return response.json();
  }
  function renderSelect() {
    select.replaceChildren(); const all = element('option', '', '本组全部来源'); all.value = ''; select.append(all);
    sources.filter(matches).forEach(item => { const option = element('option', '', item.name + (!item.enabled ? '（采集未启用）' : '')); option.value = item.id; select.append(option); }); select.value = source;
  }
  function renderSources(items) {
    const relevant = items.filter(matches).filter(item => !source || item.id === source), dates = relevant.map(item => item.last_success_at).filter(Boolean).sort();
    const failures = relevant.filter(item => item.enabled && item.last_error), disabled = relevant.filter(item => !item.enabled);
    document.getElementById('news-update').textContent = (dates.length ? '最近成功采集：' + formatDate(dates.at(-1)) : '尚未成功采集') +
      (failures.length ? ' · ' + failures.length + '个来源更新失败，保留历史' : '') + (disabled.length ? ' · ' + disabled.length + '个来源未启用' : '');
    document.getElementById('news-update').title = relevant.map(item => item.name + '：' + (!item.enabled ? '未启用；' : item.last_error ? '本轮失败或部分失败，保留历史；' : '') + '最近成功 ' + formatDate(item.last_success_at)).join('\n');
  }
  async function load(reset = false) {
    if (busy && !reset) return; if (!reset && displayedKey !== key()) return;
    const request = ++generation, requestKey = key(); busy = true; more.disabled = true;
    status.textContent = displayedKey && displayedKey !== requestKey ? '正在切换筛选，下方暂为上一筛选结果…' : '正在读取已入库的新闻…';
    const params = new URLSearchParams({limit: '20'});
    if (source) params.set('source', source); if (category) params.set('category', category); if (!reset && cursor) params.set('cursor', cursor);
    try {
      const [data, state] = await Promise.all([getJSON('/api/news?' + params), getJSON('/api/news/sources')]); if (request !== generation) return;
      sources = state.items; renderSelect(); const fragment = document.createDocumentFragment(); data.items.forEach(item => fragment.append(renderItem(item)));
      if (reset) list.replaceChildren(fragment); else list.append(fragment);
      cursor = data.next_cursor; displayedKey = requestKey; more.hidden = !cursor; renderSources(sources);
      resultLabel.textContent = '当前结果：' + categories.find(([id]) => id === category)[1] + (source ? ' / ' + sources.find(item => item.id === source).name : '');
      status.textContent = list.children.length ? '' : '此筛选下暂无已入库新闻。未启用的来源不会自动采集。';
    } catch (error) {
      if (request !== generation) return;
      status.textContent = displayedKey && displayedKey !== requestKey ? '切换失败，下方保留上一筛选结果，请刷新重试。' : '列表请求失败，已显示的内容仍可阅读。请刷新重试。';
    } finally { if (request === generation) { busy = false; more.disabled = displayedKey !== key(); } }
  }
  categories.forEach(([id, name]) => {
    const button = element('button', id === '' ? 'active' : '', name); button.setAttribute('aria-pressed', String(id === ''));
    button.addEventListener('click', () => { category = id; source = ''; renderSelect(); buttons.forEach(item => { item.node.classList.toggle('active', item.id === id); item.node.setAttribute('aria-pressed', String(item.id === id)); }); load(true); });
    buttons.push({id, node: button}); filters.append(button);
  });
  select.addEventListener('change', () => { source = select.value; load(true); });
  const refresh = element('button', 'refresh-news', '刷新列表 ↻'); refresh.addEventListener('click', () => load(true)); filters.append(refresh);
  more.addEventListener('click', () => load(false)); renderSelect(); load(true);
})();
