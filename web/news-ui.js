'use strict';
(() => {
  const page = document.getElementById('news'), toolbar = page.querySelector('.library-toolbar');
  page.querySelector('.news-empty')?.remove(); toolbar.lastElementChild.id = 'news-update';
  const element = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text) node.textContent = text; return node; };
  const filters = element('div', 'news-filters'); filters.setAttribute('role', 'group'); filters.setAttribute('aria-label', '按新闻类别筛选');
  const selectLabel = element('label', '', '来源 '), select = element('select'); select.id = 'news-source'; select.setAttribute('aria-label', '来源'); selectLabel.htmlFor = select.id; selectLabel.append(select);
  const regionLabel = element('label', '', '商业地区 '), regionSelect = element('select'); regionSelect.id = 'news-region'; regionSelect.setAttribute('aria-label', '商业地区'); regionLabel.htmlFor = regionSelect.id; regionLabel.append(regionSelect); regionLabel.hidden = true;
  const resultLabel = element('p', 'news-message'), status = element('p', 'news-message'), list = element('div', 'real-news'); status.setAttribute('role', 'status');
  const panel = element('details', 'news-filter-panel'), controls = element('div', 'news-filter-controls');
  panel.setAttribute('aria-label', '新闻筛选');
  const panelSummary = element('summary', 'news-filter-toggle'), selectedSummary = element('span', 'news-filter-selection', '全部');
  panelSummary.append(element('span', '', '筛选新闻'), selectedSummary);
  const filterBody = element('div', 'news-filter-body'), filterHeading = element('div', 'news-filter-heading'), reset = element('button', 'news-filter-reset', '重置');
  reset.type = 'button'; filterHeading.append(element('h2', '', '筛选新闻'), reset);
  const sourceOptions = element('div', 'news-source-options'); sourceOptions.setAttribute('role','group'); sourceOptions.setAttribute('aria-label','按来源筛选');
  const moreSources = element('details', 'news-more-sources'), moreSummary = element('summary', '', '更多来源');
  const extraOptions = element('div','news-source-options'); moreSources.append(moreSummary,extraOptions);
  selectLabel.hidden = true;
  const sourceHeading = element('h3', 'news-filter-label', '来源'), categoryHeading = element('h3', 'news-filter-label', '新闻类别');
  const desktopFilter = matchMedia('(min-width: 1024px)'); panel.open = desktopFilter.matches;
  desktopFilter.addEventListener('change', event => { panel.open = event.matches; });
  const resultBar = element('div', 'news-results-bar'); resultBar.tabIndex = -1;
  const PAGE_SIZE = 10;
  const totalDescription = element('span', 'news-result-count'); totalDescription.setAttribute('aria-live', 'polite');
  resultBar.append(totalDescription);
  const pagers = [];
  function makePager(position) {
    const nav = element('nav', 'news-pagination'); nav.setAttribute('aria-label', '新闻分页（' + position + '）');
    const previous = element('button', 'secondary', '上一页'), next = element('button', 'secondary', '下一页'), numbers = element('div', 'news-page-buttons');
    const description = element('span', 'news-page-info');
    description.tabIndex = -1;
    const jump = element('form', 'news-page-jump'), jumpLabel = element('label', '', '跳到第 '), input = element('input');
    input.type = 'number'; input.min = '1'; input.step = '1'; input.required = true; input.setAttribute('aria-label', '跳转页码（' + position + '）');
    jumpLabel.append(input, document.createTextNode(' 页')); const go = element('button', 'secondary', '跳转'); jump.append(jumpLabel, go);
    const capsule = element('div', 'news-page-capsule'), detail = element('details', 'news-jump-disclosure');
    const summary = element('summary', '', '跳转到指定页'); detail.append(summary, jump);
    capsule.append(previous, numbers, description, next); nav.append(capsule, detail);
    previous.addEventListener('click', () => load(false, currentPage-1, true)); next.addEventListener('click', () => load(false, currentPage+1, true));
    jump.addEventListener('submit', event => { event.preventDefault(); const target = Number(input.value); if (Number.isInteger(target) && target >= 1 && target <= totalPages) load(false, target, true); });
    pagers.push({nav,previous,next,numbers,description,input,go,detail}); return nav;
  }
  const bottomPager = makePager('底部');
  controls.append(regionLabel, sourceHeading, sourceOptions, moreSources, selectLabel);
  filterBody.append(filterHeading, categoryHeading, filters, controls); panel.append(panelSummary, filterBody);
  const resultMeta = element('div', 'news-result-meta'), resultActions = element('div', 'news-result-actions');
  const updateDetails = element('details','news-update-details');
  updateDetails.append(element('summary','','更新状态'),toolbar.lastElementChild);
  resultMeta.append(totalDescription,resultLabel,updateDetails); resultBar.append(resultMeta,resultActions);
  const layout = element('div','news-layout'), results = element('section','news-results'); results.setAttribute('aria-label','新闻结果');
  const activeFilters=element('div','selected-filters');activeFilters.setAttribute('role','group');activeFilters.setAttribute('aria-label','已选筛选条件');
  results.append(resultBar,activeFilters,status,list,bottomPager); layout.append(panel,results); toolbar.replaceWith(layout);
  let displayedItems = new Map(), sourceSignature = '';
  const categories = [['', '全部'], ['domestic_agency', '国内机构'], ['commercial', '商业航天'], ['international_agency', '国际机构']], buttons = [];
  let source = '', category = '', regionChoice = '', generation = 0, busy = false, sources = [], displayedKey = null, geographicRegions = [];
  let currentPage = 1, totalPages = 1, totalCount = 0, snapshot = null;
  const regionFilters = () => ['domestic', 'international'].includes(regionChoice) ? {region: regionChoice} : {geographic_region: regionChoice};
  const key = () => JSON.stringify([category, regionChoice, source]);
  function matches(item) {
    const categoryMatch = !category || (category === 'commercial' ? item.publisher_kind === 'company' :
      item.publisher_kind === 'agency' && item.region === (category === 'domestic_agency' ? 'domestic' : 'international'));
    const filter = regionFilters();
    return categoryMatch && (!regionChoice || (filter.region ? item.region === filter.region : item.geographic_region === filter.geographic_region));
  }
  function formatDate(date, precision) {
    if (!date) return '未提供发布时间';
    if (precision === 'day') return new Date(date).toLocaleDateString('zh-CN', {timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'});
    return new Date(date).toLocaleString('zh-CN', {year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false});
  }
  const language = item => ({zh: '中文原文', en: '英文原文', es: '西班牙文原文', ja: '日文原文', fr: '法文原文', de: '德文原文'}[item.lang] || '原始语言');
  const publicationDate = item => item.published_time_status === 'timezone_missing' ? (item.published_raw || '未提供发布时间') + '（来源未标时区）' :
    item.published_precision === 'day' && item.published_calendar_date ? item.published_calendar_date.replaceAll('-', '/') : formatDate(item.published_at, item.published_precision);
  function originalLink(item, label) {
    const link = element('a', '', label);
    try { const url = new URL(item.original_url); if (['http:', 'https:'].includes(url.protocol) && !url.username && !url.password) link.href = url.href; }
    catch { /* Invalid source links are never inserted as executable URLs. */ }
    link.target = '_blank'; link.rel = 'noopener noreferrer'; return link;
  }
  function renderItem(item, existing=null) {
    const row = existing || element('article', 'news-article');row.replaceChildren();row.classList.remove('has-thumbnail');row.dataset.articleId = item.id;
    const text=element('div','news-text');
    const meta = element('div', 'news-meta', [item.source_name, publicationDate(item), language(item)].filter(Boolean).join(' · '));
    const canRead = item.reading_mode === 'full_text', heading = element('h2');
    if (canRead) {
      const title = element('a', '', item.title); title.href = '#news/article/' + item.id;
      title.addEventListener('click', event => { event.preventDefault(); window.newsReader.open(item.id, title); }); heading.append(title);
    } else heading.append(originalLink(item, item.title));
    const bottom = element('div', 'news-row-bottom');
    const scope = ({full_text:'本站全文', link_only:'原文阅读', unavailable:'暂不可用'}[item.reading_mode] || '原文阅读');
    bottom.append(element('span', 'reading-badge', scope));
    if (canRead) bottom.append(originalLink(item, '查看原文 ↗'));
    const explain = element('button', 'link-button', '科普解读与提问'); explain.type = 'button';
    explain.addEventListener('click', () => window.newsReader.open(item.id, explain)); bottom.append(explain);
    text.append(meta, heading);
    if (canRead && item.summary?.trim()) text.append(element('p', '', item.summary));
    text.append(bottom);row.append(text);
    const thumbnail=item.thumbnail;
    if (thumbnail && ['nasa','esa'].includes(item.source_id) &&
        new RegExp('^/api/news/'+Number(item.id)+'/thumbnail\\?v=[a-f0-9]{24}$').test(thumbnail.url) && thumbnail.credit) {
      const figure=element('figure','news-thumbnail'), media=element('div','news-thumbnail-media'), image=element('img'),caption=element('figcaption','',thumbnail.credit);
      image.src=thumbnail.url;image.alt='';image.loading='lazy';image.decoding='async';
      image.addEventListener('error',()=>{if(figure.parentNode!==row)return;figure.remove();row.classList.remove('has-thumbnail');},{once:true});
      media.append(image);figure.append(media,caption);
      const knownRights=new Set(['https://www.nasa.gov/nasa-brand-center/images-and-media/',
        'https://www.esa.int/About_Us/Law_at_ESA/Intellectual_Property_Rights/ESA_copyright_notice',
        'https://creativecommons.org/licenses/by-sa/3.0/igo/']);
      if(knownRights.has(thumbnail.rights_url)){
        const rights=element('a','',thumbnail.credit);rights.href=thumbnail.rights_url;rights.target='_blank';rights.rel='noopener noreferrer';rights.setAttribute('aria-label','图片署名：'+thumbnail.credit+'；查看许可');caption.replaceChildren(rights);
      }
      row.classList.add('has-thumbnail');row.append(figure);
    }
    return row;
  }
  async function getJSON(path) {
    const response = await fetch(path, {signal: AbortSignal.timeout(15000)});
    if (!response.ok) throw new Error('HTTP ' + response.status); return response.json();
  }
  function renderSelect() {
    select.replaceChildren(); const all = element('option', '', '本组全部来源'); all.value = ''; select.append(all);
    sources.filter(matches).forEach(item => { const option = element('option', '', item.name + (!item.enabled ? '（采集未启用）' : '')); option.value = item.id; select.append(option); }); select.value = source;
    const options = [...select.options].map(option=>[option.value,option.textContent]);
    const common = new Set(['','cnsa','cmse','nasa','esa']);
    const preferred = options.filter(([id])=>common.has(id));
    const visible = new Set(preferred.length > 1 ? preferred.map(([id])=>id) : options.slice(0,5).map(([id])=>id));
    if(source) visible.add(source);
    const signature = JSON.stringify([options,[...visible]]);
    if (signature !== sourceSignature) {
      sourceSignature = signature; sourceOptions.replaceChildren();extraOptions.replaceChildren();
      options.forEach(([id,name])=>{
        const label = element('label','news-source-option'), radio = element('input'); radio.type='radio';radio.name='news-source-choice';radio.value=id;
        label.append(radio,element('span','',name));(visible.has(id)?sourceOptions:extraOptions).append(label);
        radio.addEventListener('change',()=>{if(radio.checked){select.value=id;select.dispatchEvent(new Event('change'));}});
      });
      moreSources.hidden=extraOptions.children.length===0;
      moreSummary.textContent='更多来源（'+extraOptions.children.length+'）';
    }
    controls.querySelectorAll('.news-source-options input').forEach(radio=>{radio.checked=radio.value===source;});
    updateSelectedSummary();
  }
  function updateSelectedSummary() {
    selectedSummary.textContent = categories.find(([id])=>id===category)[1] + (regionChoice ? ' · '+(regionSelect.selectedOptions[0]?.textContent || regionChoice) : '') + (source ? ' · '+(sources.find(item=>item.id===source)?.name || '所选来源') : ' · 全部来源');
    selectedSummary.title=selectedSummary.textContent;
    activeFilters.replaceChildren();
    for(const [field,value,label] of [['category',category,categories.find(([id])=>id===category)[1]],['region',regionChoice,regionSelect.selectedOptions[0]?.textContent],['source',source,sources.find(item=>item.id===source)?.name||source]]){
      if(!value)continue;const chip=element('button','',label+' ×');chip.type='button';chip.setAttribute('aria-label','移除筛选：'+label);
      chip.addEventListener('click',()=>{if(field==='category'){category='';regionChoice='';source='';}else if(field==='region'){regionChoice='';source='';}else source='';buttons.forEach(item=>{item.node.classList.toggle('active',item.id===category);item.node.setAttribute('aria-pressed',String(item.id===category));});renderRegion();renderSelect();load(true);reset.focus({preventScroll:true});});activeFilters.append(chip);
    }
  }
  function renderRegion() {
    regionLabel.hidden = category !== 'commercial'; regionSelect.replaceChildren();
    [['', '全部商业地区'], ['domestic', '国内'], ['international', '国际'], ...geographicRegions.map(item => [item.id, item.name])].forEach(([value, name]) => {
      const option = element('option', '', name); option.value = value; regionSelect.append(option);
    }); regionSelect.value = regionChoice;
  }
  function renderSources(items) {
    const relevant = items.filter(matches).filter(item => !source || item.id === source), dates = relevant.map(item => item.last_success_at).filter(Boolean).sort();
    const failures = relevant.filter(item => item.enabled && item.last_error), disabled = relevant.filter(item => !item.enabled);
    document.getElementById('news-update').textContent = (dates.length ? '最近成功采集：' + formatDate(dates.at(-1)) : '尚未成功采集') +
      (failures.length ? ' · ' + failures.length + '个来源更新失败，保留历史' : '') + (disabled.length ? ' · ' + disabled.length + '个来源未启用' : '');
    document.getElementById('news-update').title = relevant.map(item => item.name + '：' + (!item.enabled ? (item.availability_note || '未启用') + '；' : item.last_error ? '本轮失败或部分失败，保留历史；' : '') + '最近成功 ' + formatDate(item.last_success_at)).join('\n');
  }
  function renderPagination() {
    const blocked = busy || displayedKey !== key();
    totalDescription.textContent = displayedKey === null ? '正在读取结果…' : totalCount ? '共 ' + totalCount + ' 条 · 当前第 ' + currentPage + ' 页' : '共 0 条';
    list.setAttribute('aria-busy', String(busy));
    refresh.disabled = busy;
    for (const pager of pagers) {
      pager.nav.hidden = totalPages <= 1 || !totalCount;
      pager.previous.disabled = blocked || currentPage <= 1; pager.next.disabled = blocked || currentPage >= totalPages;
      pager.description.textContent = totalCount ? '第 ' + currentPage + ' / ' + totalPages + ' 页' : '暂无结果';
      pager.input.max = Math.max(1,totalPages); pager.input.value = currentPage; pager.input.disabled = pager.go.disabled = blocked || !totalCount;
      pager.numbers.replaceChildren();
      if (!totalCount) continue;
      const pages = new Set([1,totalPages]); for (let number=Math.max(1,currentPage-2);number<=Math.min(totalPages,currentPage+2);number++) pages.add(number);
      let last = 0;
      for (const number of [...pages].sort((a,b)=>a-b)) {
        if (last && number-last>1) pager.numbers.append(element('span', 'page-gap', '…'));
        const button = element('button', 'secondary' + (number===currentPage?' active':''), String(number));
        button.setAttribute('aria-label', '第 ' + number + ' 页'); if(number===currentPage)button.setAttribute('aria-current','page');
        button.disabled = blocked || number===currentPage; button.addEventListener('click',()=>load(false,number,true)); pager.numbers.append(button); last=number;
      }
    }
  }
  async function load(reset = false, targetPage = currentPage, scrollAfter = false) {
    delete status.dataset.tone;
    if (busy && !reset) return;
    if (!reset && displayedKey !== key()) return;
    const request = ++generation, requestKey = key();
    let succeeded = false;
    busy = true; renderPagination();
    status.textContent = displayedKey && displayedKey !== requestKey ? '正在切换筛选，下方暂为上一筛选结果…' : '正在读取已入库的新闻…';
    const params = new URLSearchParams({page: String(reset ? 1 : targetPage), page_size: String(PAGE_SIZE)});
    if (!reset && snapshot !== null) params.set('snapshot', snapshot);
    if (source) params.set('source', source); if (category) params.set('category', category);
    if (category === 'commercial' && regionChoice) { const filter = regionFilters(); Object.entries(filter).forEach(([name, value]) => params.set(name, value)); }
    try {
      const [data, state] = await Promise.all([getJSON('/api/news?' + params), getJSON('/api/news/sources')]); if (request !== generation) return;
      if (!Number.isInteger(data.page) || !Number.isInteger(data.total_pages)) throw new Error('pagination_unavailable');
      sources = state.items; geographicRegions = state.geographic_regions || []; renderRegion(); renderSelect(); const fragment = document.createDocumentFragment(); data.items.forEach(item => fragment.append(renderItem(item)));
      list.replaceChildren(fragment);
      displayedItems = new Map(data.items.map(item=>[String(item.id),item]));
      currentPage = data.page; totalPages = data.total_pages; totalCount = data.total; snapshot = data.snapshot;
      displayedKey = requestKey; renderSources(sources);updateDetails.classList.toggle('has-warning', sources.filter(matches).filter(item=>!source||item.id===source).some(item=>item.enabled&&item.last_error));
      resultLabel.textContent = '当前结果：' + categories.find(([id]) => id === category)[1] + (source ? ' / ' + (sources.find(item => item.id === source)?.name || '所选来源') : '');
      if (regionChoice) resultLabel.textContent += ' / ' + regionSelect.selectedOptions[0].textContent;
      resultLabel.hidden=!category&&!source&&!regionChoice;
      status.textContent = list.children.length ? '' : '此筛选下暂无已入库新闻。未启用的来源不会自动采集。';
      succeeded = true;
      if (scrollAfter) window.scrollTo({top: window.scrollY + resultBar.getBoundingClientRect().top - 24, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
    } catch (error) {
      if (request !== generation) return;
      status.dataset.tone='error';
      status.textContent = error.message === 'pagination_unavailable' ? '当前服务器尚未支持页码分页，请更新服务器版本。' :
        list.children.length ? '分页读取失败，保留当前页内容。请重试。' : '当前筛选读取失败，请刷新重试。';
    } finally { if (request === generation) { busy = false; renderPagination(); if (scrollAfter && succeeded) resultBar.focus({preventScroll:true}); } }
  }
  categories.forEach(([id, name]) => {
    const button = element('button', id === '' ? 'active' : '', name); button.setAttribute('aria-pressed', String(id === ''));
    button.addEventListener('click', () => { category = id; source = ''; regionChoice = ''; renderRegion(); renderSelect(); buttons.forEach(item => { item.node.classList.toggle('active', item.id === id); item.node.setAttribute('aria-pressed', String(item.id === id)); }); load(true); });
    buttons.push({id, node: button}); filters.append(button);
  });
  select.addEventListener('change', () => { source = select.value; renderSelect(); load(true); });
  regionSelect.addEventListener('change', () => { regionChoice = regionSelect.value; source = ''; renderSelect(); load(true); });
  const refresh = element('button', 'refresh-news', '刷新列表 ↻'); refresh.addEventListener('click', () => load(true)); resultActions.append(refresh);
  reset.addEventListener('click',()=>{category='';source='';regionChoice='';buttons.forEach(item=>{item.node.classList.toggle('active',item.id==='');item.node.setAttribute('aria-pressed',String(item.id===''));});renderRegion();renderSelect();load(true);});
  renderRegion(); renderSelect(); renderPagination(); load(true);
  document.addEventListener('readingchange', event => {
    const patch = event.detail, previous = displayedItems.get(String(patch?.id));
    const item = window.NewsPresentation.mergeItem(previous,patch);
    if (!item) return;
    const row = [...list.children].find(node=>node.dataset.articleId===String(item.id));
    if (!row) return;
    displayedItems.set(String(item.id),item);
    const fields=['title','source_name','published_at','reading_mode','summary','original_url','availability'];
    if (fields.every(name=>previous[name]===item[name])&&JSON.stringify(previous.thumbnail)===JSON.stringify(item.thumbnail)) return;
    renderItem(item,row);
  });
  window.newsList = {item(id) { const item=displayedItems.get(String(id));return item?{...item}:null; }};
})();
