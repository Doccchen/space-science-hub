'use strict';
(() => {
  const $ = id => document.getElementById(id), KEY = 'zhihang-research-preview-v1', WEEK = 7 * 86400000;
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; };
  const uid = () => crypto.randomUUID();
  let works = [], selected, available = false, sourceCount=4, wanfangEnabled = false, offlinePreview = false, serviceMessage = '正在检查知识库服务…', manageAction, opener;
  const pending = new Map();
  try { const saved = JSON.parse(localStorage.getItem(KEY)); works = (saved?.works || []).filter(w => w && typeof w.id === 'string' && typeof w.title === 'string' && Array.isArray(w.messages) && Date.now() - w.updated < WEEK).slice(0, 20); selected = works.some(w => w.id === saved.selected) ? saved.selected : works[0]?.id; } catch { /* A new browser or invalid saved preview starts empty. */ }
  const current = () => works.find(w => w.id === selected);
  function save() { try { const stored=works.map(work=>({...work,messages:work.messages.map(msg=>msg.type==='papers'?{...msg,papers:(msg.papers||[]).filter(p=>!p.sources?.includes('ScienceDirect')),transient_missing:msg.transient_missing||(msg.papers||[]).some(p=>p.sources?.includes('ScienceDirect'))}:msg)}));localStorage.setItem(KEY, JSON.stringify({selected, works:stored})); } catch { $('storage-note').textContent = '浏览器存储不可用或已满，最新记录未保存。'; } }
  function create() {
    if (works.length >= 20) { $('activity').textContent = '最多保留 20 项研究，请先删除不再需要的记录。'; return; }
    const work = {id: uid(), title: '新的研究', mode: 'papers', draft: '', messages: [], updated: Date.now(), session: null};
    works.unshift(work); selected = work.id; save(); render(); closeSidebar(); return work;
  }
  function update(work) { work.updated = Date.now(); save(); renderList(); if (work.id === selected) renderThread(); }
  function renderList() {
    $('work-list').replaceChildren();
    for (const work of [...works].sort((a,b) => b.updated - a.updated)) {
      const row = el('div', null, 'work-row'), button = el('button'); button.type = 'button'; button.setAttribute('aria-current', String(work.id === selected));
      button.append(el('strong', work.title), el('small', pending.has(work.id) ? '正在处理…' : work.demo ? '交互示例 · 演示内容' : new Date(work.updated).toLocaleDateString('zh-CN', {month:'numeric',day:'numeric'}) + ' · ' + (work.mode === 'papers' ? '论文查找' : '知识问答')));
      button.onclick = () => { selected = work.id; save(); render(); closeSidebar(); }; row.append(button); $('work-list').append(row);
    }
  }
  function setMode(mode) { const w = current(); w.draft = $('question').value; w.mode = mode; save(); renderComposer(); renderList(); $('question').focus(); }
  function renderComposer() {
    const w = current(), isPaper = w.mode === 'papers', busy = pending.has(w.id);
    document.querySelector('.workspace').dataset.empty = String(!w.messages.length);
    $('welcome-title').textContent = isPaper ? '我们要研究什么？' : '今天，想了解什么？';
    document.querySelectorAll('.mode-switch [data-mode]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === w.mode)));
    $('question').value = w.draft || ''; $('question').maxLength = isPaper ? 6000 : 1500;
    $('question').placeholder = isPaper ? '输入技术名称，或粘贴一段航天新闻…' : '向本站航天知识库提问…';
    $('question').disabled = busy;
    $('scope').textContent = isPaper ? (wanfangEnabled ? '中英文论文检索' : sourceCount+'源论文检索') : '航天知识库';
    $('input-note').textContent = isPaper ? '先识别主题，确认检索词后查找论文' : '独立知识库回答，不自动读取检索到的论文';
    $('service-note').textContent = w.demo ? '当前为交互示例，内容仅用于展示布局。' : isPaper ? '识别内容可能发送至模型；检索词将发送至论文来源。' : available ? '知识库会话有有效期与轮次限制，来源可展开查看。' : serviceMessage;
    if(offlinePreview && !w.demo)$('service-note').textContent = '离线交互预览 · 输入仅用于本机演示，不调用模型。';
    $('send').disabled = busy || !w.draft?.trim() || (!isPaper && !available);
    $('cancel').hidden = !busy; $('activity').textContent = pending.get(w.id)?.label || '';
    $('conversation').setAttribute('aria-busy', String(busy));
  }
  function render() { const w = current(); $('work-title').textContent = w.title; $('work-type').textContent = w.demo ? '交互示例' : '论文与知识'; renderList(); renderThread(); $('conversation').scrollTop = w.scroll || 0; }
  function renderThread() {
    const w = current(); $('welcome').hidden = w.messages.length > 0; $('messages').replaceChildren();
    for (const msg of w.messages) {
      const box = el('section', null, 'message ' + (msg.role === 'user' ? 'user' : msg.type === 'error' ? 'error' : 'assistant'));
      if (msg.role === 'user') box.textContent = msg.text;
      else {
        const heading = el('div', null, 'message-heading'), mark = el('img'); mark.src = '/assets/brand.svg'; mark.alt = '';
        heading.append(mark, el('span', msg.type === 'topics' ? '检索主题' : msg.type === 'papers' ? '论文检索' : msg.type === 'error' ? '本次请求未完成' : '知识库回答')); box.append(heading);
        if (msg.type === 'topics') renderTopics(box, msg, w);
        else if (msg.type === 'papers') renderPapers(box, msg, w);
        else {
          box.append(el('p', msg.text));
          if (msg.sources?.length) { const details = el('details', null, 'sources'); details.append(el('summary', '本次检索资料 · ' + msg.sources.length + ' 项')); for (const s of msg.sources) details.append(el('p', s.name + (s.positions?.length ? ' · 返回位置：' + s.positions.join('、') : ''))); if(msg.notice)details.append(el('p', msg.notice)); box.append(details); }
          if (msg.remaining != null) box.append(el('p', msg.remaining === 0 ? '本次已达到轮次上限，下次提问将开始新的知识库上下文。' : '本次知识库对话还可追问 ' + msg.remaining + ' 轮。', 'muted'));
        }
      }
      $('messages').append(box);
    }
    renderComposer();
  }
  function scrollEnd() { $('conversation').scrollTop = $('conversation').scrollHeight; }
  function link(text, url) {
    try { const parsed = new URL(url); if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) return null; const a = el('a', text); a.href = parsed.href; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a; } catch { return null; }
  }
  function renderTopics(box, msg, work) {
    box.append(el('p', '选择一个技术主题，确认或修改检索词。'));
    const choices = el('div', null, 'topic-options'), form = el('form', null, 'query-form'), input = el('input');
    input.value = msg.query || ''; input.required = true; input.minLength = 2; input.maxLength = 160; input.setAttribute('aria-label', '论文检索词');
    const zh = el('input'); zh.value=msg.query_zh || msg.topics?.[0]?.query_zh || msg.topics?.[0]?.name || ''; zh.maxLength=160;zh.setAttribute('aria-label','万方中文检索词');
    zh.oninput=()=>{msg.query_zh=zh.value;save();};
    for (const topic of msg.topics || []) { const b = el('button', topic.name); b.type = 'button'; b.setAttribute('aria-pressed', String(input.value === topic.query)); b.onclick = () => { input.value = topic.query; msg.query = topic.query; zh.value=topic.query_zh || topic.name;msg.query_zh=zh.value;choices.querySelectorAll('button').forEach(n => n.setAttribute('aria-pressed', String(n === b))); save(); }; choices.append(b); }
    input.oninput = () => { msg.query = input.value; save(); }; const submit = el('button', '查找论文', 'primary'); submit.disabled = pending.has(work.id); form.append(input, submit);
    if(wanfangEnabled){const label=el('label','万方中文检索词（可修改）','query-zh');label.append(zh);form.append(label);}
    form.onsubmit = event => { event.preventDefault(); search(work, input.value.trim(),wanfangEnabled ? zh.value.trim() : ''); };
    box.append(choices, form, el('p', msg.notice || '检索词可以直接修改；确认后再访问论文来源。', 'muted'));
  }
  function renderPapers(box, msg, work) {
    if(msg.transient_missing)box.append(el('p','ScienceDirect 结果不保存到浏览器，请重新检索查看。','muted'));
    box.append(el('p', '本次检索：' + msg.query + (msg.query_zh ? ' · 万方：' + msg.query_zh : ''), 'muted'));
    const sources = el('div', null, 'source-status'); for (const s of msg.sources || []) sources.append(el('span', s.source + ' · ' + (s.state === 'ok' ? s.count + ' 条' : s.message || '暂不可用'), s.state !== 'ok' ? 'failed' : '')); box.append(sources);
    const filters = el('div', null, 'filters'), year = el('select'), kind = el('select'), oa = el('input');
    year.setAttribute('aria-label','发表年份'); kind.setAttribute('aria-label','文献类型');
    year.append(new Option('全部年份',''), ...[...new Set((msg.papers || []).map(p => p.year).filter(Boolean))].sort((a,b)=>b-a).map(v=>new Option(String(v),String(v))));
    kind.append(...['全部类型','期刊论文','会议论文','预印本','技术报告','其他文献'].map((v,i)=>new Option(v,i?v:'')));
    msg.filters ||= {year:'',kind:'',oa:false}; year.value = msg.filters.year; kind.value = msg.filters.kind; oa.type = 'checkbox'; oa.checked = msg.filters.oa;
    for (const [text,control] of [['年份',year],['类型',kind],['公开全文',oa]]) { const l = el('label', text); l.append(control); filters.append(l); }
    const count = el('span'); filters.append(count); box.append(filters);
    if(work.demo)box.append(el('p', '演示内容：题名与摘要仅用于预览，不是真实文献。', 'muted'));
    const list = el('div'), more = el('button', '显示更多论文', 'text-button'); let shown = msg.shown || 5;
    const redraw = () => {
      const papers = (msg.papers || []).filter(p => (!year.value || String(p.year) === year.value) && (!kind.value || p.type === kind.value) && (!oa.checked || p.fulltext));
      count.textContent = papers.length + ' 篇'; list.replaceChildren();
      for (const p of papers.slice(0, shown)) {
        const row = el('article', null, 'paper'), title = el('h3'), open = el('button', p.title); open.type = 'button'; open.onclick = () => openPaper(p, open);
        title.append(open); row.append(el('p', [p.year, p.type, (p.sources || []).join(' / ')].filter(Boolean).join(' · '), 'meta'), title, el('p', [(p.authors || []).slice(0,3).join('、'), p.venue].filter(Boolean).join(' · '), 'authors'));
        const actions = el('div', null, 'paper-actions'), detail = el('button', '查看摘要与详情'); detail.type = 'button'; detail.onclick = () => openPaper(p, detail); actions.append(detail); const original = link('原文入口 ↗', p.url); if (original) actions.append(original); row.append(actions); list.append(row);
      }
      if (!papers.length) list.append(el('p', msg.papers?.length ? '当前筛选条件下没有论文，请放宽条件。' : '本次未取得论文记录，请修改检索词或前往来源网站查找。', 'muted'));
      more.hidden = shown >= papers.length;
    };
    for (const control of [year,kind,oa]) control.onchange = () => { msg.filters = {year:year.value,kind:kind.value,oa:oa.checked}; shown = 5; msg.shown = shown; save(); redraw(); };
    more.onclick = () => { shown += 5; msg.shown = shown; save(); redraw(); }; box.append(list, more);
    box.append(el('p', work.demo ? '演示内容：以下题名与摘要用于预览界面，不是真实检索结果。' : '按题名和摘要匹配，尚未读取全文。相关论文不代表新闻中的型号采用了该方法。', 'muted'));
    const links = el('div', null, 'paper-actions'); for (const item of msg.links || []) { const a = link(item.name + ' ↗', item.url); if (a) links.append(a); } box.append(links); redraw();
  }
  function openPaper(paper, button) {
    opener = button; const detail = $('paper-detail'); detail.replaceChildren(el('p', (paper.type || '文献信息') + ' · ' + (paper.year || '年份未提供'), 'muted'));
    const title = el('h2', paper.title); title.id = 'paper-title'; detail.append(title, el('p', (paper.authors || []).join('、') || '作者信息未提供', 'muted'));
    if(paper.doi) detail.append(el('p', 'DOI：' + paper.doi, 'muted'));
    detail.append(el('h3', '来源摘要'), el('p', paper.abstract || '来源未提供摘要，请前往原始页面查看。'));
    if(paper.reason) detail.append(el('p', paper.reason, 'muted'));
    for(const [text,url] of [['查看原始页面 ↗',paper.url],['公开全文入口 ↗',paper.fulltext]]) { const a = link(text,url); if(a)detail.append(a); }
    $('paper-dialog').showModal();
  }
  async function api(path, body, signal) {
    const response = await fetch(path, {method:body ? 'POST':'GET',credentials:'same-origin',cache:'no-store',headers:body ? {'Content-Type':'application/json'}:undefined,body:body ? JSON.stringify(body):undefined,signal});
    const data = await response.json(); if (!response.ok) { const error = new Error(data.error?.message || (typeof data.detail === 'string' ? data.detail : '服务暂不可用，请稍后重试。')); error.code = data.error?.code; throw error; } return data;
  }
  async function run(work, label, operation) {
    if (pending.has(work.id)) return;
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 135000); pending.set(work.id, {controller,label}); save(); renderList(); if(work.id === selected) renderThread();
    try { await operation(controller.signal); }
    catch (error) { if(works.includes(work)){ if(error.code === 'session_expired' || error.code === 'history_limit') work.session = null; work.messages.push({type:'error',text:error.name === 'AbortError' ? '已停止等待，尚未收到完整结果。记录已保留；停止等待不会撤销已经发送的服务请求。' : error.message + (error.code === 'session_expired' || error.code === 'history_limit' ? ' 下次提问将开始新的知识库上下文。' : '')}); } }
    finally { clearTimeout(timer); pending.delete(work.id); if(works.includes(work)){ update(work); if(work.id === selected)scrollEnd(); } }
  }
  function nameWork(work,text) { if(work.title === '新的研究')work.title = text.replace(/\s+/g,' ').slice(0,22); }
  async function search(work, query, query_zh='') {
    if(query.length < 2 || query.length > 160 || pending.has(work.id)) return;
    if(work.demo) { work.messages.push({type:'error',text:'交互示例不会调用真实检索。请新建研究后查找论文。'}); update(work); scrollEnd(); return; }
    work.messages.push({role:'user',text:'查找论文：' + query}); nameWork(work,query);
    await run(work,'正在检索论文来源，可切换到其他研究…',async signal => { const result = await api('/api/reader/search',{query,query_zh},signal); if(works.includes(work))work.messages.push({type:'papers',...result}); });
  }
  $('composer').onsubmit = async event => {
    event.preventDefault(); const work = current(), text = $('question').value.trim(); if(!text || pending.has(work.id))return;
    if(work.demo) { $('activity').textContent = '当前为交互示例，请新建研究后提交真实问题。'; return; }
    if(work.mode === 'knowledge' && !available) { $('activity').textContent = serviceMessage; return; }
    if(text.length > (work.mode === 'papers' ? 6000 : 1500)){ $('activity').textContent = '内容超过当前模式的长度限制，请精简后发送。'; return; }
    nameWork(work,text); work.messages.push({role:'user',text}); work.draft = '';
    if(work.mode === 'papers') await run(work,'正在识别技术主题…',async signal => {
      let result;
      try { result = await api('/api/reader/analyze',{text},signal); }
      catch(error) { if(error.name === 'AbortError')throw error; result = {topics:[],notice:'主题识别未完成，可修改下方检索词直接查找。'}; }
      if(works.includes(work))work.messages.push({type:'topics',topics:result.topics || [],query:result.topics?.[0]?.query || text.slice(0,160),query_zh:result.topics?.[0]?.query_zh || text.slice(0,160),notice:result.notice});
    });
    else await run(work,'正在检索知识库并整理回答…',async signal => {
      if(!work.session){ const data = await api('/api/ai/conversations',{},signal); work.session = data.conversation_id; }
      const result = await api('/api/ai/ask',{conversation_id:work.session,request_id:uid(),question:text},signal);
      if(works.includes(work)){work.messages.push({type:'answer',text:result.answer,sources:result.sources,notice:result.notice,remaining:result.remaining_rounds}); if(result.remaining_rounds === 0)work.session = null;}
    });
  };
  $('question').oninput = () => { const w = current(); w.draft = $('question').value; save(); $('send').disabled = !w.draft.trim() || pending.has(w.id) || (w.mode === 'knowledge' && !available); };
  let scrollTimer;
  $('conversation').addEventListener('scroll',()=>{current().scroll=$('conversation').scrollTop;clearTimeout(scrollTimer);scrollTimer=setTimeout(save,200);});
  $('question').onkeydown = event => { if(event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing){ event.preventDefault(); $('composer').requestSubmit(); } };
  document.querySelectorAll('.mode-switch button').forEach(b => b.onclick = () => setMode(b.dataset.mode));

  $('cancel').onclick = () => pending.get(selected)?.controller.abort(); $('new-work').onclick = () => {if(create())$('question').focus();};
  $('quick-new').onclick = $('new-work').onclick;
  function closeSidebar() { $('sidebar').classList.remove('open'); $('sidebar-shade').hidden = true; $('open-sidebar').setAttribute('aria-expanded','false'); $('sidebar').removeAttribute('role'); $('sidebar').removeAttribute('aria-modal'); }
  $('open-sidebar').onclick = () => { $('sidebar').classList.add('open'); $('sidebar-shade').hidden = false; $('open-sidebar').setAttribute('aria-expanded','true'); $('sidebar').setAttribute('role','dialog'); $('sidebar').setAttribute('aria-modal','true'); $('close-sidebar').focus(); };
  $('close-sidebar').onclick = () => { closeSidebar(); $('open-sidebar').focus(); }; $('sidebar-shade').onclick = $('close-sidebar').onclick;
  document.addEventListener('keydown', event => { if(!$('sidebar').classList.contains('open'))return; if(event.key === 'Escape'){ $('close-sidebar').click(); } if(event.key === 'Tab'){const nodes = [...$('sidebar').querySelectorAll('button')],first = nodes[0],last = nodes.at(-1); if(event.shiftKey && document.activeElement === first){event.preventDefault();last.focus();} else if(!event.shiftKey && document.activeElement === last){event.preventDefault();first.focus();}} });
  $('close-paper').onclick = () => $('paper-dialog').close(); $('paper-dialog').addEventListener('close',()=>opener?.isConnected && opener.focus());
  function manage(action) { manageAction = action; $('manage-title').textContent = action === 'rename' ? '重命名研究' : '删除这项研究？'; $('manage-copy').textContent = action === 'rename' ? '研究名称' : '将删除此浏览器中的记录与草稿，此操作无法撤销。'; $('name-input').hidden = action !== 'rename'; $('name-input').required = action === 'rename'; $('name-input').value = current().title; $('manage-confirm').textContent = action === 'rename' ? '保存' : '删除研究'; $('manage-dialog').showModal(); if(action === 'rename')$('name-input').select();else $('manage-cancel').focus(); }
  $('rename-work').onclick = () => manage('rename'); $('delete-work').onclick = () => manage('delete'); $('manage-cancel').onclick = () => $('manage-dialog').close();
  const recordActions=el('div',null,'record-actions');
  for(const [text,action] of [['重命名当前研究','rename'],['删除当前研究','delete']]){const button=el('button',text,'text-button');button.onclick=()=>{closeSidebar();manage(action);};recordActions.append(button);}
  $('sidebar').insertBefore(recordActions,document.querySelector('.side-bottom'));
  $('manage-form').onsubmit = event => { event.preventDefault(); const w = current(); if(manageAction === 'rename'){const name = $('name-input').value.trim();if(!name)return;w.title=name;} else {pending.get(w.id)?.controller.abort();works = works.filter(x=>x.id!==w.id);selected=works[0]?.id; if(w.session)fetch('/api/ai/conversations/'+encodeURIComponent(w.session),{method:'DELETE',credentials:'same-origin'}).catch(()=>{}); } $('manage-dialog').close(); if(!works.length)create();else{save();render();} };
  if(!works.length)create();else render();
  const params = new URLSearchParams(location.search); if(params.get('mode') === 'knowledge'){current().mode='knowledge';save();renderComposer();}
  async function boot() {
    try {const config=await api('/api/reader/config',null,AbortSignal.timeout(10000));wanfangEnabled=Boolean(config.wanfang_enabled);sourceCount=Number(config.source_count)||4;renderThread();}catch{/* Existing four-source search stays available. */}
    try { const status = await api('/api/ai/status',null,AbortSignal.timeout(10000)); available = Boolean(status.enabled); serviceMessage = status.message || '知识库服务暂未开放。'; offlinePreview = Boolean(status.preview || /离线/.test(serviceMessage)); if(offlinePreview)$('storage-note').nextElementSibling.textContent = '离线交互预览 · 未连接模型'; }
    catch { serviceMessage = '知识库服务暂不可用，仍可使用论文查找。'; }
    if(!pending.has(selected))renderComposer();
    const news = params.get('news'); if(!news || !/^[1-9]\d*$/.test(news))return;
    const work=create(); if(!work)return;
    await run(work,'正在带入新闻内容…',async signal => { const detail = await api('/api/news/'+news,null,signal); let body=''; try{const content=await api('/api/news/'+news+'/content',null,signal);body=(content.blocks||[]).map(b=>b.text||(b.items||[]).join(' ')).join('\n');}catch(error){if(error.name==='AbortError')throw error;} work.draft=[detail.title,body].filter(Boolean).join('\n\n').slice(0,6000);work.title=detail.title.slice(0,22); });
  }
  boot();
})();
